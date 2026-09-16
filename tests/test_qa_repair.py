from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
import numpy as np

import pth_corpus.repair as repair
from pth_corpus.qa import qa_pilot
from pth_corpus.repair import RepairError, apply_adjustments
from pth_corpus.segmentation import _wav_bytes, segment_pilot

from test_segmentation import _seed_pilot


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _segmented(tmp_path: Path):
    db_path, root, arrays = _seed_pilot(tmp_path)
    decoder = lambda path: arrays[Path(path).parts[-2]]
    segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    return db_path, root, arrays, decoder


def _segmented_v2(tmp_path: Path):
    db_path, root, arrays = _seed_pilot(tmp_path, leading_title=True)
    decoder = lambda path: arrays[Path(path).parts[-2]]
    segment_pilot(db_path=db_path, data_root=root, decoder=decoder)
    return db_path, root, arrays, decoder


def _approve_all(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO reviews (item_id, status, revision, clip_sha256, reviewer)
            SELECT item_id, 'approved', 1, clip_sha256, 'test'
            FROM segments
            """
        )


def _add_nonpilot_item(db_path: Path, root: Path) -> tuple[Path, str]:
    """Add one extra page/item that must be ignored by the pilot scope."""

    audio_path = root / "raw/audio/table1/extra.bin"
    audio_path.write_bytes(b"nonpilot-audio")
    clip_path = root / "derived/clips/table1/t1-00201.wav"
    clip_path.write_bytes((root / "derived/clips/table1/t1-00001.wav").read_bytes())
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO source_pages (
                source_key, table_kind, page_no, url, expected_items,
                audio_path, audio_sha256
            ) VALUES (?, 'table1', 2, ?, 1, ?, ?)
            """,
            (
                "t1-extra",
                "https://fixture/t1-extra",
                str(audio_path.relative_to(root)),
                _sha(audio_path),
            ),
        )
        page_id = connection.execute(
            "SELECT id FROM source_pages WHERE source_key = 't1-extra'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO entries (
                item_id, source_page_id, table_kind, page_position,
                global_seq, word_raw, pinyin_raw, pinyin_nfc
            ) VALUES ('t1-00201', ?, 'table1', 1, 201, 'extra', 'extra', 'extra')
            """,
            (page_id,),
        )
        connection.execute(
            """
            INSERT INTO segments (
                item_id, clip_path, clip_sha256, algorithm_version,
                start_ms, end_ms, start_ms_raw, end_ms_raw
            ) VALUES ('t1-00201', ?, ?, 'constrained-dp-v1', 0, 100, 0, 100)
            """,
            (str(clip_path.relative_to(root)), _sha(clip_path)),
        )
        clip_hash = _sha(clip_path)
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES ('t1-00201', 'approved', 1, 10, 90, ?, 'test')
            """,
            (clip_hash,),
        )
    return clip_path, clip_hash


def test_initial_qa_is_blocked_on_human_review(tmp_path):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "blocked_on_human_review"
    assert summary["machine_anomalies"] == 0
    assert summary["review_counts"] == {
        "approved": 0,
        "pending": 200,
        "rejected": 0,
        "needs_review": 0,
        "stale": 0,
    }


def test_v2_qa_missing_segmentation_report_is_machine_blocked(tmp_path):
    db_path, root, _arrays, _decoder = _segmented_v2(tmp_path)
    (root / "derived/pilot_segmentation_report.json").unlink()
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "blocked_on_machine_qa"
    assert any(
        anomaly["code"] == "missing_segmentation_report"
        for anomaly in summary["anomalies"]
    )


