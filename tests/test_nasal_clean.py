"""Tests for the nasal-clean exclusion / re-cut / undo pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import wave
from pathlib import Path

import numpy as np
import pytest

from pth_corpus.db import connect_db, init_db
from pth_corpus.nasal_clean import (
    NASAL_RECUT_ALGORITHM_VERSION,
    NasalCleanError,
    apply_nasal_decisions,
    load_decisions,
    undo_nasal_clean,
)
from pth_corpus.segmentation import _wav_bytes


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _wav_payload(duration_ms: int = 500, freq: float = 440.0) -> bytes:
    rate = 16_000
    samples = np.sin(
        2 * np.pi * freq * np.arange(int(rate * duration_ms / 1000)) / rate
    ) * 0.25
    return _wav_bytes(samples.astype(np.float32))


def _seed(tmp_path: Path) -> tuple[Path, Path, np.ndarray]:
    root = tmp_path / "data"
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    (root / "raw/audio/table1").mkdir(parents=True)
    (root / "derived/clips-v2/table1").mkdir(parents=True)
    (root / "derived/clips-excluded").mkdir(parents=True)
    source = np.sin(2 * np.pi * 220.0 * np.arange(16_000) / 16_000) * 0.25
    source_bytes = _wav_bytes(source.astype(np.float32))
    (root / "raw/audio/table1/001.wav").write_bytes(source_bytes)
    source_hash = _sha(source_bytes)

    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO source_pages (
                source_key, table_kind, page_no, url, expected_items,
                audio_path, audio_sha256
            ) VALUES ('t1-p001', 'table1', 1, 'https://fixture/t1-p001', 3, ?, ?)
            """,
            ("raw/audio/table1/001.wav", source_hash),
        )
        page_id = connection.execute(
            "SELECT id FROM source_pages WHERE source_key = 't1-p001'"
        ).fetchone()[0]
        for seq, (item_id, word, pinyin) in enumerate(
            (
                ("t1-00001", "成人", "chéngrén"),
                ("t1-00002", "安全", "ānquán"),
                ("t1-00003", "本领", "běnlǐng"),
            ),
            start=1,
        ):
            clip_path = root / "derived/clips-v2/table1" / f"{item_id}.wav"
            clip_path.write_bytes(_wav_payload(500))
            connection.execute(
                """
                INSERT INTO entries (
                    item_id, source_page_id, table_kind, page_position,
                    global_seq, word_raw, pinyin_raw, pinyin_nfc
                ) VALUES (?, ?, 'table1', ?, ?, ?, ?, ?)
                """,
                (item_id, page_id, seq, seq, word, pinyin, pinyin),
            )
            connection.execute(
                """
                INSERT INTO segments (
                    item_id, clip_path, clip_sha256, algorithm_version,
                    start_ms, end_ms, start_ms_raw, end_ms_raw, confidence
                ) VALUES (?, ?, ?, 'constrained-dp-v2-full', 0, 500, 0, 500, 0.95)
                """,
                (
                    item_id,
                    f"derived/clips-v2/table1/{item_id}.wav",
                    _sha(clip_path.read_bytes()),
                ),
            )

    formal = (
        "item_id,table_kind,word_raw,pinyin_nfc,global_seq,clip_path,clip_sha256,confidence\n"
        f"t1-00001,table1,成人,chéngrén,1,derived/clips-v2/table1/t1-00001.wav,"
        f"{_sha((root / 'derived/clips-v2/table1/t1-00001.wav').read_bytes())},0.95\n"
        f"t1-00002,table1,安全,ānquán,2,derived/clips-v2/table1/t1-00002.wav,"
        f"{_sha((root / 'derived/clips-v2/table1/t1-00002.wav').read_bytes())},0.95\n"
        f"t1-00003,table1,本领,běnlǐng,3,derived/clips-v2/table1/t1-00003.wav,"
        f"{_sha((root / 'derived/clips-v2/table1/t1-00003.wav').read_bytes())},0.95\n"
    )
    (root / "derived" / "formal_corpus.csv").write_text(formal, encoding="utf-8")
    (root / "derived" / "excluded_items.csv").write_text(
        "item_id,table_kind,word_raw,pinyin_nfc,kinds,detail,old_clip_path,new_clip_path\n",
        encoding="utf-8",
    )
    return root, db_path, source


