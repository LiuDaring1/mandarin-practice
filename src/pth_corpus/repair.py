"""Selective, transactional application of reviewed boundary adjustments."""

from __future__ import annotations

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
from .detail_fetch import PILOT_SOURCE_KEYS, atomic_write_bytes
from .segmentation import _wav_bytes


MANUAL_ALGORITHM_VERSION = "constrained-dp-v1+manual-adjust-v1"
REPAIR_REPORT_PATH = Path("review/pilot_repair_report.json")
APPLICABLE_STATUSES = ("approved", "rejected", "needs_review")


class RepairError(RuntimeError):
    """Raised when reviewed adjustments cannot be applied safely."""


Decoder = Callable[[str | Path], np.ndarray]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, stored_path: str | Path | None) -> Path:
    if not stored_path:
        raise RepairError("database path is empty")
    root_resolved = root.expanduser().resolve()
    candidate = Path(str(stored_path))
    resolved = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve(
        strict=False
    )
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RepairError(f"path escapes data_root: {stored_path}") from exc
    return resolved


def _wav_frame_count(payload: bytes) -> int:
    try:
        with wave.open(io.BytesIO(payload), "rb") as handle:
            if (
                handle.getnchannels() != 1
                or handle.getsampwidth() != 2
                or handle.getframerate() != SAMPLE_RATE
                or handle.getnframes() <= 0
            ):
                raise RepairError("generated WAV has invalid PCM format")
            return handle.getnframes()
    except (OSError, wave.Error) as exc:
        raise RepairError(f"generated WAV is invalid: {exc}") from exc


