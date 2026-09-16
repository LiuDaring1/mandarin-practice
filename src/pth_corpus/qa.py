"""Read-only machine QA for the pilot corpus.

The QA gate deliberately does not infer human decisions.  It validates the
database/file invariants that can be checked mechanically, then reports the
latest review state by comparing review and current clip hashes.  The report
is deterministic so it can be diffed in CI and is written atomically.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import wave
from collections import defaultdict
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH, connect_db
from .detail_fetch import atomic_write_bytes
from .detail_fetch import PILOT_SOURCE_KEYS
from .nasal_clean import NASAL_RECUT_ALGORITHM_VERSION
from .segmentation import (
    ALGORITHM_VERSION,
    FULL_ALGORITHM_VERSION,
    LEADING_ANNOUNCEMENT_ALGORITHM_VERSION,
    LOW_CONFIDENCE_THRESHOLD,
    SAMPLE_RATE,
)


PILOT_EXPECTED_COUNT = 200
QA_REPORT_PATH = Path("derived/pilot_qa_report.json")
FULL_QA_REPORT_PATH = Path("derived/full_qa_report.json")
FULL_ANALYSIS_REPORT_PATH = Path("derived/analysis/full_analysis.json")
FULL_SEGMENTATION_REPORT_PATH = Path("derived/full_segmentation_report.json")
REVIEW_STATUSES = ("approved", "pending", "rejected", "needs_review")


class QAGateError(RuntimeError):
    """Raised for an unrecoverable QA input/database error."""


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, stored_path: str | Path | None) -> Path | None:
    """Resolve a DB path and reject traversal/symlink escapes."""

    if not stored_path:
        return None
    root_resolved = root.expanduser().resolve()
    candidate = Path(str(stored_path))
    resolved = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve(
        strict=False
    )
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise QAGateError(f"path escapes data_root: {stored_path}") from exc
    return resolved


def _load_template_starts(root: Path) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Load the analysis report's page advert boundaries.

    Missing/malformed report data is represented as a machine anomaly rather
    than an exception so the gate can emit one complete deterministic report.
    """

    report_path = root / "derived/analysis/pilot_analysis.json"
    if not report_path.is_file():
        return {}, [
            {
                "code": "missing_analysis_report",
                "path": "derived/analysis/pilot_analysis.json",
            }
        ]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [
            {
                "code": "invalid_analysis_report",
                "path": "derived/analysis/pilot_analysis.json",
                "detail": str(exc),
            }
        ]
    pages = report.get("pages") if isinstance(report, dict) else None
    if not isinstance(pages, list):
        return {}, [
            {
                "code": "invalid_analysis_pages",
                "path": "derived/analysis/pilot_analysis.json",
            }
        ]
    starts: dict[str, float] = {}
    anomalies: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict) or not page.get("source_key"):
            anomalies.append({"code": "invalid_analysis_page"})
            continue
        source_key = str(page["source_key"])
        value = page.get("template_start_s")
        try:
            value_float = float(value)
        except (TypeError, ValueError):
            anomalies.append(
                {"code": "invalid_template_start", "source_key": source_key}
            )
            continue
        if not math.isfinite(value_float) or value_float <= 0:
            anomalies.append(
                {"code": "invalid_template_start", "source_key": source_key}
            )
            continue
        starts[source_key] = value_float
    return starts, anomalies