@pytest.mark.parametrize("tamper", ("selected", "raw"))
def test_v2_qa_rejects_report_or_candidate_boundary_tampering(tmp_path, tamper):
    db_path, root, _arrays, _decoder = _segmented_v2(tmp_path)
    if tamper == "selected":
        report_path = root / "derived/pilot_segmentation_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["pages"][0]["selected_candidate_positions"][0] = 1
        report_path.write_text(json.dumps(report), encoding="utf-8")
        expected_code = "leading_announcement_not_excluded"
    else:
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE segments SET start_ms_raw = start_ms_raw + 10 "
                "WHERE item_id = 't1-00001'"
            )
        expected_code = "candidate_boundary_mismatch"
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "blocked_on_machine_qa"
    assert any(anomaly["code"] == expected_code for anomaly in summary["anomalies"])


def test_qa_and_repair_are_scoped_to_the_two_pilot_pages(tmp_path):
    db_path, root, arrays, decoder = _segmented(tmp_path)
    extra_clip, extra_hash = _add_nonpilot_item(db_path, root)
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["entries"] == 200
    assert summary["segments"] == 200
    assert summary["machine_anomalies"] == 0
    before = extra_clip.read_bytes()
    result = apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)
    assert result["affected"] == 0
    assert extra_clip.read_bytes() == before
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id = 't1-00201'"
        ).fetchone()[0] == extra_hash
        assert connection.execute(
            "SELECT start_ms, end_ms FROM segments WHERE item_id = 't1-00201'"
        ).fetchone() == (0, 100)


def test_missing_template_start_publishes_anomaly_without_type_error(tmp_path):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    report_path = root / "derived/analysis/pilot_analysis.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["pages"][0].pop("template_start_s")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "blocked_on_machine_qa"
    assert any(
        anomaly["code"] == "missing_template_start"
        for anomaly in summary["anomalies"]
    )


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    (
        ("missing", "missing_clip"),
        ("hash", "clip_sha256_mismatch"),
        ("wav", "invalid_wav"),
        ("overlap", "segment_overlap"),
        ("outside_raw", "final_outside_raw"),
    ),
)
def test_qa_reports_machine_anomalies(tmp_path, kind, expected_code):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    clip = root / "derived/clips/table1/t1-00001.wav"
    if kind == "missing":
        clip.unlink()
    elif kind == "hash":
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE segments SET clip_sha256 = ? WHERE item_id = ?",
                ("0" * 64, "t1-00001"),
            )
    elif kind == "wav":
        clip.write_bytes(b"not-a-wav")
    elif kind == "overlap":
        with sqlite3.connect(db_path) as connection:
            end = connection.execute(
                "SELECT end_ms FROM segments WHERE item_id = 't1-00001'"
            ).fetchone()[0]
            connection.execute(
                "UPDATE segments SET start_ms = ? WHERE item_id = 't1-00002'",
                (int(end) - 1,),
            )
    elif kind == "outside_raw":
        with sqlite3.connect(db_path) as connection:
            raw_end = connection.execute(
                "SELECT end_ms_raw FROM segments WHERE item_id = 't1-00001'"
            ).fetchone()[0]
            connection.execute(
                "UPDATE segments SET end_ms = ? WHERE item_id = 't1-00001'",
                (int(raw_end) + 1,),
            )
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "blocked_on_machine_qa"
    assert any(anomaly["code"] == expected_code for anomaly in summary["anomalies"])


def test_qa_passes_with_current_hash_approved_reviews(tmp_path):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    _approve_all(db_path)
    summary = qa_pilot(db_path=db_path, data_root=root)
    assert summary["status"] == "passed"
    assert summary["machine_anomalies"] == 0
    assert summary["review_counts"]["approved"] == 200