def _temp_payload(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return temporary


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _latest_review_rows(
    connection: sqlite3.Connection,
    source_keys: tuple[str, ...] = PILOT_SOURCE_KEYS,
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in source_keys)
    return connection.execute(
        f"""
        SELECT e.item_id, e.table_kind, e.page_position, e.global_seq,
               sp.id AS source_page_id, sp.source_key, sp.audio_path, sp.audio_sha256,
               s.segment_id, s.clip_path, s.clip_sha256 AS current_clip_sha256,
               s.start_ms AS current_start_ms, s.end_ms AS current_end_ms,
               s.start_ms_raw, s.end_ms_raw,
               r.status, r.revision, r.clip_sha256 AS review_clip_sha256,
               r.adjusted_start_ms, r.adjusted_end_ms
        FROM entries AS e
        JOIN source_pages AS sp ON sp.id = e.source_page_id
        JOIN segments AS s ON s.item_id = e.item_id
        JOIN reviews AS r
          ON r.item_id = e.item_id
         AND r.revision = (
             SELECT MAX(r2.revision) FROM reviews AS r2 WHERE r2.item_id = e.item_id
         )
        WHERE sp.source_key IN ({placeholders})
        ORDER BY CASE e.table_kind WHEN 'table1' THEN 0 ELSE 1 END,
                 e.global_seq, e.item_id
        """,
        source_keys,
    ).fetchall()


def _candidate_rows(
    connection: sqlite3.Connection,
    source_keys: tuple[str, ...] = PILOT_SOURCE_KEYS,
) -> list[sqlite3.Row]:
    return [
        row
        for row in _latest_review_rows(connection, source_keys)
        if str(row["status"]) in APPLICABLE_STATUSES
        and row["review_clip_sha256"] is not None
        and row["review_clip_sha256"] == row["current_clip_sha256"]
        and row["adjusted_start_ms"] is not None
        and row["adjusted_end_ms"] is not None
        and (
            int(row["adjusted_start_ms"]) != int(row["current_start_ms"])
            or int(row["adjusted_end_ms"]) != int(row["current_end_ms"])
        )
    ]


def _validate_decoded(samples: np.ndarray, *, source_key: str) -> np.ndarray:
    array = np.asarray(samples)
    if array.ndim != 1:
        raise RepairError(f"{source_key}: decoded source is not mono 1-D")
    if array.size == 0:
        raise RepairError(f"{source_key}: decoded source is empty")
    if not np.isfinite(array).all():
        raise RepairError(f"{source_key}: decoded source contains non-finite samples")
    return array.astype(np.float32, copy=False)


def _event_key(event: dict[str, Any]) -> str:
    """Return a stable identity for one repair event."""

    identity = {
        key: event.get(key)
        for key in (
            "item_id",
            "revision",
            "old_start_ms",
            "old_end_ms",
            "new_start_ms",
            "new_end_ms",
            "old_clip_sha256",
            "new_clip_sha256",
            "algorithm_version",
        )
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_repair_events(path: Path) -> list[dict[str, Any]]:
    """Load prior cumulative events, accepting the pre-history report shape."""

    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict):
        return []
    raw_events = value.get("events")
    if not isinstance(raw_events, list):
        raw_events = value.get("history")
    if not isinstance(raw_events, list):
        raw_events = value.get("items")
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_events:
        if not isinstance(raw, dict) or not raw.get("item_id"):
            continue
        event = dict(raw)
        # Reports written before the cumulative event schema used start_ms /
        # end_ms and clip_sha256 for the new values.
        event.setdefault("new_start_ms", event.get("start_ms"))
        event.setdefault("new_end_ms", event.get("end_ms"))
        event.setdefault("new_clip_sha256", event.get("clip_sha256"))
        event.setdefault("algorithm_version", MANUAL_ALGORITHM_VERSION)
        key = _event_key(event)
        if key not in seen:
            seen.add(key)
            events.append(event)
    events.sort(key=lambda item: (_event_key(item), str(item.get("item_id", ""))))
    return events


def apply_adjustments(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    decoder: Decoder | None = None,
) -> dict[str, Any]:
    """Apply only current-hash reviewed adjustments as one atomic operation.

    All candidate bounds, source audio, current clip hashes and generated WAVs
    are validated before any destination file or SQLite row is changed.
    """

    root = Path(data_root).expanduser().resolve()
    decoder = decoder or decode_audio_ffmpeg
    if str(db_path) != ":memory:" and not Path(db_path).is_file():
        raise RepairError(f"repair database does not exist: {db_path}")
    staged_files: list[Path] = []
    plans: list[dict[str, Any]] = []
    source_cache: dict[int, np.ndarray] = {}
    report_original: bytes | None = None
    report_path = root / REPAIR_REPORT_PATH
    prior_events: list[dict[str, Any]] = []

    try:
        with connect_db(db_path) as connection:
            candidates = _candidate_rows(connection, PILOT_SOURCE_KEYS)
            if report_path.is_file():
                try:
                    report_original = report_path.read_bytes()
                except OSError as exc:
                    raise RepairError(f"cannot read existing repair report: {exc}") from exc
                prior_events = _load_repair_events(report_path)
            for row in candidates:
                item_id = str(row["item_id"])
                raw_start = (
                    int(row["start_ms_raw"])
                    if row["start_ms_raw"] is not None
                    else int(row["current_start_ms"])
                )
                raw_end = (
                    int(row["end_ms_raw"])
                    if row["end_ms_raw"] is not None
                    else int(row["current_end_ms"])
                )
                adjusted_start = int(row["adjusted_start_ms"])
                adjusted_end = int(row["adjusted_end_ms"])
                if raw_start < 0 or raw_end <= raw_start:
                    raise RepairError(f"{item_id}: invalid raw segment bounds")
                if adjusted_start < raw_start or adjusted_end > raw_end or adjusted_end <= adjusted_start:
                    raise RepairError(
                        f"{item_id}: adjusted bounds {adjusted_start}-{adjusted_end} ms "
                        f"are outside raw bounds {raw_start}-{raw_end} ms"
                    )

                clip_path = _safe_path(root, row["clip_path"])
                if not clip_path.is_file():
                    raise RepairError(f"{item_id}: clip does not exist: {clip_path}")
                try:
                    old_bytes = clip_path.read_bytes()
                    old_hash = _sha256_bytes(old_bytes)
                except OSError as exc:
                    raise RepairError(f"{item_id}: cannot read clip: {exc}") from exc
                if old_hash != str(row["current_clip_sha256"]):
                    raise RepairError(
                        f"{item_id}: current clip hash does not match database "
                        f"({old_hash} != {row['current_clip_sha256']})"
                    )

                source_page_id = int(row["source_page_id"])
                samples = source_cache.get(source_page_id)
                if samples is None:
                    source_path = _safe_path(root, row["audio_path"])
                    if not source_path.is_file():
                        raise RepairError(f"{row['source_key']}: source audio does not exist: {source_path}")
                    expected_source_hash = row["audio_sha256"]
                    if not expected_source_hash:
                        raise RepairError(
                            f"{row['source_key']}: source audio hash is missing"
                        )
                    try:
                        source_hash = _sha256_file(source_path)
                    except OSError as exc:
                        raise RepairError(f"{row['source_key']}: cannot read source audio: {exc}") from exc
                    if source_hash != str(expected_source_hash):
                        raise RepairError(
                            f"{row['source_key']}: source audio hash mismatch "
                            f"({source_hash} != {expected_source_hash})"
                        )
                    try:
                        samples = _validate_decoded(
                            decoder(source_path), source_key=str(row["source_key"])
                        )
                    except RepairError:
                        raise
                    except Exception as exc:
                        raise RepairError(
                            f"{row['source_key']}: source decode failed: {exc}"
                        ) from exc
                    source_cache[source_page_id] = samples

                start_sample = int(round(adjusted_start * SAMPLE_RATE / 1000))
                end_sample = int(round(adjusted_end * SAMPLE_RATE / 1000))
                if start_sample < 0 or end_sample <= start_sample or end_sample > samples.size:
                    raise RepairError(
                        f"{item_id}: adjusted sample bounds {start_sample}-{end_sample} "
                        f"outside source length {samples.size}"
                    )
                payload = _wav_bytes(samples[start_sample:end_sample])
                frames = _wav_frame_count(payload)
                expected_frames = end_sample - start_sample
                if frames != expected_frames:
                    raise RepairError(
                        f"{item_id}: generated frame count {frames} != {expected_frames}"
                    )
                new_hash = _sha256_bytes(payload)
                if new_hash == str(row["current_clip_sha256"]):
                    raise RepairError(
                        f"{item_id}: adjusted bounds produce the same clip SHA256; "
                        "refusing to leave the review current"
                    )
                plans.append(
                    {
                        "item_id": item_id,
                        "segment_id": int(row["segment_id"]),
                        "old_start_ms": int(row["current_start_ms"]),
                        "old_end_ms": int(row["current_end_ms"]),
                        "start_ms": adjusted_start,
                        "end_ms": adjusted_end,
                        "old_clip_sha256": str(row["current_clip_sha256"]),
                        "clip_sha256": new_hash,
                        "clip_path": _relative_path(clip_path, root),
                        "clip_path_abs": clip_path,
                        "status": str(row["status"]),
                        "revision": int(row["revision"]),
                        "boundary_adjustment_ms": max(
                            0, (adjusted_start - raw_start) + (raw_end - adjusted_end)
                        ),
                        "old_bytes": old_bytes,
                        "payload": payload,
                    }
                )

            plans.sort(key=lambda value: value["item_id"])
            # Materialize every replacement in a same-directory temporary file
            # before touching any destination.  This catches disk errors early.
            for plan in plans:
                staged_files.append(
                    _temp_payload(plan["clip_path_abs"], plan["payload"])
                )

            items_report = [
                {
                    "algorithm_version": MANUAL_ALGORITHM_VERSION,
                    "clip_path": update["clip_path"],
                    "item_id": update["item_id"],
                    "revision": update["revision"],
                    "status": update["status"],
                    "old_start_ms": update["old_start_ms"],
                    "old_end_ms": update["old_end_ms"],
                    "new_start_ms": update["start_ms"],
                    "new_end_ms": update["end_ms"],
                    "old_clip_sha256": update["old_clip_sha256"],
                    "new_clip_sha256": update["clip_sha256"],
                    "start_ms": update["start_ms"],
                    "end_ms": update["end_ms"],
                    "clip_sha256": update["clip_sha256"],
                }
                for update in plans
            ]
            cumulative_events: list[dict[str, Any]] = []
            seen_events: set[str] = set()
            for event in [*prior_events, *items_report]:
                key = _event_key(event)
                if key not in seen_events:
                    seen_events.add(key)
                    cumulative_events.append(event)
            cumulative_events.sort(
                key=lambda item: (_event_key(item), str(item.get("item_id", "")))
            )

            # A no-op rerun must not rewrite the report: retaining the exact
            # bytes preserves the cumulative audit trail and deterministic
            # history while still returning affected=0 to the caller.
            if not items_report and report_original is not None:
                return {
                    "command": "review",
                    "operation": "apply-adjustments",
                    "scope": "pilot",
                    "status": "succeeded",
                    "algorithm_version": MANUAL_ALGORITHM_VERSION,
                    "affected": 0,
                    "items": [],
                    "report": _relative_path(report_path, root),
                }
            report = {
                "command": "review",
                "operation": "apply-adjustments",
                "scope": "pilot",
                "status": "succeeded",
                "algorithm_version": MANUAL_ALGORITHM_VERSION,
                "affected": len(items_report),
                "items": items_report,
                "events": cumulative_events,
                "history": cumulative_events,
                "last_affected": len(items_report),
                "report": _relative_path(report_path, root),
            }
            report_payload = _json_bytes(report)

            # Publish the deterministic plan before touching clips/SQLite.  If
            # the later file or database transaction fails, the original
            # report is restored along with the data, so no partial repair is
            # observable.
            atomic_write_bytes(report_path, report_payload)

            # Replace all affected files, then update every row in one SQLite
            # transaction.  Any exception restores both sides from originals.
            replaced: list[tuple[Path, bytes]] = []
            try:
                for temporary, plan in zip(staged_files, plans, strict=True):
                    destination = plan["clip_path_abs"]
                    old_bytes = plan["old_bytes"]
                    os.replace(temporary, destination)
                    replaced.append((destination, old_bytes))
                connection.execute("BEGIN")
                for update in plans:
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
                            update["start_ms"],
                            update["end_ms"],
                            update["start_ms"],
                            update["end_ms"],
                            update["boundary_adjustment_ms"],
                            update["clip_sha256"],
                            MANUAL_ALGORITHM_VERSION,
                            update["segment_id"],
                            update["item_id"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RepairError(f"{update['item_id']}: segment disappeared during update")
                connection.commit()
            except Exception:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                for destination, old_bytes in reversed(replaced):
                    try:
                        atomic_write_bytes(destination, old_bytes)
                    except OSError:
                        pass
                if report_original is None:
                    try:
                        report_path.unlink()
                    except OSError:
                        pass
                else:
                    try:
                        atomic_write_bytes(report_path, report_original)
                    except OSError:
                        pass
                raise
    except (sqlite3.Error, OSError) as exc:
        if isinstance(exc, RepairError):
            raise
        raise RepairError(f"repair failed: {exc}") from exc
    finally:
        for temporary in staged_files:
            try:
                temporary.unlink()
            except OSError:
                pass

    return {
        "command": "review",
        "operation": "apply-adjustments",
        "scope": "pilot",
        "status": "succeeded",
        "algorithm_version": MANUAL_ALGORITHM_VERSION,
        "affected": len(plans),
        "items": [
            {
                "algorithm_version": MANUAL_ALGORITHM_VERSION,
                "item_id": value["item_id"],
                "revision": value["revision"],
                "old_start_ms": value["old_start_ms"],
                "old_end_ms": value["old_end_ms"],
                "new_start_ms": value["start_ms"],
                "new_end_ms": value["end_ms"],
                "old_clip_sha256": value["old_clip_sha256"],
                "new_clip_sha256": value["clip_sha256"],
                "start_ms": value["start_ms"],
                "end_ms": value["end_ms"],
                "clip_sha256": value["clip_sha256"],
            }
            for value in plans
        ],
        "report": _relative_path(report_path, root),
    }


__all__ = [
    "APPLICABLE_STATUSES",
    "MANUAL_ALGORITHM_VERSION",
    "REPAIR_REPORT_PATH",
    "RepairError",
    "apply_adjustments",
]