def _load_leading_announcement_reports(
    root: Path,
    *,
    required_algorithm_version: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load v2 segmentation/analysis metadata for structural boundary QA."""

    segmentation_path = root / "derived/pilot_segmentation_report.json"
    if not segmentation_path.is_file():
        if required_algorithm_version == LEADING_ANNOUNCEMENT_ALGORITHM_VERSION:
            return None, {}, [
                {
                    "code": "missing_segmentation_report",
                    "path": "derived/pilot_segmentation_report.json",
                }
            ]
        return None, {}, []
    try:
        segmentation = json.loads(segmentation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, {}, [
            {
                "code": "invalid_segmentation_report",
                "path": "derived/pilot_segmentation_report.json",
                "detail": str(exc),
            }
        ]
    if not isinstance(segmentation, dict):
        return None, {}, [
            {
                "code": "invalid_segmentation_report",
                "path": "derived/pilot_segmentation_report.json",
            }
        ]
    report_algorithm = segmentation.get("algorithm_version")
    if required_algorithm_version == LEADING_ANNOUNCEMENT_ALGORITHM_VERSION:
        if report_algorithm != LEADING_ANNOUNCEMENT_ALGORITHM_VERSION:
            return segmentation, {}, [
                {
                    "code": "segmentation_report_algorithm_mismatch",
                    "path": "derived/pilot_segmentation_report.json",
                    "expected": LEADING_ANNOUNCEMENT_ALGORITHM_VERSION,
                    "actual": report_algorithm,
                }
            ]
    elif report_algorithm != LEADING_ANNOUNCEMENT_ALGORITHM_VERSION:
        # Legacy v1 fixtures intentionally exercise only the ordinary DP
        # invariants; the heading-specific checks are v2-only.
        return None, {}, []
    else:
        # A v2 report alongside a v1 database is stale/mismatched metadata.
        if required_algorithm_version is not None:
            return segmentation, {}, [
                {
                    "code": "segmentation_report_database_algorithm_mismatch",
                    "path": "derived/pilot_segmentation_report.json",
                    "expected": required_algorithm_version,
                    "actual": report_algorithm,
                }
            ]
    analysis_path = root / "derived/analysis/pilot_analysis.json"
    if not analysis_path.is_file():
        return segmentation, {}, [
            {
                "code": "missing_analysis_report",
                "path": "derived/analysis/pilot_analysis.json",
            }
        ]
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return segmentation, {}, [
            {
                "code": "invalid_analysis_report",
                "path": "derived/analysis/pilot_analysis.json",
                "detail": str(exc),
            }
        ]
    analysis_pages = analysis.get("pages") if isinstance(analysis, dict) else None
    if not isinstance(analysis_pages, list):
        return segmentation, {}, [
            {
                "code": "invalid_analysis_pages",
                "path": "derived/analysis/pilot_analysis.json",
            }
        ]
    by_key = {
        str(page.get("source_key")): page
        for page in analysis_pages
        if isinstance(page, dict) and page.get("source_key")
    }
    return segmentation, by_key, []


def _leading_announcement_checks(
    rows: list[sqlite3.Row],
    *,
    segmentation: dict[str, Any] | None,
    analysis_pages: dict[str, dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> None:
    """Verify v2 excludes only the leading interval and retains all others."""

    if segmentation is None:
        return
    pages = segmentation.get("pages")
    if not isinstance(pages, list):
        _append_anomaly(anomalies, "invalid_segmentation_pages")
        return
    segment_rows_by_page: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if row["segment_id"] is not None and row["source_key"]:
            segment_rows_by_page[str(row["source_key"])].append(row)
    for page in pages:
        if not isinstance(page, dict) or not page.get("source_key"):
            _append_anomaly(anomalies, "invalid_segmentation_page")
            continue
        source_key = str(page["source_key"])
        expected_items = int(page.get("expected_items") or 0)
        expected_positions = list(range(2, expected_items + 3))
        selected = page.get("selected_candidate_positions")
        discarded = page.get("discarded_candidate_positions")
        if page.get("algorithm_version") != LEADING_ANNOUNCEMENT_ALGORITHM_VERSION:
            _append_anomaly(
                anomalies,
                "leading_announcement_algorithm_mismatch",
                source_key=source_key,
                algorithm_version=page.get("algorithm_version"),
            )
        if int(page.get("candidate_count") or 0) != expected_items + 2:
            _append_anomaly(
                anomalies,
                "leading_announcement_candidate_count",
                source_key=source_key,
                expected=expected_items + 2,
                actual=page.get("candidate_count"),
            )
        if selected != expected_positions:
            _append_anomaly(
                anomalies,
                "leading_announcement_not_excluded",
                source_key=source_key,
                expected_positions=expected_positions,
                actual_positions=selected,
            )
        if discarded != []:
            _append_anomaly(
                anomalies,
                "internal_candidate_discarded",
                source_key=source_key,
                discarded_positions=discarded,
            )
        excluded = page.get("excluded_candidate_positions")
        if excluded != [1]:
            _append_anomaly(
                anomalies,
                "leading_announcement_exclusion_metadata",
                source_key=source_key,
                expected=[1],
                actual=excluded,
            )
        candidates = analysis_pages.get(source_key, {}).get("candidates")
        if not isinstance(candidates, list) or len(candidates) != expected_items + 2:
            _append_anomaly(
                anomalies,
                "leading_announcement_analysis_candidates",
                source_key=source_key,
            )
            continue
        try:
            boundaries_ms = [int(round(float(item["boundary_s"]) * 1000)) for item in candidates]
        except (KeyError, TypeError, ValueError):
            _append_anomaly(
                anomalies,
                "leading_announcement_invalid_candidate_boundary",
                source_key=source_key,
            )
            continue
        page_rows = sorted(
            segment_rows_by_page.get(source_key, []),
            key=lambda row: (int(row["page_position"]), str(row["item_id"])),
        )
        if len(page_rows) != expected_items:
            continue
        for position, row in enumerate(page_rows):
            start = row["start_ms_raw"]
            end = row["end_ms_raw"]
            start_expected = boundaries_ms[position + 1]
            end_expected = boundaries_ms[position + 2]
            if start is None or end is None or abs(int(start) - start_expected) > 1 or abs(int(end) - end_expected) > 1:
                _append_anomaly(
                    anomalies,
                    "candidate_boundary_mismatch",
                    item_id=str(row["item_id"]),
                    source_key=source_key,
                    expected_start_ms=start_expected,
                    expected_end_ms=end_expected,
                    actual_start_ms=start,
                    actual_end_ms=end,
                )

    report_keys = {
        str(page.get("source_key"))
        for page in pages
        if isinstance(page, dict) and page.get("source_key")
    }
    for source_key in PILOT_SOURCE_KEYS:
        if source_key not in report_keys:
            _append_anomaly(
                anomalies,
                "segmentation_page_missing",
                source_key=source_key,
            )


def _latest_reviews(
    connection: sqlite3.Connection,
    source_keys: tuple[str, ...] = PILOT_SOURCE_KEYS,
) -> dict[str, sqlite3.Row]:
    placeholders = ",".join("?" for _ in source_keys)
    rows = connection.execute(
        f"""
        SELECT r.*
        FROM reviews AS r
        JOIN entries AS e ON e.item_id = r.item_id
        JOIN source_pages AS sp ON sp.id = e.source_page_id
        JOIN (
            SELECT item_id, MAX(revision) AS revision
            FROM reviews
            GROUP BY item_id
        ) AS latest
          ON latest.item_id = r.item_id AND latest.revision = r.revision
        WHERE sp.source_key IN ({placeholders})
        """,
        source_keys,
    ).fetchall()
    return {str(row["item_id"]): row for row in rows}


def _row_order(row: sqlite3.Row) -> tuple[int, int, str]:
    return (
        0 if str(row["table_kind"]) == "table1" else 1,
        int(row["global_seq"] or 0),
        str(row["item_id"]),
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open an existing SQLite file in read-only mode for the QA gate."""

    if str(path) == ":memory:":
        # Useful for callers that intentionally construct an in-memory fixture;
        # ordinary filesystem QA always takes the URI read-only branch.
        return connect_db(path)
    database = Path(path)
    if not database.is_file():
        raise QAGateError(f"QA database does not exist: {database}")
    connection = sqlite3.connect(
        f"file:{database.expanduser().resolve()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _append_anomaly(
    anomalies: list[dict[str, Any]],
    code: str,
    *,
    item_id: str | None = None,
    **details: Any,
) -> None:
    value: dict[str, Any] = {"code": code}
    if item_id is not None:
        value["item_id"] = item_id
    value.update(details)
    anomalies.append(value)


def _pilot_source_page_checks(
    connection: sqlite3.Connection,
    *,
    root: Path,
    anomalies: list[dict[str, Any]],
) -> dict[str, int]:
    """Validate and return the two pilot source-page IDs.

    All counts in the gate are scoped through these source keys.  Additional
    pages in a larger corpus are intentionally outside the pilot gate.
    """

    placeholders = ",".join("?" for _ in PILOT_SOURCE_KEYS)
    rows = connection.execute(
        f"""
        SELECT id, source_key, expected_items, audio_path, audio_sha256
        FROM source_pages
        WHERE source_key IN ({placeholders})
        ORDER BY source_key, id
        """,
        PILOT_SOURCE_KEYS,
    ).fetchall()
    by_key: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_key[str(row["source_key"])].append(row)
    page_ids: dict[str, int] = {}
    for source_key in PILOT_SOURCE_KEYS:
        matches = by_key.get(source_key, [])
        if not matches:
            _append_anomaly(
                anomalies,
                "missing_pilot_source_page",
                source_key=source_key,
            )
            continue
        if len(matches) != 1:
            _append_anomaly(
                anomalies,
                "duplicate_pilot_source_page",
                source_key=source_key,
                actual=len(matches),
            )
        row = matches[0]
        page_id = int(row["id"])
        page_ids[source_key] = page_id
        expected_items = row["expected_items"]
        if expected_items is None or int(expected_items) != 100:
            _append_anomaly(
                anomalies,
                "pilot_page_expected_items",
                source_key=source_key,
                expected=100,
                actual=expected_items,
            )
        entry_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM entries WHERE source_page_id = ?", (page_id,)
            ).fetchone()[0]
        )
        segment_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM segments AS s
                JOIN entries AS e ON e.item_id = s.item_id
                WHERE e.source_page_id = ?
                """,
                (page_id,),
            ).fetchone()[0]
        )
        if entry_count != 100:
            _append_anomaly(
                anomalies,
                "pilot_page_entry_count",
                source_key=source_key,
                expected=100,
                actual=entry_count,
            )
        if segment_count != 100:
            _append_anomaly(
                anomalies,
                "pilot_page_segment_count",
                source_key=source_key,
                expected=100,
                actual=segment_count,
            )

        audio_path_value = row["audio_path"]
        audio_hash = row["audio_sha256"]
        if not audio_path_value:
            _append_anomaly(anomalies, "missing_source_audio_path", source_key=source_key)
        if not audio_hash:
            _append_anomaly(anomalies, "missing_source_audio_hash", source_key=source_key)
        if not audio_path_value:
            continue
        try:
            audio_path = _safe_path(root, audio_path_value)
        except QAGateError as exc:
            _append_anomaly(
                anomalies,
                "source_audio_path_escape",
                source_key=source_key,
                detail=str(exc),
            )
            continue
        if not audio_path.is_file():
            _append_anomaly(
                anomalies,
                "missing_source_audio",
                source_key=source_key,
                path=_relative_path(audio_path, root),
            )
            continue
        if audio_hash:
            try:
                actual_hash = _sha256_file(audio_path)
            except OSError as exc:
                _append_anomaly(
                    anomalies,
                    "unreadable_source_audio",
                    source_key=source_key,
                    path=_relative_path(audio_path, root),
                    detail=str(exc),
                )
            else:
                if actual_hash != str(audio_hash):
                    _append_anomaly(
                        anomalies,
                        "source_audio_sha256_mismatch",
                        source_key=source_key,
                        path=_relative_path(audio_path, root),
                        expected=str(audio_hash),
                        actual=actual_hash,
                    )
    return page_ids


def _validate_clip(
    row: sqlite3.Row,
    *,
    root: Path,
    anomalies: list[dict[str, Any]],
) -> None:
    item_id = str(row["item_id"])
    try:
        clip_path = _safe_path(root, row["clip_path"])
    except QAGateError as exc:
        _append_anomaly(anomalies, "clip_path_escape", item_id=item_id, detail=str(exc))
        return
    if clip_path is None:
        _append_anomaly(anomalies, "missing_clip_path", item_id=item_id)
        return
    if not clip_path.is_file():
        _append_anomaly(
            anomalies,
            "missing_clip",
            item_id=item_id,
            path=_relative_path(clip_path, root),
        )
        return
    try:
        actual_hash = _sha256_file(clip_path)
    except OSError as exc:
        _append_anomaly(
            anomalies,
            "unreadable_clip",
            item_id=item_id,
            path=_relative_path(clip_path, root),
            detail=str(exc),
        )
        return
    expected_hash = row["clip_sha256"]
    if not expected_hash or actual_hash != str(expected_hash):
        _append_anomaly(
            anomalies,
            "clip_sha256_mismatch",
            item_id=item_id,
            path=_relative_path(clip_path, root),
            expected=str(expected_hash) if expected_hash else None,
            actual=actual_hash,
        )
    try:
        with wave.open(str(clip_path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            duration_ms = frames * 1000.0 / SAMPLE_RATE if rate else 0.0
            expected_frames = int(
                round((int(row["end_ms"]) - int(row["start_ms"])) * SAMPLE_RATE / 1000)
            )
            if channels != 1 or width != 2 or rate != SAMPLE_RATE:
                _append_anomaly(
                    anomalies,
                    "clip_format",
                    item_id=item_id,
                    channels=channels,
                    sample_width=width,
                    sample_rate=rate,
                )
            if frames <= 0:
                _append_anomaly(anomalies, "empty_clip", item_id=item_id)
            if frames != expected_frames:
                _append_anomaly(
                    anomalies,
                    "clip_frame_count",
                    item_id=item_id,
                    expected_frames=expected_frames,
                    actual_frames=frames,
                    expected_duration_ms=int(row["end_ms"]) - int(row["start_ms"]),
                    actual_duration_ms=round(duration_ms, 6),
                )
    except (OSError, EOFError, wave.Error) as exc:
        _append_anomaly(
            anomalies,
            "invalid_wav",
            item_id=item_id,
            path=_relative_path(clip_path, root),
            detail=str(exc),
        )


def _page_boundary_checks(
    rows: list[sqlite3.Row],
    *,
    anomalies: list[dict[str, Any]],
) -> None:
    grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[int(row["source_page_id"])].append(row)
    for page_id, page_rows in sorted(grouped.items()):
        page_rows.sort(key=lambda value: (int(value["page_position"]), str(value["item_id"])))
        previous_end: int | None = None
        previous_raw_end: int | None = None
        previous_item: str | None = None
        for row in page_rows:
            item_id = str(row["item_id"])
            try:
                start = int(row["start_ms"])
                end = int(row["end_ms"])
            except (TypeError, ValueError):
                _append_anomaly(anomalies, "invalid_segment_bounds", item_id=item_id)
                continue
            if start < 0 or end <= start:
                _append_anomaly(
                    anomalies,
                    "invalid_segment_bounds",
                    item_id=item_id,
                    start_ms=start,
                    end_ms=end,
                )
            if previous_end is not None and start < previous_end:
                _append_anomaly(
                    anomalies,
                    "segment_overlap",
                    item_id=item_id,
                    previous_item_id=previous_item,
                    previous_end_ms=previous_end,
                    start_ms=start,
                    source_page_id=page_id,
                )
            raw_start_value = row["start_ms_raw"]
            raw_end_value = row["end_ms_raw"]
            if raw_start_value is not None and raw_end_value is not None:
                raw_start = int(raw_start_value)
                raw_end = int(raw_end_value)
                if raw_end <= raw_start or raw_start < 0:
                    _append_anomaly(
                        anomalies,
                        "invalid_raw_segment_bounds",
                        item_id=item_id,
                        start_ms_raw=raw_start,
                        end_ms_raw=raw_end,
                    )
                if previous_raw_end is not None and raw_start < previous_raw_end:
                    _append_anomaly(
                        anomalies,
                        "raw_segment_overlap",
                        item_id=item_id,
                        previous_item_id=previous_item,
                        previous_end_ms_raw=previous_raw_end,
                        start_ms_raw=raw_start,
                        source_page_id=page_id,
                    )
                previous_raw_end = raw_end
            previous_end = end
            previous_item = item_id


def qa_pilot(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
) -> dict[str, Any]:
    """Run the pilot machine gate and atomically publish its report.

    The SQLite connection is strictly read-only from this function: no table
    writes, review rows, or segment updates are performed.
    """

    root = Path(data_root).expanduser().resolve()
    anomalies: list[dict[str, Any]] = []
    low_confidence_ids: list[str] = []
    review_counts = {status: 0 for status in REVIEW_STATUSES}
    stale_count = 0
    unapplied_adjustments: list[dict[str, Any]] = []
    template_starts, report_anomalies = _load_template_starts(root)
    anomalies.extend(report_anomalies)
    segmentation_report: dict[str, Any] | None = None
    analysis_pages: dict[str, dict[str, Any]] = {}

    try:
        with _connect_readonly(db_path) as connection:
            _pilot_source_page_checks(connection, root=root, anomalies=anomalies)
            source_placeholders = ",".join("?" for _ in PILOT_SOURCE_KEYS)
            entries_count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM entries AS e
                    JOIN source_pages AS sp ON sp.id = e.source_page_id
                    WHERE sp.source_key IN ({source_placeholders})
                    """,
                    PILOT_SOURCE_KEYS,
                ).fetchone()[0]
            )
            segments_count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM segments AS s
                    JOIN entries AS e ON e.item_id = s.item_id
                    JOIN source_pages AS sp ON sp.id = e.source_page_id
                    WHERE sp.source_key IN ({source_placeholders})
                    """,
                    PILOT_SOURCE_KEYS,
                ).fetchone()[0]
            )
            unique_segments = int(
                connection.execute(
                    f"""
                    SELECT COUNT(DISTINCT s.item_id)
                    FROM segments AS s
                    JOIN entries AS e ON e.item_id = s.item_id
                    JOIN source_pages AS sp ON sp.id = e.source_page_id
                    WHERE sp.source_key IN ({source_placeholders})
                    """,
                    PILOT_SOURCE_KEYS,
                ).fetchone()[0]
            )
            if entries_count != PILOT_EXPECTED_COUNT:
                _append_anomaly(
                    anomalies,
                    "entry_count",
                    expected=PILOT_EXPECTED_COUNT,
                    actual=entries_count,
                )
            if segments_count != PILOT_EXPECTED_COUNT:
                _append_anomaly(
                    anomalies,
                    "segment_count",
                    expected=PILOT_EXPECTED_COUNT,
                    actual=segments_count,
                )
            if unique_segments != segments_count:
                _append_anomaly(
                    anomalies,
                    "duplicate_segment_item_id",
                    expected=segments_count,
                    actual=unique_segments,
                )

            algorithm_rows = connection.execute(
                f"""
                SELECT DISTINCT s.algorithm_version
                FROM segments AS s
                JOIN entries AS e ON e.item_id = s.item_id
                JOIN source_pages AS sp ON sp.id = e.source_page_id
                WHERE sp.source_key IN ({source_placeholders})
                """,
                PILOT_SOURCE_KEYS,
            ).fetchall()
            algorithm_versions = {
                str(row["algorithm_version"])
                for row in algorithm_rows
                if row["algorithm_version"] is not None
            }
            required_algorithm_version: str | None = None
            if algorithm_versions == {LEADING_ANNOUNCEMENT_ALGORITHM_VERSION}:
                required_algorithm_version = LEADING_ANNOUNCEMENT_ALGORITHM_VERSION
            elif algorithm_versions == {ALGORITHM_VERSION}:
                # Existing v1 fixtures remain supported; v2 structural report
                # requirements apply only when the pilot DB is actually v2.
                required_algorithm_version = ALGORITHM_VERSION
            elif algorithm_versions:
                _append_anomaly(
                    anomalies,
                    "segment_algorithm_version",
                    expected=[ALGORITHM_VERSION, LEADING_ANNOUNCEMENT_ALGORITHM_VERSION],
                    actual=sorted(algorithm_versions),
                )
            if required_algorithm_version is not None:
                segmentation_report, analysis_pages, segmentation_anomalies = (
                    _load_leading_announcement_reports(
                        root,
                        required_algorithm_version=required_algorithm_version,
                    )
                )
                anomalies.extend(segmentation_anomalies)

            rows = connection.execute(
                f"""
                SELECT e.item_id, e.source_page_id, e.table_kind, e.page_position,
                       e.global_seq, sp.source_key, sp.page_no,
                       s.segment_id, s.clip_path, s.clip_sha256,
                       s.confidence, s.start_ms, s.end_ms,
                       s.start_ms_raw, s.end_ms_raw,
                       s.start_ms_adjusted, s.end_ms_adjusted
                FROM entries AS e
                JOIN source_pages AS sp ON sp.id = e.source_page_id
                LEFT JOIN segments AS s ON s.item_id = e.item_id
                WHERE sp.source_key IN ({source_placeholders})
                ORDER BY CASE e.table_kind WHEN 'table1' THEN 0 ELSE 1 END,
                         e.global_seq, e.item_id
                """,
                PILOT_SOURCE_KEYS,
            ).fetchall()
            segment_rows = [row for row in rows if row["segment_id"] is not None]
            if len(segment_rows) != segments_count:
                _append_anomaly(
                    anomalies,
                    "orphan_segment",
                    entry_joined_segments=len(segment_rows),
                    segment_count=segments_count,
                )
            for row in rows:
                item_id = str(row["item_id"])
                if row["segment_id"] is None:
                    _append_anomaly(anomalies, "missing_segment", item_id=item_id)
                    continue
                _validate_clip(row, root=root, anomalies=anomalies)
                confidence = row["confidence"]
                if confidence is not None:
                    try:
                        if float(confidence) < LOW_CONFIDENCE_THRESHOLD:
                            low_confidence_ids.append(item_id)
                    except (TypeError, ValueError):
                        _append_anomaly(
                            anomalies,
                            "invalid_confidence",
                            item_id=item_id,
                            confidence=confidence,
                        )

                source_key = row["source_key"]
                template_start_s = template_starts.get(str(source_key)) if source_key else None
                if template_start_s is None:
                    _append_anomaly(
                        anomalies,
                        "missing_template_start",
                        item_id=item_id,
                        source_key=str(source_key) if source_key else None,
                    )
                else:
                    template_start_ms = int(round(template_start_s * 1000))
                    if int(row["end_ms"]) > template_start_ms:
                        _append_anomaly(
                            anomalies,
                            "segment_overlaps_advert",
                            item_id=item_id,
                            end_ms=int(row["end_ms"]),
                            template_start_ms=template_start_ms,
                        )
                    if (
                        row["end_ms_raw"] is not None
                        and int(row["end_ms_raw"]) > template_start_ms
                    ):
                        _append_anomaly(
                            anomalies,
                            "raw_segment_overlaps_advert",
                            item_id=item_id,
                            end_ms_raw=int(row["end_ms_raw"]),
                            template_start_ms=template_start_ms,
                        )
                raw_start = row["start_ms_raw"]
                raw_end = row["end_ms_raw"]
                if raw_start is None or raw_end is None:
                    _append_anomaly(
                        anomalies,
                        "missing_raw_segment_bounds",
                        item_id=item_id,
                    )
                elif (
                    int(row["start_ms"]) < int(raw_start)
                    or int(row["end_ms"]) > int(raw_end)
                    or int(row["end_ms"]) <= int(row["start_ms"])
                ):
                    _append_anomaly(
                        anomalies,
                        "final_outside_raw",
                        item_id=item_id,
                        start_ms=int(row["start_ms"]),
                        end_ms=int(row["end_ms"]),
                        start_ms_raw=int(raw_start),
                        end_ms_raw=int(raw_end),
                    )

            _page_boundary_checks(segment_rows, anomalies=anomalies)
            _leading_announcement_checks(
                rows,
                segmentation=segmentation_report,
                analysis_pages=analysis_pages,
                anomalies=anomalies,
            )

            latest_reviews = _latest_reviews(connection, PILOT_SOURCE_KEYS)
            segment_by_item = {str(row["item_id"]): row for row in segment_rows}
            for item_id in sorted(segment_by_item, key=lambda value: _row_order(segment_by_item[value])):
                segment = segment_by_item[item_id]
                latest = latest_reviews.get(item_id)
                stale = False
                if latest is None:
                    effective_status = "pending"
                else:
                    stale = latest["clip_sha256"] != segment["clip_sha256"]
                    if stale:
                        stale_count += 1
                        effective_status = "pending"
                    else:
                        effective_status = str(latest["status"])
                        if effective_status not in review_counts:
                            _append_anomaly(
                                anomalies,
                                "invalid_review_status",
                                item_id=item_id,
                                status=effective_status,
                            )
                            effective_status = "pending"
                review_counts[effective_status] += 1
                if latest is not None:
                    adjusted_start = latest["adjusted_start_ms"]
                    adjusted_end = latest["adjusted_end_ms"]
                    if (
                        not stale
                        and adjusted_start is not None
                        and adjusted_end is not None
                        and (
                            int(adjusted_start) != int(segment["start_ms"])
                            or int(adjusted_end) != int(segment["end_ms"])
                        )
                    ):
                        unapplied_adjustments.append(
                            {
                                "item_id": item_id,
                                "status": str(latest["status"]),
                                "current_start_ms": int(segment["start_ms"]),
                                "current_end_ms": int(segment["end_ms"]),
                                "adjusted_start_ms": int(adjusted_start),
                                "adjusted_end_ms": int(adjusted_end),
                            }
                        )
                        _append_anomaly(
                            anomalies,
                            "unapplied_adjustment",
                            item_id=item_id,
                            adjusted_start_ms=int(adjusted_start),
                            adjusted_end_ms=int(adjusted_end),
                            current_start_ms=int(segment["start_ms"]),
                            current_end_ms=int(segment["end_ms"]),
                        )
    except sqlite3.Error as exc:
        raise QAGateError(f"QA database failure: {exc}") from exc
    except OSError as exc:
        raise QAGateError(f"QA filesystem failure: {exc}") from exc

    low_confidence_ids.sort()
    anomalies.sort(
        key=lambda value: (
            str(value.get("item_id", "")),
            str(value.get("code", "")),
            json.dumps(value, ensure_ascii=False, sort_keys=True),
        )
    )
    unapplied_adjustments.sort(key=lambda value: value["item_id"])
    machine_anomalies = len(anomalies)
    if machine_anomalies:
        gate = "blocked_on_machine_qa"
    elif (
        review_counts["approved"] != PILOT_EXPECTED_COUNT
        or review_counts["pending"]
        or review_counts["rejected"]
        or review_counts["needs_review"]
        or stale_count
    ):
        gate = "blocked_on_human_review"
    else:
        gate = "passed"
    report = {
        "command": "qa",
        "scope": "pilot",
        "status": gate,
        "gate": gate,
        "entries": entries_count,
        "segments": segments_count,
        "unique_segment_items": unique_segments,
        "expected_count": PILOT_EXPECTED_COUNT,
        "machine_anomalies": machine_anomalies,
        "anomalies": anomalies,
        "low_confidence_ids": low_confidence_ids,
        "review_counts": {
            **review_counts,
            "stale": stale_count,
        },
        "unapplied_adjustments": unapplied_adjustments,
        "report": _relative_path(root / QA_REPORT_PATH, root),
    }
    atomic_write_bytes(root / QA_REPORT_PATH, _json_bytes(report))
    return report


def _full_source_page_checks(
    connection: sqlite3.Connection,
    *,
    root: Path,
    anomalies: list[dict[str, Any]],
) -> int:
    """Validate every registered source page and return expected item total."""

    rows = connection.execute(
        """
        SELECT id, source_key, table_kind, page_no, expected_items,
               audio_path, audio_sha256, fetch_status
        FROM source_pages
        ORDER BY table_kind, page_no
        """
    ).fetchall()
    expected_total = 0
    for row in rows:
        source_key = str(row["source_key"])
        if str(row["fetch_status"]) != "fetched":
            _append_anomaly(
                anomalies,
                "source_page_not_fetched",
                source_key=source_key,
                fetch_status=row["fetch_status"],
            )
        expected_items = row["expected_items"]
        if expected_items is None or int(expected_items) <= 0:
            _append_anomaly(
                anomalies,
                "full_page_expected_items",
                source_key=source_key,
                actual=expected_items,
            )
            continue
        expected_items = int(expected_items)
        expected_total += expected_items
        page_id = int(row["id"])
        entry_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM entries WHERE source_page_id = ?",
                (page_id,),
            ).fetchone()[0]
        )
        segment_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM segments AS s
                JOIN entries AS e ON e.item_id = s.item_id
                WHERE e.source_page_id = ?
                """,
                (page_id,),
            ).fetchone()[0]
        )
        if entry_count != expected_items:
            _append_anomaly(
                anomalies,
                "full_page_entry_count",
                source_key=source_key,
                expected=expected_items,
                actual=entry_count,
            )
        if segment_count != expected_items:
            _append_anomaly(
                anomalies,
                "full_page_segment_count",
                source_key=source_key,
                expected=expected_items,
                actual=segment_count,
            )
        audio_path_value = row["audio_path"]
        audio_hash = row["audio_sha256"]
        if not audio_path_value:
            _append_anomaly(anomalies, "missing_source_audio_path", source_key=source_key)
        if not audio_hash:
            _append_anomaly(anomalies, "missing_source_audio_hash", source_key=source_key)
        if not audio_path_value:
            continue
        try:
            audio_path = _safe_path(root, audio_path_value)
        except QAGateError as exc:
            _append_anomaly(
                anomalies,
                "source_audio_path_escape",
                source_key=source_key,
                detail=str(exc),
            )
            continue
        if not audio_path.is_file():
            _append_anomaly(
                anomalies,
                "missing_source_audio",
                source_key=source_key,
                path=_relative_path(audio_path, root),
            )
            continue
        if audio_hash:
            try:
                actual_hash = _sha256_file(audio_path)
            except OSError as exc:
                _append_anomaly(
                    anomalies,
                    "unreadable_source_audio",
                    source_key=source_key,
                    path=_relative_path(audio_path, root),
                    detail=str(exc),
                )
            else:
                if actual_hash != str(audio_hash):
                    _append_anomaly(
                        anomalies,
                        "source_audio_sha256_mismatch",
                        source_key=source_key,
                        path=_relative_path(audio_path, root),
                        expected=str(audio_hash),
                        actual=actual_hash,
                    )
    return expected_total