def test_stale_review_is_human_gate_and_unapplied_adjustment_is_machine_gate(tmp_path):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    _approve_all(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE reviews SET clip_sha256 = ? WHERE item_id = ?",
            ("stale", "t1-00001"),
        )
    stale = qa_pilot(db_path=db_path, data_root=root)
    assert stale["status"] == "blocked_on_human_review"
    assert stale["review_counts"]["stale"] == 1
    assert stale["review_counts"]["approved"] == 199

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT clip_sha256, start_ms, end_ms FROM segments WHERE item_id = ?",
            ("t1-00002",),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES (?, 'approved', 2, ?, ?, ?, 'test')
            """,
            ("t1-00002", int(row[1]) + 10, int(row[2]) - 10, row[0]),
        )
    unapplied = qa_pilot(db_path=db_path, data_root=root)
    assert unapplied["status"] == "blocked_on_machine_qa"
    assert unapplied["machine_anomalies"] == 1
    assert unapplied["unapplied_adjustments"][0]["item_id"] == "t1-00002"


def test_selective_repair_is_hash_selective_and_idempotent(tmp_path):
    db_path, root, arrays, decoder = _segmented(tmp_path)
    with sqlite3.connect(db_path) as connection:
        target = connection.execute(
            "SELECT clip_sha256, start_ms, end_ms FROM segments WHERE item_id = ?",
            ("t1-00001",),
        ).fetchone()
        untouched = connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id = ?", ("t1-00002",)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES (?, 'approved', 1, ?, ?, ?, 'test')
            """,
            ("t1-00001", int(target[1]) + 10, int(target[2]) - 10, target[0]),
        )
    old_clip = root / "derived/clips/table1/t1-00001.wav"
    old_hash = _sha(old_clip)
    summary = apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)
    assert summary["affected"] == 1
    repair_report = root / "review/pilot_repair_report.json"
    first_report_bytes = repair_report.read_bytes()
    first_report = json.loads(first_report_bytes)
    assert len(first_report["events"]) == 1
    event = first_report["events"][0]
    assert {
        "item_id",
        "revision",
        "old_start_ms",
        "old_end_ms",
        "new_start_ms",
        "new_end_ms",
        "old_clip_sha256",
        "new_clip_sha256",
        "algorithm_version",
    } <= event.keys()
    with sqlite3.connect(db_path) as connection:
        updated = connection.execute(
            "SELECT clip_sha256, start_ms, end_ms, algorithm_version "
            "FROM segments WHERE item_id = ?",
            ("t1-00001",),
        ).fetchone()
        assert updated[1:] == (int(target[1]) + 10, int(target[2]) - 10, "constrained-dp-v1+manual-adjust-v1")
        assert updated[0] != old_hash
        assert connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id = ?", ("t1-00002",)
        ).fetchone()[0] == untouched
        assert connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE item_id = ?", ("t1-00001",)
        ).fetchone()[0] == 1
    qa_after = qa_pilot(db_path=db_path, data_root=root)
    assert qa_after["review_counts"]["stale"] == 1
    assert qa_after["review_counts"]["pending"] == 200
    second = apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)
    assert second["affected"] == 0
    assert repair_report.read_bytes() == first_report_bytes


def test_repair_rejects_same_hash_boundary_change(tmp_path):
    db_path, root, _arrays, _decoder = _segmented(tmp_path)
    clip = root / "derived/clips/table1/t1-00001.wav"
    payload = _wav_bytes(np.full(1_600, 0.2, dtype=np.float32))
    clip.write_bytes(payload)
    clip_hash = _sha(clip)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE segments
            SET clip_sha256 = ?, start_ms = 100, end_ms = 200,
                start_ms_raw = 0, end_ms_raw = 1000
            WHERE item_id = 't1-00001'
            """,
            (clip_hash,),
        )
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES ('t1-00001', 'approved', 1, 110, 210, ?, 'test')
            """,
            (clip_hash,),
        )
    before = clip.read_bytes()
    with pytest.raises(RepairError, match="same clip SHA256"):
        apply_adjustments(
            db_path=db_path,
            data_root=root,
            decoder=lambda _path: np.full(16_000, 0.2, dtype=np.float32),
        )
    assert clip.read_bytes() == before
    assert not (root / "review/pilot_repair_report.json").exists()


