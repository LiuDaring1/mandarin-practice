"""Analyze the shared tail advertisement without making any clips.

This module deliberately stops before segmentation.  It decodes the two pilot
MP3s to deterministic 16 kHz mono float PCM, finds a common suffix by comparing
tail-aligned windows, and summarizes low-energy candidate boundaries before the
suffix.  The only files it publishes are the shared template WAV and a JSON
analysis report; the ``segments`` table is never touched.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import subprocess
import wave
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .db import DEFAULT_DB_PATH, connect_db
from .detail_fetch import PILOT_SOURCE_KEYS, atomic_write_bytes


ALGORITHM_VERSION = "advert-analysis-v1"
SAMPLE_RATE = 16_000
TEMPLATE_PATH = Path("derived/analysis/advert_template.wav")
REPORT_PATH = Path("derived/analysis/pilot_analysis.json")
FULL_TEMPLATE_PATH = Path("derived/analysis/advert_template_full.wav")
FULL_REPORT_PATH = Path("derived/analysis/full_analysis.json")
DEFAULT_MAX_TAIL_SECONDS = 15.0
DEFAULT_TEMPLATE_CORRELATION = 0.995
DEFAULT_TEMPLATE_MIN_SECONDS = 0.50
DEFAULT_TEMPLATE_WINDOW_MS = 100
DEFAULT_TEMPLATE_HOP_MS = 10
DEFAULT_TEMPLATE_RELATIVE_DIFF = 0.20
RMS_WINDOW_MS = 20
RMS_HOP_MS = 10
SILENCE_THRESHOLDS_DBFS = (-35.0, -40.0, -45.0)
SILENCE_MIN_DURATIONS_SECONDS = (0.20, 0.35, 0.50)
CANDIDATE_MERGE_SECONDS = 0.15


class AudioAnalysisError(RuntimeError):
    """Raised for unavailable/invalid audio or an invalid analysis request."""


@dataclass(frozen=True, slots=True)
class CommonSuffix:
    """A tail-aligned suffix shared by two decoded signals."""

    length_samples: int
    sample_rate: int
    correlation: float
    difference_rms: float
    relative_difference: float

    @property
    def duration_seconds(self) -> float:
        return self.length_samples / self.sample_rate


@dataclass(frozen=True, slots=True)
class _Interval:
    start_s: float
    end_s: float
    boundary_s: float
    duration_s: float
    depth_dbfs: float
    threshold_dbfs: float
    min_duration_s: float


def _round(value: float, digits: int = 6) -> float:
    """Round report floats so JSON bytes are stable across reruns."""

    return float(round(float(value), digits))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AudioAnalysisError(f"cannot read audio file {path}: {exc}") from exc
    return digest.hexdigest()


def decode_audio_ffmpeg(
    path: str | Path,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Decode one file with ffmpeg to a mono little-endian float32 array.

    The invocation is an argument list (never a shell command), which also
    makes the conversion path straightforward to exercise in tests.
    """

    audio_path = Path(path)
    if sample_rate <= 0:
        raise AudioAnalysisError(f"sample_rate must be > 0, got {sample_rate!r}")
    if not audio_path.is_file():
        raise AudioAnalysisError(f"audio file does not exist: {audio_path}")
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
    except OSError as exc:
        raise AudioAnalysisError(f"ffmpeg unavailable for {audio_path}: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AudioAnalysisError(
            f"ffmpeg decode failed for {audio_path}: {detail or completed.returncode}"
        )
    payload = bytes(completed.stdout or b"")
    if len(payload) % 4:
        raise AudioAnalysisError(
            f"ffmpeg returned partial float sample for {audio_path}"
        )
    samples = np.frombuffer(payload, dtype="<f4").copy()
    if samples.size == 0:
        raise AudioAnalysisError(f"ffmpeg returned no audio samples for {audio_path}")
    if not np.isfinite(samples).all():
        raise AudioAnalysisError(f"ffmpeg returned non-finite samples for {audio_path}")
    return samples