def _full_segmentation_checks(
    connection: sqlite3.Connection,
    *,
    root: Path,
    anomalies: list[dict[str, Any]],
) -> dict[str, int]:
    """Cross-check segmentation report boundaries against DB segments."""

    segmentation_path = root / FULL_SEGMENTATION_REPORT_PATH
    if not segmentation_path.is_file():
        _append_anomaly(
            anomalies,
            "missing_full_segmentation_report",
            path="derived/full_segmentation_report.json",
        )
        return {"low_confidence_count": 0}
    try:
        segmentation = json.loads(segmentation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _append_anomaly(
            anomalies,
            "invalid_full_segmentation_report",
            path="derived/full_segmentation_report.json",
            detail=str(exc),
        )
        return {"low_confidence_count": 0}
    if not isinstance(segmentation, dict) or segmentation.get("status") != "succeeded":
        _append_anomaly(
            anomalies,
            "full_segmentation_report_status",
            status=segmentation.get("status") if isinstance(segmentation, dict) else None,
        )
    pages = segmentation.get("pages") if isinstance(segmentation, dict) else None
    if not isinstance(pages, list):
        _append_anomaly(anomalies, "invalid_full_segmentation_pages")
        return {"low_confidence_count": 0}

    segment_rows_by_page: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute(
        """
        SELECT s.item_id, e.source_page_id, sp.source_key, e.page_position,
               s.start_ms_raw, s.end_ms_raw, s.clip_path, s.clip_sha256
        FROM segments AS s
        JOIN entries AS e ON e.item_id = s.item_id
        JOIN source_pages AS sp ON sp.id = e.source_page_id
        ORDER BY sp.table_kind, sp.page_no, e.page_position
        """
    ).fetchall():
        segment_rows_by_page[str(row["source_key"])].append(row)

    low_confidence_count = 0
    allowed_versions = {FULL_ALGORITHM_VERSION, LEADING_ANNOUNCEMENT_ALGORITHM_VERSION}
    for page in pages:
        if not isinstance(page, dict) or not page.get("source_key"):
            _append_anomaly(anomalies, "invalid_full_segmentation_page")
            continue
        source_key = str(page["source_key"])
        expected_items = int(page.get("expected_items") or 0)
        version = page.get("algorithm_version")
        if version not in allowed_versions:
            _append_anomaly(
                anomalies,
                "full_segmentation_algorithm_version",
                source_key=source_key,
                algorithm_version=version,
            )
        selected = page.get("selected_candidates")
        if not isinstance(selected, list) or len(selected) != expected_items + 1:
            _append_anomaly(
                anomalies,
                "full_segmentation_selected_count",
                source_key=source_key,
                expected=expected_items + 1,
                actual=len(selected) if isinstance(selected, list) else None,
            )
            continue
        template_start = page.get("template_start_s")
        try:
            last_boundary = float(selected[-1]["boundary_s"])
            template_start_float = float(template_start)
        except (KeyError, TypeError, ValueError):
            _append_anomaly(
                anomalies,
                "full_segmentation_invalid_boundary_metadata",
                source_key=source_key,
            )
            continue
        if last_boundary >= template_start_float:
            _append_anomaly(
                anomalies,
                "full_segmentation_overlaps_advert",
                source_key=source_key,
                last_boundary_s=last_boundary,
                template_start_s=template_start_float,
            )
        page_rows = sorted(
            segment_rows_by_page.get(source_key, []),
            key=lambda row: (int(row["page_position"]), str(row["item_id"])),
        )
        if len(page_rows) != expected_items:
            _append_anomaly(
                anomalies,
                "full_segmentation_db_rows",
                source_key=source_key,
                expected=expected_items,
                actual=len(page_rows),
            )
            continue
        for position, row in enumerate(page_rows):
            start_ms = int(row["start_ms_raw"])
            end_ms = int(row["end_ms_raw"])
            start_expected = int(round(float(selected[position]["boundary_s"]) * 1000))
            end_expected = int(round(float(selected[position + 1]["boundary_s"]) * 1000))
            if abs(start_ms - start_expected) > 1 or abs(end_ms - end_expected) > 1:
                _append_anomaly(
                    anomalies,
                    "full_candidate_boundary_mismatch",
                    item_id=str(row["item_id"]),
                    source_key=source_key,
                    expected_start_ms=start_expected,
                    expected_end_ms=end_expected,
                    actual_start_ms=start_ms,
                    actual_end_ms=end_ms,
                )
        low_confidence_count += int(page.get("low_confidence_count") or 0)

    report_keys = {
        str(page.get("source_key"))
        for page in pages
        if isinstance(page, dict) and page.get("source_key")
    }
    for row in connection.execute("SELECT source_key FROM source_pages").fetchall():
        if str(row["source_key"]) not in report_keys:
            _append_anomaly(
                anomalies,
                "full_segmentation_page_missing",
                source_key=str(row["source_key"]),
            )
    return {"low_confidence_count": low_confidence_count}


def qa_full(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
) -> dict[str, Any]:
    """Run the full-corpus machine gate and atomically publish its report.

    Unlike the pilot gate, the full gate checks machine structure only: every
    page is fetched/parsed, every entry has a valid segment whose hash, WAV
    format, raw boundaries and advert exclusion match the deterministic
    segmentation report, and every ``excluded_items`` row still resolves to a
    real file.  Human review status is reported but does not block the gate.
    """

    root = Path(data_root).expanduser().resolve()
    anomalies: list[dict[str, Any]] = []
    review_counts = {status: 0 for status in REVIEW_STATUSES}
    stale_count = 0
    low_confidence_count = 0
    excluded_count = 0
    try:
        with _connect_readonly(db_path) as connection:
            expected_count = _full_source_page_checks(
                connection, root=root, anomalies=anomalies
            )
            entries_count = int(
                connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            )
            segments_count = int(
                connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            )
            unique_segments = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT item_id) FROM segments"
                ).fetchone()[0]
            )
            if entries_count != expected_count:
                _append_anomaly(
                    anomalies,
                    "full_entry_count",
                    expected=expected_count,
                    actual=entries_count,
                )
            if segments_count != expected_count:
                _append_anomaly(
                    anomalies,
                    "full_segment_count",
                    expected=expected_count,
                    actual=segments_count,
                )
            if unique_segments != segments_count:
                _append_anomaly(
                    anomalies,
                    "duplicate_segment_item_id",
                    expected=segments_count,
                    actual=unique_segments,
                )
            versions = {
                str(row["algorithm_version"])
                for row in connection.execute(
                    "SELECT DISTINCT algorithm_version FROM segments"
                ).fetchall()
                if row["algorithm_version"] is not None
            }
            allowed_versions = {
                FULL_ALGORITHM_VERSION,
                LEADING_ANNOUNCEMENT_ALGORITHM_VERSION,
                # Human-reviewed re-cuts from the nasal cleaning pass are a
                # machine-verified state (hash-checked on every QA run).
                NASAL_RECUT_ALGORITHM_VERSION,
            }
            if not versions <= allowed_versions:
                _append_anomaly(
                    anomalies,
                    "full_segment_algorithm_version",
                    allowed=sorted(allowed_versions),
                    actual=sorted(versions),
                )
            excluded_count = int(
                connection.execute("SELECT COUNT(*) FROM excluded_items").fetchone()[0]
            )
            for row in connection.execute(
                """
                SELECT x.item_id, s.clip_path
                FROM excluded_items AS x
                JOIN segments AS s ON s.item_id = x.item_id
                ORDER BY x.item_id
                """
            ).fetchall():
                item_id = str(row["item_id"])
                try:
                    clip_path = _safe_path(root, row["clip_path"])
                except QAGateError as exc:
                    _append_anomaly(
                        anomalies,
                        "excluded_clip_path_escape",
                        item_id=item_id,
                        detail=str(exc),
                    )
                    continue
                if clip_path is None or not clip_path.is_file():
                    _append_anomaly(
                        anomalies,
                        "excluded_clip_missing",
                        item_id=item_id,
                        path=_relative_path(clip_path, root) if clip_path else None,
                    )
            segment_rows = connection.execute(
                """
                SELECT e.item_id, e.source_page_id, sp.table_kind, sp.page_no,
                       e.page_position, e.global_seq, s.clip_path, s.clip_sha256,
                       s.start_ms, s.end_ms, s.start_ms_raw, s.end_ms_raw
                FROM segments AS s
                JOIN entries AS e ON e.item_id = s.item_id
                JOIN source_pages AS sp ON sp.id = e.source_page_id
                ORDER BY sp.table_kind, sp.page_no, e.page_position
                """
            ).fetchall()
            for row in segment_rows:
                _validate_clip(row, root=root, anomalies=anomalies)
            _page_boundary_checks(segment_rows, anomalies=anomalies)
            segment_meta = _full_segmentation_checks(
                connection, root=root, anomalies=anomalies
            )
            low_confidence_count = int(segment_meta["low_confidence_count"])
            for row in connection.execute(
                """
                SELECT r.item_id, r.status, r.clip_sha256, s.clip_sha256 AS current_sha
                FROM reviews AS r
                JOIN (
                    SELECT item_id, MAX(revision) AS revision
                    FROM reviews GROUP BY item_id
                ) AS latest
                  ON latest.item_id = r.item_id AND latest.revision = r.revision
                JOIN segments AS s ON s.item_id = r.item_id
                """
            ).fetchall():
                status = str(row["status"])
                if status in review_counts:
                    review_counts[status] += 1
                if (
                    row["clip_sha256"] is not None
                    and row["current_sha"] is not None
                    and row["clip_sha256"] != row["current_sha"]
                ):
                    stale_count += 1
    except QAGateError as exc:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise QAGateError(f"full QA database failure: {exc}") from exc

    anomalies.sort(
        key=lambda value: (
            str(value.get("item_id", "")),
            str(value.get("code", "")),
            json.dumps(value, ensure_ascii=False, sort_keys=True),
        )
    )
    machine_anomalies = len(anomalies)
    gate = "blocked_on_machine_qa" if machine_anomalies else "passed"
    report = {
        "command": "qa",
        "scope": "full",
        "status": gate,
        "gate": gate,
        "entries": entries_count,
        "segments": segments_count,
        "unique_segment_items": unique_segments,
        "expected_count": expected_count,
        "excluded_count": excluded_count,
        "machine_anomalies": machine_anomalies,
        "anomalies": anomalies,
        "low_confidence_count": low_confidence_count,
        "review_counts": {
            **review_counts,
            "stale": stale_count,
        },
        "report": _relative_path(root / FULL_QA_REPORT_PATH, root),
    }
    atomic_write_bytes(root / FULL_QA_REPORT_PATH, _json_bytes(report))
    return report


__all__ = [
    "FULL_QA_REPORT_PATH",
    "PILOT_EXPECTED_COUNT",
    "QA_REPORT_PATH",
    "QAGateError",
    "qa_full",
    "qa_pilot",
]
