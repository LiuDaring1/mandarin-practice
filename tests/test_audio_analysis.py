from __future__ import annotations

import hashlib
import sqlite3
import wave
from pathlib import Path

import numpy as np

from pth_corpus.audio_analysis import (
    analyze_pilot,
    decode_audio_ffmpeg,
    find_candidate_boundaries,
    find_common_suffix,
)
from pth_corpus.db import connect_db, init_db


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _seed_analysis_db(tmp_path: Path, first: np.ndarray, second: np.ndarray) -> tuple[Path, Path]:
    db_path = tmp_path / "corpus.sqlite3"
    data_root = tmp_path / "data"
    init_db(db_path)
    for kind, samples in (("table1", first), ("table2", second)):
        _write_wav(data_root / "raw" / "audio" / kind / "001.wav", samples)
    with connect_db(db_path) as connection:
        connection.executemany(
            "INSERT INTO source_pages "
            "(source_key, table_kind, page_no, url, audio_path) "
            "VALUES (?, ?, 1, ?, ?)",
            (
                ("t1-p001", "table1", "http://fixture/t1", "raw/audio/table1/001.wav"),
                ("t2-p001", "table2", "http://fixture/t2", "raw/audio/table2/001.wav"),
            ),
        )
    return db_path, data_root


def test_find_common_suffix_is_tail_aligned_and_longest():
    rng = np.random.default_rng(3)
    tail = np.sin(np.linspace(0, 40, 1_200, dtype=np.float32)) * 0.4
    first = np.concatenate((rng.normal(0, 0.2, 2_700), tail)).astype(np.float32)
    second = np.concatenate((rng.normal(0, 0.2, 1_900), tail)).astype(np.float32)
    suffix = find_common_suffix(
        first,
        second,
        sample_rate=1_000,
        max_tail_seconds=5,
        window_ms=100,
        hop_ms=10,
        min_template_seconds=0.5,
    )
    assert suffix is not None
    assert 1.0 <= suffix.duration_seconds <= 1.21
    assert suffix.correlation >= 0.995


def test_find_common_suffix_rejects_unrelated_tails():
    rng = np.random.default_rng(4)
    first = rng.normal(0, 0.3, 4_000).astype(np.float32)
    second = rng.normal(0, 0.3, 4_000).astype(np.float32)
    assert find_common_suffix(first, second, sample_rate=1_000, min_template_seconds=0.5) is None


def test_candidates_use_multiple_thresholds_and_merge_nearby_boundaries():
    sample_rate = 1_000
    tone = np.full(700, 0.5, dtype=np.float32)
    silence = np.zeros(450, dtype=np.float32)
    samples = np.concatenate((silence, tone, silence, tone, silence, tone))
    candidates, stats = find_candidate_boundaries(
        samples,
        end_sample=len(samples),
        sample_rate=sample_rate,
        thresholds_dbfs=(-35, -40, -45),
        min_durations_s=(0.20, 0.35, 0.50),
        merge_seconds=0.15,
    )
    assert stats["rms_frame_count"] > 0
    assert stats["raw_interval_count"] >= 3
    assert len(candidates) >= 3
    assert all(candidate["support_threshold_count"] == 3 for candidate in candidates)
    assert all(candidate["duration_s"] >= 0.20 for candidate in candidates)


def test_analyze_pilot_is_deterministic_and_does_not_write_segments(tmp_path):
    rng = np.random.default_rng(9)
    tail = np.sin(np.linspace(0, 100, 16_000, dtype=np.float32)) * 0.25
    first = np.concatenate((rng.normal(0, 0.2, 31_000), tail)).astype(np.float32)
    second = np.concatenate((rng.normal(0, 0.2, 27_000), tail)).astype(np.float32)
    db_path, data_root = _seed_analysis_db(tmp_path, first, second)

    first_summary = analyze_pilot(db_path=db_path, data_root=data_root)
    report_path = data_root / "derived" / "analysis" / "pilot_analysis.json"
    template_path = data_root / "derived" / "analysis" / "advert_template.wav"
    first_report = report_path.read_bytes()
    first_template = template_path.read_bytes()
    second_summary = analyze_pilot(db_path=db_path, data_root=data_root)

    assert first_summary["status"] == second_summary["status"] == "succeeded"
    assert first_report == report_path.read_bytes()
    assert first_template == template_path.read_bytes()
    import json

    report = json.loads(first_report)
    assert hashlib.sha256(first_template).hexdigest() == report["template"]["sha256"]

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0


def test_decode_audio_ffmpeg_real_path(tmp_path):
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    source = np.sin(2 * np.pi * 440 * times) * 0.25
    path = tmp_path / "tone.wav"
    _write_wav(path, source, sample_rate)
    decoded = decode_audio_ffmpeg(path, sample_rate=sample_rate)
    assert decoded.shape == source.shape
    assert np.corrcoef(decoded, source)[0, 1] > 0.999