def test_repair_rejects_missing_source_audio_hash(tmp_path):
    db_path, root, _arrays, decoder = _segmented(tmp_path)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT clip_sha256, start_ms, end_ms FROM segments WHERE item_id = 't1-00001'"
        ).fetchone()
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES ('t1-00001', 'approved', 1, ?, ?, ?, 'test')
            """,
            (int(row[1]) + 10, int(row[2]) - 10, row[0]),
        )
        connection.execute(
            "UPDATE source_pages SET audio_sha256 = NULL WHERE source_key = 't1-p001'"
        )
    with pytest.raises(RepairError, match="source audio hash is missing"):
        apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)


def test_repair_rejects_nonexistent_database_without_creating_it(tmp_path):
    db_path = tmp_path / "missing" / "corpus.sqlite3"
    with pytest.raises(RepairError, match="database does not exist"):
        apply_adjustments(db_path=db_path, data_root=tmp_path / "data")
    assert not db_path.exists()


def test_repair_restores_first_file_db_and_report_when_second_replace_fails(
    monkeypatch, tmp_path
):
    db_path, root, _arrays, decoder = _segmented(tmp_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT item_id, clip_sha256, start_ms, end_ms FROM segments "
            "WHERE item_id IN ('t1-00001', 't1-00002') ORDER BY item_id"
        ).fetchall()
        for item_id, clip_hash, start_ms, end_ms in rows:
            connection.execute(
                """
                INSERT INTO reviews (
                    item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                    clip_sha256, reviewer
                ) VALUES (?, 'approved', 1, ?, ?, ?, 'test')
                """,
                (item_id, int(start_ms) + 10, int(end_ms) - 10, clip_hash),
            )
        before_segments = connection.execute(
            "SELECT item_id, start_ms, end_ms, clip_sha256, algorithm_version "
            "FROM segments WHERE item_id IN ('t1-00001', 't1-00002') ORDER BY item_id"
        ).fetchall()
    clips = [
        root / "derived/clips/table1/t1-00001.wav",
        root / "derived/clips/table1/t1-00002.wav",
    ]
    before_clips = [clip.read_bytes() for clip in clips]
    real_replace = repair.os.replace
    calls = 0

    def flaky_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(repair.os, "replace", flaky_replace)
    with pytest.raises(RepairError, match="injected second replacement failure"):
        apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)
    assert [clip.read_bytes() for clip in clips] == before_clips
    assert not (root / "review/pilot_repair_report.json").exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT item_id, start_ms, end_ms, clip_sha256, algorithm_version "
            "FROM segments WHERE item_id IN ('t1-00001', 't1-00002') ORDER BY item_id"
        ).fetchall() == before_segments


def test_illegal_adjustment_does_not_change_files_or_database(tmp_path):
    db_path, root, _arrays, decoder = _segmented(tmp_path)
    with sqlite3.connect(db_path) as connection:
        target = connection.execute(
            "SELECT clip_sha256, start_ms_raw, end_ms_raw, start_ms, end_ms "
            "FROM segments WHERE item_id = ?",
            ("t1-00001",),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO reviews (
                item_id, status, revision, adjusted_start_ms, adjusted_end_ms,
                clip_sha256, reviewer
            ) VALUES (?, 'approved', 1, ?, ?, ?, 'test')
            """,
            ("t1-00001", int(target[3]), int(target[2]) + 1, target[0]),
        )
    clip = root / "derived/clips/table1/t1-00001.wav"
    before_clip = clip.read_bytes()
    with sqlite3.connect(db_path) as connection:
        before_segment = connection.execute(
            "SELECT * FROM segments WHERE item_id = ?", ("t1-00001",)
        ).fetchone()
    with pytest.raises(RepairError, match="outside raw bounds"):
        apply_adjustments(db_path=db_path, data_root=root, decoder=decoder)
    assert clip.read_bytes() == before_clip
    assert not (root / "review/pilot_repair_report.json").exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT * FROM segments WHERE item_id = ?", ("t1-00001",)
        ).fetchone() == before_segment