def _decisions_csv(
    tmp_path: Path, rows: list[dict[str, str]], name: str = "nasal_decisions_batch_01.csv"
) -> Path:
    path = tmp_path / name
    lines = [
        "item_id,word,pinyin,tier,verdict,notes,adjusted_start_ms,adjusted_end_ms,reviewed_at,reviewer"
    ]
    for row in rows:
        lines.append(
            ",".join(
                row.get(key, "")
                for key in (
                    "item_id",
                    "word",
                    "pinyin",
                    "tier",
                    "verdict",
                    "notes",
                    "adjusted_start_ms",
                    "adjusted_end_ms",
                    "reviewed_at",
                    "reviewer",
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _state(db_path: Path, item_id: str) -> dict:
    with connect_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT s.clip_path, s.clip_sha256, s.start_ms, s.end_ms,
                   s.algorithm_version, x.item_id AS excluded_id,
                   x.kind, x.reason
            FROM segments AS s
            LEFT JOIN excluded_items AS x ON x.item_id = s.item_id
            WHERE s.item_id = ?
            """,
            (item_id,),
        ).fetchone()
    return dict(row)


def test_load_decisions_merges_and_rejects_conflicts(tmp_path):
    a = _decisions_csv(tmp_path, [{"item_id": "t1-00001", "verdict": "wrong_word"}], "a.csv")
    b = _decisions_csv(tmp_path, [{"item_id": "t1-00002", "verdict": "ok"}], "b.csv")
    merged = load_decisions([a, b])
    assert set(merged) == {"t1-00001", "t1-00002"}
    conflict = _decisions_csv(tmp_path, [{"item_id": "t1-00001", "verdict": "ok"}], "c.csv")
    with pytest.raises(NasalCleanError, match="conflicting"):
        load_decisions([a, conflict])
    bad = _decisions_csv(tmp_path, [{"item_id": "t1-00001", "verdict": "bogus"}], "d.csv")
    with pytest.raises(NasalCleanError, match="unknown verdict"):
        load_decisions([bad])


def test_apply_excludes_and_recuts_and_is_idempotent(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [
            {"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
             "tier": "T2_mismatch", "verdict": "wrong_word", "notes": "读成行人"},
            {"item_id": "t1-00002", "word": "安全", "pinyin": "ānquán",
             "tier": "T3_shift", "verdict": "shift", "notes": "串位",
             "adjusted_start_ms": "10", "adjusted_end_ms": "490"},
        ],
    )
    decoder = lambda _path: source
    summary = apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=decoder,
    )
    assert summary["excluded"] == 1
    assert summary["recut"] == 1
    assert summary["kinds"] == {"audio_word_mismatch": 1}

    # Exclusion landed everywhere it should.
    state = _state(db_path, "t1-00001")
    assert state["excluded_id"] == "t1-00001"
    assert state["kind"] == "audio_word_mismatch"
    assert state["reason"] == "nasal_review_batch_01"
    assert state["clip_path"] == "derived/clips-excluded/table1/t1-00001.wav"
    assert (root / "derived/clips-excluded/table1/t1-00001.wav").is_file()
    assert not (root / "derived/clips-v2/table1/t1-00001.wav").is_file()
    manifest = (root / "derived/excluded_items.csv").read_text(encoding="utf-8")
    assert "t1-00001" in manifest and "clips-excluded/table1/t1-00001.wav" in manifest
    formal = (root / "derived/formal_corpus.csv").read_text(encoding="utf-8")
    assert "t1-00001," not in formal
    assert "t1-00002," in formal and "t1-00003," in formal

    # Re-cut landed everywhere it should.
    recut = _state(db_path, "t1-00002")
    assert recut["excluded_id"] is None
    assert recut["algorithm_version"] == NASAL_RECUT_ALGORITHM_VERSION
    assert (recut["start_ms"], recut["end_ms"]) == (10, 490)
    clip = root / "derived/clips-v2/table1/t1-00002.wav"
    assert _sha(clip.read_bytes()) == recut["clip_sha256"]
    backup = root / "derived/nasal-cleaning/recut-backup/t1-00002.wav"
    assert backup.is_file()
    report = json.loads(
        (root / "derived/nasal-cleaning/nasal_repair_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["events"][0]["item_id"] == "t1-00002"
    assert report["events"][0]["old_start_ms"] == 0
    assert report["events"][0]["new_start_ms"] == 10

    # Idempotent re-run changes nothing.
    before_formal = (root / "derived/formal_corpus.csv").read_bytes()
    again = apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=decoder,
    )
    assert again["excluded"] == 0 and again["recut"] == 0
    assert again["already_applied"] == 2
    assert (root / "derived/formal_corpus.csv").read_bytes() == before_formal


def test_dry_run_changes_nothing(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
          "tier": "T2_mismatch", "verdict": "wrong_word"}],
    )
    before = (root / "derived/clips-v2/table1/t1-00001.wav").read_bytes()
    summary = apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        dry_run=True,
        decoder=lambda _path: source,
    )
    assert summary["dry_run"] is True
    assert summary["exclude_count"] == 1
    assert (root / "derived/clips-v2/table1/t1-00001.wav").read_bytes() == before
    assert _state(db_path, "t1-00001")["excluded_id"] is None
    assert not (root / "derived/clips-excluded/table1/t1-00001.wav").exists()


def test_shift_without_bounds_excludes_with_audio_shift(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00003", "word": "本领", "pinyin": "běnlǐng",
          "tier": "T3_shift", "verdict": "shift", "notes": "无法重切"}],
    )
    summary = apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=lambda _path: source,
    )
    assert summary["kinds"] == {"audio_shift": 1}
    assert _state(db_path, "t1-00003")["kind"] == "audio_shift"


def test_apply_rejects_clip_hash_drift(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
          "tier": "T2_mismatch", "verdict": "wrong_word"}],
    )
    clip = root / "derived/clips-v2/table1/t1-00001.wav"
    clip.write_bytes(_wav_payload(600))
    with pytest.raises(NasalCleanError, match="hash does not match"):
        apply_nasal_decisions(
            db_path=db_path,
            data_root=root,
            decisions_csvs=[decisions],
            decoder=lambda _path: source,
        )
    assert _state(db_path, "t1-00001")["excluded_id"] is None
    assert not (root / "derived/clips-excluded/table1/t1-00001.wav").exists()


def test_apply_rejects_partial_exclusion_state(tmp_path):
    root, db_path, source = _seed(tmp_path)
    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO excluded_items (item_id, reason, kind, detail)
            VALUES ('t1-00001', 'nasal_review_batch_01', 'audio_word_mismatch', 'x')
            """
        )
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
          "tier": "T2_mismatch", "verdict": "wrong_word"}],
    )
    with pytest.raises(NasalCleanError, match="partial state"):
        apply_nasal_decisions(
            db_path=db_path,
            data_root=root,
            decisions_csvs=[decisions],
            decoder=lambda _path: source,
        )