def _window_metrics(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Return (correlation, RMS difference, relative RMS difference)."""

    if x.size == 0 or y.size == 0 or x.size != y.size:
        return 0.0, math.inf, math.inf
    difference = float(np.sqrt(np.mean(np.square(x - y), dtype=np.float64)))
    x_rms = float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))
    y_rms = float(np.sqrt(np.mean(np.square(y), dtype=np.float64)))
    centered_x = x.astype(np.float64, copy=False) - float(np.mean(x, dtype=np.float64))
    centered_y = y.astype(np.float64, copy=False) - float(np.mean(y, dtype=np.float64))
    denominator = float(
        np.sqrt(np.dot(centered_x, centered_x) * np.dot(centered_y, centered_y))
    )
    if denominator <= 1e-12:
        # Two matching silent/constant windows are a valid common tail.  A
        # silent window versus a non-silent one is not.
        correlation = 1.0 if difference <= 1e-7 else 0.0
    else:
        correlation = float(np.dot(centered_x, centered_y) / denominator)
    relative = difference / max(x_rms, y_rms, 1e-6)
    return correlation, difference, relative


def find_common_suffix(
    first: np.ndarray,
    second: np.ndarray,
    *,
    sample_rate: int = SAMPLE_RATE,
    max_tail_seconds: float = DEFAULT_MAX_TAIL_SECONDS,
    window_ms: int = DEFAULT_TEMPLATE_WINDOW_MS,
    hop_ms: int = DEFAULT_TEMPLATE_HOP_MS,
    correlation_threshold: float = DEFAULT_TEMPLATE_CORRELATION,
    relative_difference_threshold: float = DEFAULT_TEMPLATE_RELATIVE_DIFF,
    min_template_seconds: float = DEFAULT_TEMPLATE_MIN_SECONDS,
) -> CommonSuffix | None:
    """Find the longest high-similarity suffix after aligning both ends.

    Windows are inspected from the end towards the beginning.  The first
    failing window defines the template start; therefore no absolute duration
    or ad start second is baked into the algorithm.
    """

    if sample_rate <= 0 or max_tail_seconds <= 0 or window_ms <= 0 or hop_ms <= 0:
        raise AudioAnalysisError("invalid common-suffix timing configuration")
    if not 0.0 < correlation_threshold <= 1.0:
        raise AudioAnalysisError("correlation_threshold must be in (0, 1]")
    if relative_difference_threshold < 0 or min_template_seconds <= 0:
        raise AudioAnalysisError("invalid common-suffix similarity configuration")
    first = np.asarray(first, dtype=np.float32)
    second = np.asarray(second, dtype=np.float32)
    if first.ndim != 1 or second.ndim != 1:
        raise AudioAnalysisError("decoded audio must be one-dimensional")
    window = max(1, round(sample_rate * window_ms / 1000))
    hop = max(1, round(sample_rate * hop_ms / 1000))
    max_samples = min(
        first.size,
        second.size,
        max(1, round(sample_rate * max_tail_seconds)),
    )
    if max_samples < window:
        return None
    first_end = first.size
    second_end = second.size
    first_failure: int | None = None
    # Offset zero is the final window.  An offset of N means that the
    # candidate suffix starts N samples before each respective audio end.
    for offset in range(0, max_samples - window + 1, hop):
        first_start = first_end - offset - window
        second_start = second_end - offset - window
        x = first[first_start : first_end - offset if offset else first_end]
        y = second[second_start : second_end - offset if offset else second_end]
        correlation, _difference, relative = _window_metrics(x, y)
        if not (
            correlation >= correlation_threshold
            and relative <= relative_difference_threshold
        ):
            first_failure = offset
            break
    if first_failure is None:
        length_samples = max_samples
    else:
        length_samples = first_failure
    min_samples = max(1, round(sample_rate * min_template_seconds))
    if length_samples < min_samples:
        return None
    first_template = first[first.size - length_samples :]
    second_template = second[second.size - length_samples :]
    correlation, difference, relative = _window_metrics(first_template, second_template)
    if correlation < correlation_threshold:
        return None
    return CommonSuffix(
        length_samples=int(length_samples),
        sample_rate=int(sample_rate),
        correlation=correlation,
        difference_rms=difference,
        relative_difference=relative,
    )


def _write_template_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write a canonical mono PCM16 WAV through an atomic replacement."""

    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = np.rint(clipped * 32767.0).astype("<i2", copy=False)
    # ``wave`` produces a stable RIFF header for these fixed parameters.
    temporary = bytearray()
    with _wave_bytes_writer(temporary, sample_rate) as handle:
        handle.writeframes(pcm.tobytes())
    atomic_write_bytes(path, bytes(temporary))


class _wave_bytes_writer:
    """Small context manager for writing a ``wave`` file into bytes."""

    def __init__(self, target: bytearray, sample_rate: int) -> None:
        self._target = target
        self._sample_rate = sample_rate
        self._buffer = None
        self._wave = None

    def __enter__(self) -> wave.Wave_write:
        import io

        self._buffer = io.BytesIO()
        self._wave = wave.open(self._buffer, "wb")
        self._wave.setnchannels(1)
        self._wave.setsampwidth(2)
        self._wave.setframerate(self._sample_rate)
        return self._wave

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        assert self._buffer is not None and self._wave is not None
        self._wave.close()
        if exc_type is None:
            self._target.extend(self._buffer.getvalue())
        self._buffer.close()


def rms_dbfs_frames(
    samples: np.ndarray,
    *,
    end_sample: int,
    sample_rate: int = SAMPLE_RATE,
    window_ms: int = RMS_WINDOW_MS,
    hop_ms: int = RMS_HOP_MS,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute RMS dBFS and frame starts before ``end_sample``."""

    if end_sample < 0 or end_sample > len(samples):
        raise AudioAnalysisError("end_sample is outside decoded audio")
    window = max(1, round(sample_rate * window_ms / 1000))
    hop = max(1, round(sample_rate * hop_ms / 1000))
    if end_sample < window:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int64)
    starts = np.arange(0, end_sample - window + 1, hop, dtype=np.int64)
    squared = np.square(np.asarray(samples[:end_sample], dtype=np.float64))
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(squared, dtype=np.float64)))
    powers = (cumulative[starts + window] - cumulative[starts]) / window
    rms = np.sqrt(np.maximum(powers, 0.0))
    dbfs = 20.0 * np.log10(np.maximum(rms, 1e-12))
    return dbfs, starts


def _silence_intervals(
    dbfs: np.ndarray,
    starts: np.ndarray,
    *,
    sample_rate: int,
    window_ms: int,
    threshold_dbfs: float,
    min_duration_s: float,
    end_sample: int,
) -> list[_Interval]:
    window = max(1, round(sample_rate * window_ms / 1000))
    mask = dbfs <= threshold_dbfs
    intervals: list[_Interval] = []
    run_start: int | None = None
    for index, is_silent in enumerate(mask.tolist() + [False]):
        if is_silent:
            if run_start is None:
                run_start = index
            continue
        if run_start is None:
            continue
        run_end = index - 1
        start_sample = int(starts[run_start])
        end_sample_run = min(int(starts[run_end]) + window, end_sample)
        duration_s = (end_sample_run - start_sample) / sample_rate
        if duration_s >= min_duration_s:
            segment_dbfs = dbfs[run_start : run_end + 1]
            min_index = run_start + int(np.argmin(segment_dbfs))
            boundary_s = (int(starts[min_index]) + window / 2) / sample_rate
            intervals.append(
                _Interval(
                    start_s=start_sample / sample_rate,
                    end_s=end_sample_run / sample_rate,
                    boundary_s=boundary_s,
                    duration_s=duration_s,
                    depth_dbfs=float(np.min(segment_dbfs)),
                    threshold_dbfs=threshold_dbfs,
                    min_duration_s=min_duration_s,
                )
            )
        run_start = None
    return intervals


def find_candidate_boundaries(
    samples: np.ndarray,
    *,
    end_sample: int,
    sample_rate: int = SAMPLE_RATE,
    thresholds_dbfs: Sequence[float] = SILENCE_THRESHOLDS_DBFS,
    min_durations_s: Sequence[float] = SILENCE_MIN_DURATIONS_SECONDS,
    window_ms: int = RMS_WINDOW_MS,
    hop_ms: int = RMS_HOP_MS,
    merge_seconds: float = CANDIDATE_MERGE_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Find and merge low-energy boundary candidates before a template."""

    dbfs, starts = rms_dbfs_frames(
        samples,
        end_sample=end_sample,
        sample_rate=sample_rate,
        window_ms=window_ms,
        hop_ms=hop_ms,
    )
    all_intervals: list[_Interval] = []
    threshold_interval_counts: Counter[str] = Counter()
    for threshold in thresholds_dbfs:
        for min_duration in min_durations_s:
            intervals = _silence_intervals(
                dbfs,
                starts,
                sample_rate=sample_rate,
                window_ms=window_ms,
                threshold_dbfs=float(threshold),
                min_duration_s=float(min_duration),
                end_sample=end_sample,
            )
            all_intervals.extend(intervals)
            threshold_interval_counts[str(float(threshold))] += len(intervals)
    all_intervals.sort(key=lambda item: (item.boundary_s, item.start_s, item.end_s))
    clusters: list[list[_Interval]] = []
    for interval in all_intervals:
        if not clusters or interval.boundary_s - clusters[-1][-1].boundary_s > merge_seconds:
            clusters.append([interval])
        else:
            clusters[-1].append(interval)

    candidates: list[dict[str, Any]] = []
    for cluster in clusters:
        deepest = min(cluster, key=lambda item: (item.depth_dbfs, item.boundary_s))
        thresholds = sorted({item.threshold_dbfs for item in cluster})
        min_durations = sorted({item.min_duration_s for item in cluster})
        start_s = min(item.start_s for item in cluster)
        end_s = max(item.end_s for item in cluster)
        candidates.append(
            {
                "boundary_s": _round(deepest.boundary_s),
                "start_s": _round(start_s),
                "end_s": _round(end_s),
                "duration_s": _round(end_s - start_s),
                "depth_dbfs": _round(deepest.depth_dbfs),
                "support_threshold_count": len(thresholds),
                "support_config_count": len(cluster),
                "thresholds_dbfs": [_round(value, 2) for value in thresholds],
                "min_durations_s": [_round(value, 2) for value in min_durations],
            }
        )
    stats = {
        "rms_frame_count": int(dbfs.size),
        "raw_interval_count": len(all_intervals),
        "candidate_count": len(candidates),
        "threshold_interval_counts": {
            key: threshold_interval_counts[key]
            for key in sorted(threshold_interval_counts, key=float)
        },
    }
    return candidates, stats


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _audio_rows(
    db_path: str | Path,
    data_root: Path,
    source_keys: tuple[str, ...] | None = PILOT_SOURCE_KEYS,
) -> list[dict[str, Any]]:
    try:
        with connect_db(db_path) as connection:
            if source_keys is None:
                rows = connection.execute(
                    """
                    SELECT source_key, table_kind, page_no, audio_path
                    FROM source_pages
                    ORDER BY table_kind, page_no
                    """
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in source_keys)
                rows = connection.execute(
                    f"""
                    SELECT source_key, table_kind, page_no, audio_path
                    FROM source_pages
                    WHERE source_key IN ({placeholders})
                    ORDER BY table_kind, page_no
                    """,
                    tuple(source_keys),
                ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        raise AudioAnalysisError(f"cannot read source_pages: {exc}") from exc
    found = {str(row["source_key"]) for row in rows}
    missing = [key for key in (source_keys or ()) if key not in found]
    if missing:
        raise AudioAnalysisError("source_pages missing: " + ", ".join(missing))
    result: list[dict[str, Any]] = []
    for row in rows:
        stored = row["audio_path"]
        relative = str(stored) if stored else f"raw/audio/{row['table_kind']}/001.mp3"
        path = Path(relative)
        if not path.is_absolute():
            path = data_root / path
        result.append(
            {
                "source_key": str(row["source_key"]),
                "table_kind": str(row["table_kind"]),
                "page_no": int(row["page_no"]),
                "audio_path": path,
            }
        )
    return result


def _report_bytes(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _common_suffix_across(decoded: Sequence[np.ndarray]) -> CommonSuffix | None:
    """Longest advert tail shared by every decoded page (intersection)."""

    if len(decoded) < 2:
        return None
    template = decoded[0]
    best: CommonSuffix | None = None
    for other in decoded[1:]:
        suffix = find_common_suffix(template, other)
        if suffix is None:
            return None
        if best is None or suffix.length_samples < best.length_samples:
            best = suffix
    return best


def _analyze(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    scope: str = "pilot",
    source_keys: tuple[str, ...] | None = PILOT_SOURCE_KEYS,
    report_path: Path = REPORT_PATH,
    template_path: Path = TEMPLATE_PATH,
) -> dict[str, Any]:
    """Analyze MP3 tails and publish only template/report artifacts."""

    root = Path(data_root)
    rows = _audio_rows(db_path, root, source_keys)
    inputs: list[dict[str, Any]] = []
    decoded: list[np.ndarray] = []
    for row in rows:
        path = row["audio_path"]
        digest = _sha256_file(path)
        samples = decode_audio_ffmpeg(path)
        decoded.append(samples)
        duration_s = len(samples) / SAMPLE_RATE
        inputs.append(
            {
                "source_key": row["source_key"],
                "table_kind": row["table_kind"],
                "page_no": row["page_no"],
                "audio_path": _relative_path(path, root),
                "audio_sha256": digest,
                "sample_rate": SAMPLE_RATE,
                "duration_s": _round(duration_s),
                "duration_ms": int(round(duration_s * 1000)),
                "sample_count": int(len(samples)),
            }
        )

    suffix = _common_suffix_across(decoded)
    output_path = root / report_path
    template_path = root / template_path
    base_report: dict[str, Any] = {
        "algorithm_version": ALGORITHM_VERSION,
        "config": {
            "sample_rate": SAMPLE_RATE,
            "max_tail_seconds": DEFAULT_MAX_TAIL_SECONDS,
            "template_window_ms": DEFAULT_TEMPLATE_WINDOW_MS,
            "template_hop_ms": DEFAULT_TEMPLATE_HOP_MS,
            "template_correlation_threshold": DEFAULT_TEMPLATE_CORRELATION,
            "template_relative_difference_threshold": DEFAULT_TEMPLATE_RELATIVE_DIFF,
            "template_min_seconds": DEFAULT_TEMPLATE_MIN_SECONDS,
            "rms_window_ms": RMS_WINDOW_MS,
            "rms_hop_ms": RMS_HOP_MS,
            "silence_thresholds_dbfs": list(SILENCE_THRESHOLDS_DBFS),
            "silence_min_durations_s": list(SILENCE_MIN_DURATIONS_SECONDS),
            "candidate_merge_seconds": CANDIDATE_MERGE_SECONDS,
        },
        "inputs": inputs,
        "status": "abnormal" if suffix is None else "succeeded",
        "template": None,
        "pages": [],
    }
    if suffix is None:
        base_report["error"] = "no common high-similarity suffix in the final 15 seconds"
        atomic_write_bytes(output_path, _report_bytes(base_report))
        return {
            "command": "segment",
            "scope": scope,
            "analyze_only": True,
            "status": "abnormal",
            "output": _relative_path(output_path, root),
            "template": None,
            "candidate_count": 0,
        }

    template_samples = decoded[0][-suffix.length_samples :]
    _write_template_wav(template_path, template_samples, SAMPLE_RATE)
    template_digest = _sha256_file(template_path)
    base_report["template"] = {
        "path": _relative_path(template_path, root),
        "sha256": template_digest,
        "sample_rate": SAMPLE_RATE,
        "duration_s": _round(suffix.duration_seconds),
        "length_samples": suffix.length_samples,
        "correlation": _round(suffix.correlation, 9),
        "difference_rms": _round(suffix.difference_rms, 9),
        "relative_difference": _round(suffix.relative_difference, 9),
        "correlation_ok": bool(suffix.correlation >= DEFAULT_TEMPLATE_CORRELATION),
    }
    total_candidates = 0
    for row, samples, input_info in zip(rows, decoded, inputs):
        start_sample = len(samples) - suffix.length_samples
        candidates, stats = find_candidate_boundaries(
            samples,
            end_sample=start_sample,
            sample_rate=SAMPLE_RATE,
        )
        for candidate in candidates:
            candidate["boundary_s"] = _round(candidate["boundary_s"])
        total_candidates += len(candidates)
        page_info = {
            "source_key": row["source_key"],
            "table_kind": row["table_kind"],
            "page_no": row["page_no"],
            "template_start_s": _round(start_sample / SAMPLE_RATE),
            "template_start_from_end_s": _round(suffix.duration_seconds),
            "template_correlation": _round(suffix.correlation, 9),
            "candidate_stats": stats,
            "candidates": candidates,
        }
        base_report["pages"].append(page_info)
    if suffix.correlation < DEFAULT_TEMPLATE_CORRELATION:
        base_report["status"] = "abnormal"
        base_report["error"] = "common suffix correlation below threshold"
    atomic_write_bytes(output_path, _report_bytes(base_report))
    return {
        "command": "segment",
        "scope": scope,
        "analyze_only": True,
        "status": base_report["status"],
        "output": _relative_path(output_path, root),
        "template_path": _relative_path(template_path, root),
        "template_duration_s": _round(suffix.duration_seconds),
        "template_correlation": _round(suffix.correlation, 9),
        "candidate_count": total_candidates,
        "page_candidate_counts": {
            page["table_kind"]: len(page["candidates"]) for page in base_report["pages"]
        },
    }


def analyze_pilot(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
) -> dict[str, Any]:
    """Analyze pilot MP3 tails and publish only template/report artifacts."""

    return _analyze(
        db_path=db_path,
        data_root=data_root,
        scope="pilot",
        source_keys=PILOT_SOURCE_KEYS,
        report_path=REPORT_PATH,
        template_path=TEMPLATE_PATH,
    )


def analyze_full(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
) -> dict[str, Any]:
    """Analyze every fetched MP3 and publish full-corpus template/report."""

    return _analyze(
        db_path=db_path,
        data_root=data_root,
        scope="full",
        source_keys=None,
        report_path=FULL_REPORT_PATH,
        template_path=FULL_TEMPLATE_PATH,
    )


__all__ = [
    "ALGORITHM_VERSION",
    "AudioAnalysisError",
    "CommonSuffix",
    "analyze_full",
    "analyze_pilot",
    "decode_audio_ffmpeg",
    "find_candidate_boundaries",
    "find_common_suffix",
    "rms_dbfs_frames",
]
