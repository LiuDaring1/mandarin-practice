from __future__ import annotations

import hashlib
import json
import sqlite3
import wave
from pathlib import Path

import numpy as np
import pytest

from pth_corpus.db import connect_db, init_db
from pth_corpus.segmentation import (
    LEADING_ANNOUNCEMENT_ALGORITHM_VERSION,
    SegmentationError,
    SEGMENTATION_REPORT_PATH,
    select_leading_announcement_boundaries,
    segment_pilot,
    select_boundaries_dp,
    trim_speech_bounds,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_list(count: int = 101, *, extra: bool = False) -> list[dict[str, float | int]]:
    values = [round(index * 0.2, 6) for index in range(count)]
    if extra:
        values.insert(51, 10.1)
    return [
        {
            "boundary_s": value,
            "depth_dbfs": -80.0,
            "support_config_count": 9,
            "support_threshold_count": 3,
        }
        for value in values
    ]


def _seed_pilot(
    tmp_path: Path,
    *,
    silence_second: bool = False,
    extra_candidate: bool = False,
    leading_title: bool = False,
) -> tuple[Path, Path, dict[str, np.ndarray]]:
    root = tmp_path / "data"
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    root.joinpath("raw/audio/table1").mkdir(parents=True)
    root.joinpath("raw/audio/table2").mkdir(parents=True)
    root.joinpath("derived/analysis").mkdir(parents=True)
    template = root / "derived/analysis/advert_template.wav"
    template.write_bytes(b"synthetic-template")

    arrays: dict[str, np.ndarray] = {}
    candidates = _candidate_list(
        count=102 if leading_title else 101,
        extra=extra_candidate,
    )
    interval_count = 100
    interval_samples = 3_200  # 200 ms
    template_samples = 9_600  # 600 ms; the selected final boundary is 100 ms before it
    for table_no, table_kind in ((1, "table1"), (2, "table2")):
        pieces: list[np.ndarray] = []
        if leading_title:
            title_speech = np.full(1_000, 0.15 + table_no * 0.01, dtype=np.float32)
            pieces.append(
                np.concatenate(
                    (title_speech, np.zeros(interval_samples - title_speech.size, dtype=np.float32))
                )
            )
        for _ in range(interval_count):
            if table_no == 2 and silence_second:
                pieces.append(np.zeros(interval_samples, dtype=np.float32))
            else:
                speech = np.full(1_600, 0.2 + table_no * 0.01, dtype=np.float32)
                pieces.append(np.concatenate((speech, np.zeros(1_600, dtype=np.float32))))
        arrays[table_kind] = np.concatenate(
            (*pieces, np.zeros(template_samples, dtype=np.float32))
        )
        audio_path = root / "raw/audio" / table_kind / "001.bin"
        audio_path.write_bytes(f"audio-{table_no}".encode())

    with connect_db(db_path) as connection:
        for table_no, table_kind in ((1, "table1"), (2, "table2")):
            source_key = f"t{table_no}-p001"
            audio_path = root / "raw/audio" / table_kind / "001.bin"
            connection.execute(
                """
                INSERT INTO source_pages (
                    source_key, table_kind, page_no, url, expected_items,
                    audio_path, audio_sha256
                ) VALUES (?, ?, 1, ?, 100, ?, ?)
                """,
                (
                    source_key,
                    table_kind,
                    f"https://fixture/{source_key}",
                    str(audio_path.relative_to(root)),
                    _sha(audio_path),
                ),
            )
            page_id = connection.execute(
                "SELECT id FROM source_pages WHERE source_key = ?", (source_key,)
            ).fetchone()[0]
            connection.executemany(
                """
                INSERT INTO entries (
                    item_id, source_page_id, table_kind, page_position,
                    global_seq, word_raw, pinyin_raw, pinyin_nfc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"t{table_no}-{position:05d}",
                        page_id,
                        table_kind,
                        position,
                        (table_no - 1) * 100 + position,
                        f"word{position}",
                        "word",
                        "word",
                    )
                    for position in range(1, 101)
                ],
            )

    pages = []
    for table_no, table_kind in ((1, "table1"), (2, "table2")):
        audio_path = root / "raw/audio" / table_kind / "001.bin"
        sample_count = arrays[table_kind].size
        pages.append(
            {
                "source_key": f"t{table_no}-p001",
                "table_kind": table_kind,
                "page_no": 1,
                "template_start_s": 20.3 if leading_title else 20.1,
                "template_start_from_end_s": 0.5,
                "candidates": candidates,
                **({"leading_announcement": True} if leading_title else {}),
            }
        )
    report = {
        "algorithm_version": "advert-analysis-v1",
        "config": {"template_correlation_threshold": 0.995},
        "status": "succeeded",
        "template": {
            "path": "derived/analysis/advert_template.wav",
            "sha256": _sha(template),
            "sample_rate": 16_000,
            "duration_s": 0.5,
            "length_samples": template_samples,
            "correlation": 1.0,
            "correlation_ok": True,
        },
        "inputs": [
            {
                "source_key": f"t{table_no}-p001",
                "table_kind": table_kind,
                "page_no": 1,
                "audio_path": f"raw/audio/{table_kind}/001.bin",
                "audio_sha256": _sha(root / "raw/audio" / table_kind / "001.bin"),
                "sample_rate": 16_000,
                "sample_count": int(arrays[table_kind].size),
                "duration_s": round(arrays[table_kind].size / 16_000, 6),
            }
            for table_no, table_kind in ((1, "table1"), (2, "table2"))
        ],
        "pages": pages,
    }
    (root / "derived/analysis/pilot_analysis.json").write_text(
        json.dumps(report, sort_keys=True), encoding="utf-8"
    )
    return db_path, root, arrays


def test_dp_selects_exact_count_and_forces_endpoints():
    selected, discarded, details = select_boundaries_dp(
        _candidate_list(extra=True), expected_items=100
    )
    assert len(selected) == 101
    assert selected[0]["boundary_s"] == 0.0
    assert selected[-1]["boundary_s"] == 20.0
    assert discarded == [52]  # the inserted 10.1 s internal pause
    assert details["required_boundary_count"] == 101


def test_dp_rejects_insufficient_candidates():
    with pytest.raises(SegmentationError, match="insufficient candidates"):
        select_boundaries_dp(_candidate_list(10), expected_items=10)


def test_trim_speech_rejects_no_speech():
    with pytest.raises(SegmentationError, match="no speech"):
        trim_speech_bounds(np.zeros(16_000, dtype=np.float32), 0, 8_000)


def test_template_hash_mismatch_aborts_without_segments(tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path)
    report_path = root / "derived/analysis/pilot_analysis.json"
    report = json.loads(report_path.read_text())
    report["template"]["sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SegmentationError, match="template SHA256"):
        segment_pilot(
            db_path=db_path,
            data_root=root,
            decoder=lambda path: arrays[Path(path).parts[-2]],
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0


def test_no_speech_page_does_not_publish_first_page(tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path, silence_second=True)
    with pytest.raises(SegmentationError, match="no speech"):
        segment_pilot(
            db_path=db_path,
            data_root=root,
            decoder=lambda path: arrays[Path(path).parts[-2]],
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0
    assert not (root / "derived/clips").exists()


def test_segment_publishes_200_deterministic_wavs_and_is_idempotent(tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path, extra_candidate=True)
    decoder = lambda path: arrays[Path(path).parts[-2]]
    first = segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    assert first["segments"] == 200
    clips = sorted((root / "derived/clips").rglob("*.wav"))
    assert len(clips) == 200
    for clip in clips:
        with wave.open(str(clip), "rb") as handle:
            assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (1, 2, 16_000)
            assert handle.getnframes() > 0
    before = {
        path.relative_to(root).as_posix(): _sha(path)
        for path in [*clips, root / SEGMENTATION_REPORT_PATH]
    }
    second = segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    assert second["segments"] == 200
    after = {
        path.relative_to(root).as_posix(): _sha(path)
        for path in [*sorted((root / "derived/clips").rglob("*.wav")), root / SEGMENTATION_REPORT_PATH]
    }
    assert before == after
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 200
        assert connection.execute(
            "SELECT COUNT(*) FROM segments WHERE algorithm_version = 'constrained-dp-v1'"
        ).fetchone()[0] == 200


def test_existing_different_hash_is_preserved_and_aborts_before_publish(tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path)
    decoder = lambda path: arrays[Path(path).parts[-2]]
    segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    destination = root / "derived/clips/table1/t1-00001.wav"
    destination.write_bytes(b"existing-good-file")
    before = destination.read_bytes()
    with pytest.raises(SegmentationError, match="different hash"):
        segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    assert destination.read_bytes() == before


def test_database_upsert_failure_removes_new_clips(monkeypatch, tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path)

    def fail_upsert(*_args, **_kwargs):
        raise SegmentationError("db failed")

    monkeypatch.setattr("pth_corpus.segmentation._upsert_segments", fail_upsert)
    with pytest.raises(SegmentationError, match="db failed"):
        segment_pilot(
            db_path=db_path,
            data_root=root,
            decoder=lambda path: arrays[Path(path).parts[-2]],
        )
    assert not list((root / "derived/clips").rglob("*.wav"))
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0


def test_leading_announcement_selection_excludes_title_and_keeps_all_internal_boundaries():
    candidates = _candidate_list(count=102)
    selected, discarded, details = select_leading_announcement_boundaries(
        candidates, expected_items=100
    )
    assert len(selected) == 101
    assert [item["boundary_s"] for item in selected] == [
        item["boundary_s"] for item in candidates[1:]
    ]
    assert details["selected_indices"] == list(range(2, 103))
    assert details["excluded_candidate_positions"] == [1]
    assert discarded == []


def test_segment_leading_announcement_publishes_v2_clips_and_exact_mapping(tmp_path):
    db_path, root, arrays = _seed_pilot(tmp_path, leading_title=True)
    decoder = lambda path: arrays[Path(path).parts[-2]]
    result = segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    assert result["segments"] == 200
    clips = sorted((root / "derived/clips-v2").rglob("*.wav"))
    assert len(clips) == 200
    assert not (root / "derived/clips").exists()
    config = json.loads((root / "derived/segmentation_config.json").read_text(encoding="utf-8"))
    policy = config["leading_announcement"]
    assert policy["excluded_leading_units"] == 1
    assert policy["candidate_count_delta"] == 2
    assert policy["selected_position_rule"] == (
        "one_based_positions_2_through_expected_items_plus_2"
    )
    assert "excluded_interval_s" not in policy
    assert "selected_indices" not in policy
    report = json.loads((root / SEGMENTATION_REPORT_PATH).read_text(encoding="utf-8"))
    assert report["algorithm_version"] == LEADING_ANNOUNCEMENT_ALGORITHM_VERSION
    assert report["leading_announcement"] == policy
    for page in report["pages"]:
        assert page["selected_candidate_positions"] == list(range(2, 103))
        assert page["discarded_candidate_positions"] == []
        assert page["excluded_candidate_positions"] == [1]
        assert page["leading_announcement"]["excluded_interval_s"] == {
            "start_s": 0.0,
            "end_s": 0.2,
        }
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 200
        assert connection.execute(
            "SELECT COUNT(*) FROM segments WHERE algorithm_version = ?",
            (LEADING_ANNOUNCEMENT_ALGORITHM_VERSION,),
        ).fetchone()[0] == 200
        assert connection.execute(
            "SELECT COUNT(*) FROM segments WHERE clip_path LIKE 'derived/clips-v2/%'"
        ).fetchone()[0] == 200
        first = connection.execute(
            "SELECT start_ms_raw, end_ms_raw FROM segments WHERE item_id = 't1-00001'"
        ).fetchone()
        assert tuple(first) == (200, 400)


def test_real_pilot_analysis_maps_title_exclusion_to_positions():
    report_path = Path("data/derived/analysis/pilot_analysis.json")
    if not report_path.is_file():
        pytest.skip("pilot analysis fixture is not present")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for page in report["pages"]:
        candidates = page["candidates"]
        assert len(candidates) == 102
        _selected, discarded, details = select_leading_announcement_boundaries(
            candidates, expected_items=100
        )
        assert details["selected_indices"] == list(range(2, 103))
        assert discarded == []