def test_recut_requires_bounds_within_raw(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00002", "word": "安全", "pinyin": "ānquán",
          "tier": "T3_shift", "verdict": "shift",
          "adjusted_start_ms": "0", "adjusted_end_ms": "700"}],
    )
    with pytest.raises(NasalCleanError, match="outside raw bounds"):
        apply_nasal_decisions(
            db_path=db_path,
            data_root=root,
            decisions_csvs=[decisions],
            decoder=lambda _path: source,
        )


def test_undo_restores_exclusions_and_recuts(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [
            {"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
             "tier": "T2_mismatch", "verdict": "wrong_word"},
            {"item_id": "t1-00002", "word": "安全", "pinyin": "ānquán",
             "tier": "T3_shift", "verdict": "shift",
             "adjusted_start_ms": "10", "adjusted_end_ms": "490"},
        ],
    )
    decoder = lambda _path: source
    apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=decoder,
    )
    original_sha = _sha(_wav_payload(500))
    original_clip_bytes = (root / "derived/clips-excluded/table1/t1-00001.wav").read_bytes()
    assert original_sha == _sha(original_clip_bytes)

    result = undo_nasal_clean(
        db_path=db_path, data_root=root, decisions_csvs=[decisions]
    )
    assert sorted(result["restored_exclusions"]) == ["t1-00001"]
    assert sorted(result["restored_recuts"]) == ["t1-00002"]

    state = _state(db_path, "t1-00001")
    assert state["excluded_id"] is None
    assert state["clip_path"] == "derived/clips-v2/table1/t1-00001.wav"
    assert (root / "derived/clips-v2/table1/t1-00001.wav").read_bytes() == original_clip_bytes
    assert not (root / "derived/clips-excluded/table1/t1-00001.wav").exists()

    recut = _state(db_path, "t1-00002")
    assert recut["algorithm_version"] == "constrained-dp-v2-full"
    assert (recut["start_ms"], recut["end_ms"]) == (0, 500)
    assert _sha((root / "derived/clips-v2/table1/t1-00002.wav").read_bytes()) == recut["clip_sha256"]
    assert not (root / "derived/nasal-cleaning/recut-backup/t1-00002.wav").exists()

    formal = (root / "derived/formal_corpus.csv").read_text(encoding="utf-8")
    assert "t1-00001," in formal and "t1-00002," in formal and "t1-00003," in formal
    manifest = (root / "derived/excluded_items.csv").read_text(encoding="utf-8")
    assert "t1-00001" not in manifest
    report = json.loads(
        (root / "derived/nasal-cleaning/nasal_repair_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["events"] == []

    # Undo again is a no-op.
    again = undo_nasal_clean(
        db_path=db_path, data_root=root, decisions_csvs=[decisions]
    )
    assert again["restored_exclusions"] == [] and again["restored_recuts"] == []


def test_undo_by_item_id(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [{"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
          "tier": "T2_mismatch", "verdict": "wrong_word"}],
    )
    apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=lambda _path: source,
    )
    result = undo_nasal_clean(
        db_path=db_path, data_root=root, item_ids=["t1-00001"]
    )
    assert result["restored_exclusions"] == ["t1-00001"]
    assert _state(db_path, "t1-00001")["excluded_id"] is None


def test_undo_refuses_non_nasal_exclusion(tmp_path):
    root, db_path, source = _seed(tmp_path)
    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO excluded_items (item_id, reason, kind, detail)
            VALUES ('t1-00003', 'qwen3_full_align', 'audio_word_mismatch', 'x')
            """
        )
        connection.execute(
            "UPDATE segments SET clip_path = 'derived/clips-excluded/table1/t1-00003.wav' "
            "WHERE item_id = 't1-00003'"
        )
    (root / "derived/clips-excluded/table1").mkdir(exist_ok=True)
    (root / "derived/clips-excluded/table1/t1-00003.wav").write_bytes(_wav_payload(500))
    manifest = (
        "item_id,table_kind,word_raw,pinyin_nfc,kinds,detail,old_clip_path,new_clip_path\n"
        "t1-00003,table1,本领,běnlǐng,audio_word_mismatch,x,"
        "derived/clips-v2/table1/t1-00003.wav,"
        "derived/clips-excluded/table1/t1-00003.wav\n"
    )
    (root / "derived/excluded_items.csv").write_text(manifest, encoding="utf-8")
    result = undo_nasal_clean(
        db_path=db_path, data_root=root, item_ids=["t1-00003"]
    )
    assert result["no_ops"] == ["t1-00003"]
    assert _state(db_path, "t1-00003")["excluded_id"] == "t1-00003"


def test_ok_and_skip_verdicts_are_noops(tmp_path):
    root, db_path, source = _seed(tmp_path)
    decisions = _decisions_csv(
        tmp_path,
        [
            {"item_id": "t1-00001", "word": "成人", "pinyin": "chéngrén",
             "tier": "T2_mismatch", "verdict": "ok"},
            {"item_id": "t1-00002", "word": "安全", "pinyin": "ānquán",
             "tier": "T3_shift", "verdict": "skip"},
        ],
    )
    summary = apply_nasal_decisions(
        db_path=db_path,
        data_root=root,
        decisions_csvs=[decisions],
        decoder=lambda _path: source,
    )
    assert summary["excluded"] == 0 and summary["recut"] == 0
    assert _state(db_path, "t1-00001")["excluded_id"] is None
    assert _state(db_path, "t1-00002")["excluded_id"] is None
