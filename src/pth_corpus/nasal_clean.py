"""Idempotent, atomic application of nasal listening decisions.

Reads ``data/review/nasal_decisions_*.csv`` (the single source of truth for
the human listening pass) and turns verdicts into corpus state changes:

- ``ok`` / ``skip``      no action;
- ``wrong_word``         exclude with ``audio_word_mismatch``;
- ``tone``               exclude with ``audio_tone_mismatch``;
- ``quality``            exclude with ``audio_quality``;
- ``shift``              re-cut from source audio when the decision carries
                         adjusted boundaries (within the raw bounds),
                         otherwise exclude with ``audio_shift``.

Exclusion follows the historical convention exactly: insert
``excluded_items`` in the master DB, move the WAV from ``derived/clips-v2/``
to ``derived/clips-excluded/``, update ``segments.clip_path``, append the
recovery row to ``derived/excluded_items.csv`` and regenerate
``derived/formal_corpus.csv``.

Re-cutting writes the new WAV over the clip path, updates the segment bounds
/ hash / algorithm version, stashes the original clip in
``derived/nasal-cleaning/recut-backup/`` and records a cumulative event in
``derived/nasal-cleaning/nasal_repair_report.json``.

Everything is validated up front (file existence, SHA-256 against the DB,
bound containment) and applied files-first-then-DB with rollback, mirroring
``repair.apply_adjustments``.  Re-running the same decisions CSV is a no-op;
``--undo`` walks the same trail backwards and restores clips and rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .audio_analysis import SAMPLE_RATE, decode_audio_ffmpeg
from .db import DEFAULT_DB_PATH, connect_db
from .segmentation import _wav_bytes

NASAL_RECUT_ALGORITHM_VERSION = "constrained-dp-v2+nasal-recut-v1"
NASAL_REASON_PREFIX = "nasal_review_"
EXCLUDED_DIRNAME = "clips-excluded"
FORMAL_CORPUS_RELPATH = "derived/formal_corpus.csv"
EXCLUDED_CSV_RELPATH = "derived/excluded_items.csv"
CLEANING_DIR_RELPATH = "derived/nasal-cleaning"
REPAIR_REPORT_RELPATH = f"{CLEANING_DIR_RELPATH}/nasal_repair_report.json"
BACKUP_DIR_RELPATH = f"{CLEANING_DIR_RELPATH}/recut-backup"

VERDICT_KIND = {
    "wrong_word": "audio_word_mismatch",
    "tone": "audio_tone_mismatch",
    "quality": "audio_quality",
    "shift": "audio_shift",
}
EXCLUDED_CSV_COLUMNS = [
    "item_id",
    "table_kind",
    "word_raw",
    "pinyin_nfc",
    "kinds",
    "detail",
    "old_clip_path",
    "new_clip_path",
]

Decoder = Callable[[str | Path], np.ndarray]


class NasalCleanError(RuntimeError):
    """Raised when nasal decisions cannot be applied safely."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _safe_path(root: Path, stored: str | None) -> Path:
    if not stored:
        raise NasalCleanError("database path is empty")
    root_resolved = root.expanduser().resolve()
    candidate = Path(str(stored))
    resolved = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve(
        strict=False
    )
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise NasalCleanError(f"path escapes data_root: {stored}") from exc
    return resolved


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _read_original(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NasalCleanError(f"cannot read {path}: {exc}") from exc


def _excluded_target(clip_path: str) -> str:
    """Map a clips-v2 relative path to the clips-excluded relative path."""
    normalized = clip_path.replace("\\", "/")
    marker = "clips-v2/"
    if marker not in normalized:
        raise NasalCleanError(
            f"clip path does not live under clips-v2: {clip_path}"
        )
    return normalized.replace(marker, f"{EXCLUDED_DIRNAME}/", 1)


def load_decisions(paths: list[str | Path]) -> dict[str, dict[str, str]]:
    """Merge decision CSVs; conflicting verdicts for one item are rejected."""
    merged: dict[str, dict[str, str]] = {}
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise NasalCleanError(f"decisions CSV does not exist: {path}")
        with open(path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            item_id = str(row.get("item_id") or "").strip()
            if not item_id:
                raise NasalCleanError(f"decision row without item_id in {path}")
            verdict = str(row.get("verdict") or "").strip().lower()
            if verdict not in {"ok", "wrong_word", "shift", "tone", "quality", "skip"}:
                raise NasalCleanError(
                    f"unknown verdict {verdict!r} for {item_id} in {path}"
                )
            existing = merged.get(item_id)
            if existing is not None and existing["verdict"] != verdict:
                raise NasalCleanError(
                    f"conflicting verdicts for {item_id}: "
                    f"{existing['verdict']} vs {verdict}"
                )
            merged[item_id] = dict(row)
            merged[item_id]["verdict"] = verdict
    return merged


def _formal_corpus_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT e.item_id, e.table_kind, e.word_raw, e.pinyin_nfc, e.global_seq,
               s.clip_path, s.clip_sha256, s.confidence
        FROM entries AS e
        JOIN segments AS s ON s.item_id = e.item_id
        LEFT JOIN excluded_items AS x ON x.item_id = e.item_id
        WHERE x.item_id IS NULL
        ORDER BY CASE e.table_kind WHEN 'table1' THEN 0 ELSE 1 END,
                 e.global_seq
        """
    ).fetchall()
    return [
        {
            "item_id": str(row["item_id"]),
            "table_kind": str(row["table_kind"]),
            "word_raw": str(row["word_raw"]),
            "pinyin_nfc": str(row["pinyin_nfc"]),
            "global_seq": str(row["global_seq"]),
            "clip_path": str(row["clip_path"]),
            "clip_sha256": str(row["clip_sha256"]),
            "confidence": (
                f"{round(float(row['confidence'] or 0.0), 4):g}"
                if row["confidence"] is not None
                else ""
            ),
        }
        for row in rows
    ]


def _formal_corpus_payload(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "item_id",
            "table_kind",
            "word_raw",
            "pinyin_nfc",
            "global_seq",
            "clip_path",
            "clip_sha256",
            "confidence",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _excluded_csv_payload(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXCLUDED_CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _load_excluded_csv(root: Path) -> tuple[list[dict[str, str]], Path]:
    path = root / EXCLUDED_CSV_RELPATH
    if not path.is_file():
        raise NasalCleanError(f"recovery manifest missing: {path}")
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, path


def _load_repair_events(root: Path) -> tuple[list[dict[str, Any]], Path]:
    path = root / REPAIR_REPORT_RELPATH
    if not path.is_file():
        return [], path
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NasalCleanError(f"cannot read nasal repair report: {exc}") from exc
    events = value.get("events", []) if isinstance(value, dict) else []
    return [event for event in events if isinstance(event, dict)], path


def _fetch_item_state(
    connection: sqlite3.Connection, item_id: str
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT e.item_id, e.word_raw, e.pinyin_nfc, e.table_kind, e.global_seq,
               s.segment_id, s.clip_path, s.clip_sha256, s.start_ms, s.end_ms,
               s.start_ms_raw, s.end_ms_raw, s.confidence, s.algorithm_version,
               sp.audio_path, sp.audio_sha256,
               x.item_id AS excluded_item_id, x.reason, x.kind, x.detail
        FROM entries AS e
        JOIN segments AS s ON s.item_id = e.item_id
        JOIN source_pages AS sp ON sp.id = e.source_page_id
        LEFT JOIN excluded_items AS x ON x.item_id = e.item_id
        WHERE e.item_id = ?
        """,
        (item_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _read_file_with_db_hash(
    root: Path, stored_path: str | None, db_hash: str | None, what: str
) -> tuple[Path, bytes]:
    path = _safe_path(root, stored_path)
    if not path.is_file():
        raise NasalCleanError(f"{what} does not exist: {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise NasalCleanError(f"cannot read {what} {path}: {exc}") from exc
    if db_hash and _sha256_bytes(payload) != db_hash:
        raise NasalCleanError(
            f"{what} hash does not match the database: {path}"
        )
    return path, payload


def _validated_recut_plan(
    root: Path,
    state: dict[str, Any],
    adjusted_start: int,
    adjusted_end: int,
    decoder: Decoder,
) -> dict[str, Any]:
    raw_start = int(state["start_ms_raw"] or state["start_ms"])
    raw_end = int(state["end_ms_raw"] or state["end_ms"])
    if not (raw_start <= adjusted_start < adjusted_end <= raw_end):
        raise NasalCleanError(
            f"{state['item_id']}: adjusted bounds {adjusted_start}-{adjusted_end} "
            f"outside raw bounds {raw_start}-{raw_end}"
        )
    clip_path, old_bytes = _read_file_with_db_hash(
        root, state["clip_path"], state["clip_sha256"], "clip"
    )
    source_path, _ = _read_file_with_db_hash(
        root, state["audio_path"], state["audio_sha256"], "source audio"
    )
    try:
        samples = np.asarray(decoder(source_path))
    except Exception as exc:
        raise NasalCleanError(
            f"{state['item_id']}: source decode failed: {exc}"
        ) from exc
    if samples.ndim != 1 or samples.size == 0 or not np.isfinite(samples).all():
        raise NasalCleanError(f"{state['item_id']}: decoded source is not usable mono audio")
    start_sample = int(round(adjusted_start * SAMPLE_RATE / 1000))
    # Derive the end from the duration so the frame count always equals
    # round((end-start) * SAMPLE_RATE / 1000), which is what qa --scope full
    # recomputes from the stored bounds.
    end_sample = start_sample + int(
        round((adjusted_end - adjusted_start) * SAMPLE_RATE / 1000)
    )
    if start_sample < 0 or end_sample <= start_sample or end_sample > samples.size:
        raise NasalCleanError(
            f"{state['item_id']}: sample bounds {start_sample}-{end_sample} "
            f"outside source length {samples.size}"
        )
    payload = _wav_bytes(samples[start_sample:end_sample].astype(np.float32, copy=False))
    with wave.open(io.BytesIO(payload), "rb") as handle:
        if (
            handle.getnchannels() != 1
            or handle.getsampwidth() != 2
            or handle.getframerate() != SAMPLE_RATE
            or handle.getnframes() != end_sample - start_sample
        ):
            raise NasalCleanError(f"{state['item_id']}: generated WAV is invalid")
    new_hash = _sha256_bytes(payload)
    if new_hash == state["clip_sha256"]:
        raise NasalCleanError(
            f"{state['item_id']}: adjusted bounds produce the same clip hash"
        )
    return {
        "item_id": state["item_id"],
        "kind": "recut",
        "clip_path": clip_path,
        "old_bytes": old_bytes,
        "payload": payload,
        "old_start_ms": int(state["start_ms"]),
        "old_end_ms": int(state["end_ms"]),
        "new_start_ms": adjusted_start,
        "new_end_ms": adjusted_end,
        "old_clip_sha256": str(state["clip_sha256"]),
        "new_clip_sha256": new_hash,
        "old_algorithm_version": str(state["algorithm_version"] or ""),
        "boundary_adjustment_ms": max(
            0, (adjusted_start - raw_start) + (raw_end - adjusted_end)
        ),
    }


def apply_nasal_decisions(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    decisions_csvs: list[str | Path],
    dry_run: bool = False,
    decoder: Decoder | None = None,
) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    db = Path(db_path)
    decoder = decoder or decode_audio_ffmpeg
    if str(db) != ":memory:" and not db.is_file():
        raise NasalCleanError(f"database does not exist: {db}")

    decisions = load_decisions(decisions_csvs)
    actionable = {
        item_id: row
        for item_id, row in decisions.items()
        if row["verdict"] in VERDICT_KIND
    }
    backup_dir = root / BACKUP_DIR_RELPATH
    repair_path = root / REPAIR_REPORT_RELPATH
    excluded_csv_path = root / EXCLUDED_CSV_RELPATH
    formal_csv_path = root / FORMAL_CORPUS_RELPATH
    prior_events, _ = _load_repair_events(root)
    prior_event_keys = {
        (event.get("item_id"), event.get("new_start_ms"), event.get("new_end_ms"))
        for event in prior_events
    }

    plans: list[dict[str, Any]] = []
    skipped_already: list[str] = []
    recut_conflict: list[str] = []
    with connect_db(db) as connection:
        for item_id, decision in sorted(actionable.items()):
            state = _fetch_item_state(connection, item_id)
            if state is None:
                raise NasalCleanError(f"item not found in corpus: {item_id}")
            verdict = decision["verdict"]
            if state["excluded_item_id"] is not None:
                # Idempotency: verify the historical move actually happened
                # and the segment row already points at clips-excluded.
                if str(state["clip_path"]).startswith(f"derived/{EXCLUDED_DIRNAME}/"):
                    if _safe_path(root, state["clip_path"]).is_file():
                        skipped_already.append(item_id)
                        continue
                    raise NasalCleanError(
                        f"{item_id}: excluded row exists but the clip is missing "
                        f"at {state['clip_path']}; partial state, refusing to continue"
                    )
                raise NasalCleanError(
                    f"{item_id}: excluded row exists but segments.clip_path still "
                    f"points at {state['clip_path']}; partial state, refusing to continue"
                )
            if state["algorithm_version"] == NASAL_RECUT_ALGORITHM_VERSION:
                skipped_already.append(item_id)
                continue
            if verdict == "shift" and decision.get("adjusted_start_ms") and decision.get("adjusted_end_ms"):
                adjusted_start = int(decision["adjusted_start_ms"])
                adjusted_end = int(decision["adjusted_end_ms"])
                key = (item_id, adjusted_start, adjusted_end)
                if key in prior_event_keys:
                    skipped_already.append(item_id)
                    continue
                existing_recut = any(
                    event.get("item_id") == item_id for event in prior_events
                )
                if existing_recut:
                    recut_conflict.append(item_id)
                    continue
                plans.append(
                    _validated_recut_plan(
                        root, state, adjusted_start, adjusted_end, decoder
                    )
                )
            else:
                kind = VERDICT_KIND[verdict]
                clip_path, old_bytes = _read_file_with_db_hash(
                    root, state["clip_path"], state["clip_sha256"], "clip"
                )
                old_rel = str(state["clip_path"])
                new_rel = _excluded_target(old_rel)
                new_path = root / new_rel
                if new_path.is_file():
                    raise NasalCleanError(
                        f"{item_id}: destination already exists: {new_rel}"
                    )
                notes = (decision.get("notes") or "").strip()
                detail = notes or f"nasal human review: {verdict}"
                plans.append(
                    {
                        "item_id": item_id,
                        "kind": "exclude",
                        "exclude_kind": kind,
                        "clip_path": clip_path,
                        "new_path": new_path,
                        "new_rel": new_rel,
                        "old_rel": old_rel,
                        "old_bytes": old_bytes,
                        "detail": detail,
                    }
                )

        if dry_run:
            return _dry_run_summary(plans, skipped_already, recut_conflict)

        if recut_conflict:
            raise NasalCleanError(
                f"items already re-cut with different bounds, undo first: "
                f"{', '.join(sorted(recut_conflict))}"
            )

        # Stage every replacement payload before touching any destination.
        staged: dict[str, Path] = {}
        try:
            for plan in plans:
                if plan["kind"] == "recut":
                    descriptor, name = tempfile.mkstemp(
                        prefix=f".{plan['clip_path'].name}.nasal-",
                        dir=str(plan["clip_path"].parent),
                    )
                    temporary = Path(name)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(plan["payload"])
                        handle.flush()
                        os.fsync(handle.fileno())
                    staged[plan["item_id"]] = temporary
        except Exception:
            for temporary in staged.values():
                try:
                    temporary.unlink()
                except OSError:
                    pass
            raise

        # Original derived-artifact payloads for rollback.
        excluded_original = _read_original(excluded_csv_path)
        formal_original = _read_original(formal_csv_path)
        repair_original = _read_original(repair_path)

        replaced: list[tuple[Path, bytes | None, Path | None]] = []
        try:
            # 1. Files first (mirrors repair.apply_adjustments).
            for plan in plans:
                if plan["kind"] == "recut":
                    backup_path = backup_dir / f"{plan['item_id']}.wav"
                    _atomic_write_bytes(backup_path, plan["old_bytes"])
                    os.replace(staged[plan["item_id"]], plan["clip_path"])
                    replaced.append((plan["clip_path"], plan["old_bytes"], backup_path))
                else:
                    plan["new_path"].parent.mkdir(parents=True, exist_ok=True)
                    os.replace(plan["clip_path"], plan["new_path"])
                    replaced.append((plan["clip_path"], plan["old_bytes"], plan["new_path"]))

            # 2. Database in one transaction.
            connection.execute("BEGIN")
            for plan in plans:
                if plan["kind"] == "recut":
                    cursor = connection.execute(
                        """
                        UPDATE segments
                        SET start_ms = ?, end_ms = ?,
                            start_ms_adjusted = ?, end_ms_adjusted = ?,
                            boundary_adjustment_ms = ?,
                            clip_sha256 = ?, algorithm_version = ?
                        WHERE segment_id = ? AND item_id = ?
                        """,
                        (
                            plan["new_start_ms"],
                            plan["new_end_ms"],
                            plan["new_start_ms"],
                            plan["new_end_ms"],
                            plan["boundary_adjustment_ms"],
                            plan["new_clip_sha256"],
                            NASAL_RECUT_ALGORITHM_VERSION,
                            _segment_id_for(connection, plan["item_id"]),
                            plan["item_id"],
                        ),
                    )
                else:
                    cursor = connection.execute(
                        "UPDATE segments SET clip_path = ? WHERE item_id = ?",
                        (plan["new_rel"], plan["item_id"]),
                    )
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO excluded_items
                            (item_id, reason, kind, detail, created_at)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            plan["item_id"],
                            NASAL_REASON_PREFIX + _batch_label(decisions_csvs),
                            plan["exclude_kind"],
                            plan["detail"],
                        ),
                    )
                if cursor.rowcount != 1:
                    raise NasalCleanError(
                        f"{plan['item_id']}: segment disappeared during update"
                    )
            connection.commit()

            # 3. Derived artifacts, atomically.
            _write_derived_artifacts(
                root, db, plans, decisions, decisions_csvs, prior_events
            )
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            for destination, old_bytes, companion in reversed(replaced):
                try:
                    _atomic_write_bytes(destination, old_bytes)
                except OSError:
                    pass
                if companion is not None and companion != destination:
                    try:
                        companion.unlink()
                    except OSError:
                        pass
            for temporary in staged.values():
                try:
                    temporary.unlink()
                except OSError:
                    pass
            _restore_original(excluded_csv_path, excluded_original)
            _restore_original(formal_csv_path, formal_original)
            _restore_original(repair_path, repair_original)
            raise
        for temporary in staged.values():
            try:
                temporary.unlink()
            except OSError:
                pass

    summary = _apply_summary(plans, skipped_already)
    summary["command"] = "nasal-clean"
    summary["operation"] = "apply"
    summary["status"] = "succeeded"
    summary["dry_run"] = False
    summary["report"] = str(repair_path.relative_to(root)) if repair_path.is_file() else None
    return summary


def _segment_id_for(connection: sqlite3.Connection, item_id: str) -> int:
    row = connection.execute(
        "SELECT segment_id FROM segments WHERE item_id = ?", (item_id,)
    ).fetchone()
    if row is None:
        raise NasalCleanError(f"{item_id}: no segment row")
    return int(row["segment_id"])


def _manifest_old_path(root: Path, item_id: str) -> str:
    rows, _ = _load_excluded_csv(root)
    for row in rows:
        if row["item_id"] == item_id:
            return str(row["old_clip_path"])
    raise NasalCleanError(f"{item_id}: no manifest row to recover the old clip path")


def _batch_label(decisions_csvs: list[str | Path]) -> str:
    stems = "_".join(sorted(Path(p).stem for p in decisions_csvs))
    return stems.replace("nasal_decisions_", "")


def _write_derived_artifacts(
    root: Path,
    db_path: Path,
    plans: list[dict[str, Any]],
    decisions: dict[str, dict[str, str]],
    decisions_csvs: list[str | Path],
    prior_events: list[dict[str, Any]],
) -> None:
    excluded_rows, excluded_path = _load_excluded_csv(root)
    existing_excluded = {row["item_id"] for row in excluded_rows}
    for plan in plans:
        if plan["kind"] != "exclude":
            continue
        if plan["item_id"] in existing_excluded:
            continue
        state_row = decisions[plan["item_id"]]
        excluded_rows.append(
            {
                "item_id": plan["item_id"],
                "table_kind": "",  # filled below from DB
                "word_raw": state_row.get("word", ""),
                "pinyin_nfc": state_row.get("pinyin", ""),
                "kinds": plan["exclude_kind"],
                "detail": plan["detail"],
                "old_clip_path": plan["old_rel"],
                "new_clip_path": plan["new_rel"],
            }
        )
    # Fill table_kind from the DB for freshly appended rows.
    with connect_db(db_path) as connection:
        table_kinds = {
            row["item_id"]: str(row["table_kind"])
            for row in connection.execute(
                "SELECT item_id, table_kind FROM entries"
            ).fetchall()
        }
        for row in excluded_rows:
            if not row["table_kind"]:
                row["table_kind"] = table_kinds.get(row["item_id"], "")
        formal_rows = _formal_corpus_rows(connection)
    _atomic_write_bytes(excluded_path, _excluded_csv_payload(excluded_rows))
    _atomic_write_bytes(root / FORMAL_CORPUS_RELPATH, _formal_corpus_payload(formal_rows))

    recut_events = [
        {
            "algorithm_version": NASAL_RECUT_ALGORITHM_VERSION,
            "item_id": plan["item_id"],
            "old_start_ms": plan["old_start_ms"],
            "old_end_ms": plan["old_end_ms"],
            "new_start_ms": plan["new_start_ms"],
            "new_end_ms": plan["new_end_ms"],
            "old_clip_sha256": plan["old_clip_sha256"],
            "new_clip_sha256": plan["new_clip_sha256"],
            "old_algorithm_version": plan["old_algorithm_version"],
            "backup": f"{BACKUP_DIR_RELPATH}/{plan['item_id']}.wav",
            "applied_at": _now_iso(),
        }
        for plan in plans
        if plan["kind"] == "recut"
    ]
    if recut_events:
        seen = {(e.get("item_id"), e.get("new_start_ms"), e.get("new_end_ms")) for e in prior_events}
        merged = [e for e in prior_events if (e.get("item_id"), e.get("new_start_ms"), e.get("new_end_ms")) in seen]
        merged.extend(
            e for e in recut_events
            if (e["item_id"], e["new_start_ms"], e["new_end_ms"]) not in seen
        )
        merged.sort(key=lambda e: (str(e["item_id"]), e.get("new_start_ms", 0)))
        _atomic_write_bytes(
            root / REPAIR_REPORT_RELPATH,
            _json_bytes(
                {
                    "command": "nasal-clean",
                    "operation": "recut",
                    "algorithm_version": NASAL_RECUT_ALGORITHM_VERSION,
                    "affected": len(recut_events),
                    "events": merged,
                }
            ),
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _restore_original(path: Path, original: bytes | None) -> None:
    try:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_write_bytes(path, original)
    except OSError:
        pass


def _dry_run_summary(
    plans: list[dict[str, Any]],
    skipped_already: list[str],
    recut_conflict: list[str],
) -> dict[str, Any]:
    actions: dict[str, list[dict[str, Any]]] = {"exclude": [], "recut": []}
    for plan in plans:
        if plan["kind"] == "recut":
            actions["recut"].append(
                {
                    "item_id": plan["item_id"],
                    "old_bounds": [plan["old_start_ms"], plan["old_end_ms"]],
                    "new_bounds": [plan["new_start_ms"], plan["new_end_ms"]],
                    "new_clip_sha256": plan["new_clip_sha256"],
                }
            )
        else:
            actions["exclude"].append(
                {
                    "item_id": plan["item_id"],
                    "kind": plan["exclude_kind"],
                    "new_clip_path": plan["new_rel"],
                }
            )
    return {
        "command": "nasal-clean",
        "operation": "apply",
        "dry_run": True,
        "status": "planned",
        "exclude_count": len(actions["exclude"]),
        "recut_count": len(actions["recut"]),
        "already_applied": len(skipped_already),
        "recut_conflicts": recut_conflict,
        "exclude": actions["exclude"],
        "recut": actions["recut"],
    }


def _apply_summary(plans: list[dict[str, Any]], skipped: list[str]) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    recut = 0
    items: list[dict[str, Any]] = []
    for plan in plans:
        if plan["kind"] == "recut":
            recut += 1
            items.append(
                {
                    "item_id": plan["item_id"],
                    "action": "recut",
                    "new_bounds": [plan["new_start_ms"], plan["new_end_ms"]],
                    "new_clip_sha256": plan["new_clip_sha256"],
                }
            )
        else:
            kinds[plan["exclude_kind"]] = kinds.get(plan["exclude_kind"], 0) + 1
            items.append(
                {
                    "item_id": plan["item_id"],
                    "action": "exclude",
                    "kind": plan["exclude_kind"],
                    "new_clip_path": plan["new_rel"],
                }
            )
    return {
        "excluded": len(items) - recut,
        "recut": recut,
        "already_applied": len(skipped),
        "kinds": kinds,
        "items": items,
    }


def undo_nasal_clean(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    decisions_csvs: list[str | Path] | None = None,
    item_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Reverse every nasal-clean action for the requested items."""
    root = Path(data_root).expanduser().resolve()
    db = Path(db_path)
    if str(db) != ":memory:" and not db.is_file():
        raise NasalCleanError(f"database does not exist: {db}")

    targets: set[str] = set(item_ids or [])
    if decisions_csvs:
        targets.update(load_decisions(decisions_csvs).keys())
    if not targets:
        raise NasalCleanError("undo requires --undo or --undo-item")

    backup_dir = root / BACKUP_DIR_RELPATH
    repair_path = root / REPAIR_REPORT_RELPATH
    prior_events, _ = _load_repair_events(root)

    restore_exclusions: list[dict[str, Any]] = []
    restore_recuts: list[dict[str, Any]] = []
    no_ops: list[str] = []
    with connect_db(db) as connection:
        for item_id in sorted(targets):
            state = _fetch_item_state(connection, item_id)
            if state is None:
                raise NasalCleanError(f"item not found in corpus: {item_id}")
            is_nasal_recut = state["algorithm_version"] == NASAL_RECUT_ALGORITHM_VERSION
            is_nasal_excluded = bool(
                state["excluded_item_id"]
                and str(state["reason"] or "").startswith(NASAL_REASON_PREFIX)
            )
            if is_nasal_excluded and is_nasal_recut:
                raise NasalCleanError(
                    f"{item_id}: both excluded and re-cut; refusing ambiguous undo"
                )
            if is_nasal_excluded:
                new_rel = str(state["clip_path"])
                old_rel = _manifest_old_path(root, item_id)
                new_path = _safe_path(root, new_rel)
                if not new_path.is_file():
                    raise NasalCleanError(
                        f"{item_id}: excluded clip missing at {new_rel}"
                    )
                old_path = _safe_path(root, old_rel)
                restore_exclusions.append(
                    {
                        "item_id": item_id,
                        "old_rel": old_rel,
                        "new_rel": new_rel,
                        "new_path": new_path,
                        "old_path": old_path,
                    }
                )
            elif is_nasal_recut:
                backup_path = backup_dir / f"{item_id}.wav"
                if not backup_path.is_file():
                    raise NasalCleanError(
                        f"{item_id}: recut backup missing at {backup_path}; "
                        "cannot restore the original clip"
                    )
                event = next(
                    (e for e in prior_events if e.get("item_id") == item_id), None
                )
                if event is None:
                    raise NasalCleanError(
                        f"{item_id}: recut event missing from the repair report"
                    )
                clip_path = _safe_path(root, state["clip_path"])
                if not clip_path.is_file():
                    raise NasalCleanError(f"{item_id}: clip missing at {state['clip_path']}")
                backup_bytes = backup_path.read_bytes()
                if _sha256_bytes(backup_bytes) != str(event.get("old_clip_sha256")):
                    raise NasalCleanError(
                        f"{item_id}: backup hash does not match the repair report"
                    )
                restore_recuts.append(
                    {
                        "item_id": item_id,
                        "clip_path": clip_path,
                        "backup_path": backup_path,
                        "backup_bytes": backup_bytes,
                        "event": event,
                    }
                )
            else:
                no_ops.append(item_id)

        if dry_run:
            return {
                "command": "nasal-clean",
                "operation": "undo",
                "dry_run": True,
                "status": "planned",
                "restore_exclusions": [r["item_id"] for r in restore_exclusions],
                "restore_recuts": [r["item_id"] for r in restore_recuts],
                "no_ops": no_ops,
            }

        excluded_original = _read_original(root / EXCLUDED_CSV_RELPATH)
        formal_original = _read_original(root / FORMAL_CORPUS_RELPATH)
        repair_original = _read_original(repair_path)

        replaced: list[tuple[Path, bytes | None, Path | None]] = []
        try:
            # 1. Files.
            for plan in restore_exclusions:
                if plan["old_path"].is_file():
                    raise NasalCleanError(
                        f"{plan['item_id']}: original clip path already occupied: "
                        f"{plan['old_rel']}"
                    )
                plan["old_path"].parent.mkdir(parents=True, exist_ok=True)
                os.replace(plan["new_path"], plan["old_path"])
                replaced.append((plan["new_path"], None, plan["old_path"]))
            for plan in restore_recuts:
                current_bytes = plan["clip_path"].read_bytes()
                _atomic_write_bytes(plan["clip_path"], plan["backup_bytes"])
                plan["current_bytes"] = current_bytes
                replaced.append((plan["clip_path"], current_bytes, plan["backup_path"]))

            # 2. Database.
            connection.execute("BEGIN")
            for plan in restore_exclusions:
                connection.execute(
                    "DELETE FROM excluded_items WHERE item_id = ?", (plan["item_id"],)
                )
                connection.execute(
                    "UPDATE segments SET clip_path = ? WHERE item_id = ?",
                    (plan["old_rel"], plan["item_id"]),
                )
            for plan in restore_recuts:
                event = plan["event"]
                connection.execute(
                    """
                    UPDATE segments
                    SET start_ms = ?, end_ms = ?,
                        start_ms_adjusted = ?, end_ms_adjusted = ?,
                        boundary_adjustment_ms = 0,
                        clip_sha256 = ?, algorithm_version = ?
                    WHERE item_id = ?
                    """,
                    (
                        event["old_start_ms"],
                        event["old_end_ms"],
                        event["old_start_ms"],
                        event["old_end_ms"],
                        event["old_clip_sha256"],
                        event.get("old_algorithm_version") or "constrained-dp-v2-full",
                        plan["item_id"],
                    ),
                )
            connection.commit()

            # 3. Derived artifacts.
            _write_undo_artifacts(
                root,
                connection,
                restore_exclusions,
                restore_recuts,
                prior_events,
            )
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            for destination, old_bytes, companion in reversed(replaced):
                try:
                    if old_bytes is None:
                        destination.unlink(missing_ok=True)
                    else:
                        _atomic_write_bytes(destination, old_bytes)
                except OSError:
                    pass
                if companion is not None:
                    try:
                        _atomic_write_bytes(companion, b"")
                        companion.unlink()
                    except OSError:
                        pass
            _restore_original(root / EXCLUDED_CSV_RELPATH, excluded_original)
            _restore_original(root / FORMAL_CORPUS_RELPATH, formal_original)
            _restore_original(repair_path, repair_original)
            raise

        for plan in restore_recuts:
            try:
                plan["backup_path"].unlink()
            except OSError:
                pass

    return {
        "command": "nasal-clean",
        "operation": "undo",
        "status": "succeeded",
        "dry_run": False,
        "restored_exclusions": [r["item_id"] for r in restore_exclusions],
        "restored_recuts": [r["item_id"] for r in restore_recuts],
        "no_ops": no_ops,
    }


def _write_undo_artifacts(
    root: Path,
    connection: sqlite3.Connection,
    restore_exclusions: list[dict[str, Any]],
    restore_recuts: list[dict[str, Any]],
    prior_events: list[dict[str, Any]],
) -> None:
    excluded_rows, excluded_path = _load_excluded_csv(root)
    undo_ids = {r["item_id"] for r in restore_exclusions}
    excluded_rows = [row for row in excluded_rows if row["item_id"] not in undo_ids]
    formal_rows = _formal_corpus_rows(connection)
    _atomic_write_bytes(excluded_path, _excluded_csv_payload(excluded_rows))
    _atomic_write_bytes(root / FORMAL_CORPUS_RELPATH, _formal_corpus_payload(formal_rows))

    recut_ids = {r["item_id"] for r in restore_recuts}
    remaining = [e for e in prior_events if e.get("item_id") not in recut_ids]
    _atomic_write_bytes(
        root / REPAIR_REPORT_RELPATH,
        _json_bytes(
            {
                "command": "nasal-clean",
                "operation": "recut",
                "algorithm_version": NASAL_RECUT_ALGORITHM_VERSION,
                "affected": len(remaining),
                "events": remaining,
            }
        ),
    )


__all__ = [
    "NASAL_RECUT_ALGORITHM_VERSION",
    "NASAL_REASON_PREFIX",
    "VERDICT_KIND",
    "NasalCleanError",
    "apply_nasal_decisions",
    "load_decisions",
    "undo_nasal_clean",
]
