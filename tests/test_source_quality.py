from __future__ import annotations

import json
import sqlite3
import wave
from pathlib import Path

import numpy as np

from pth_corpus.db import connect_db, init_db
from pth_corpus.source_quality import (
    check_audio_tone,
    check_pinyin_lexicon,
    normalize_db_pinyin,
    run_source_quality,
    single_syllable_info,
    tone_contour,
)


def _write_tone_wav(path: Path, tone: int, *, duration_s: float = 0.6) -> None:
    """Synthesize a clean single syllable with the requested tone contour."""

    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    count = int(sample_rate * duration_s)
    time = np.arange(count) / sample_rate
    if tone == 1:
        frequency = np.full(count, 180.0)
    elif tone == 2:
        frequency = np.linspace(120.0, 195.0, count)
    elif tone == 3:
        half = count // 2
        frequency = np.concatenate(
            [np.linspace(120.0, 95.0, half), np.linspace(95.0, 150.0, count - half)]
        )
    else:
        frequency = np.linspace(230.0, 90.0, count)
    phase = 2 * np.pi * np.cumsum(frequency) / sample_rate
    samples = np.rint(0.3 * np.sin(phase) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


def _seed_db(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "data"
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    clips = {
        "t1-00001": root / "derived/clips/table1/t1-00001.wav",
        "t1-00002": root / "derived/clips/table1/t1-00002.wav",
        "t1-00003": root / "derived/clips/table1/t1-00003.wav",
        "t1-00004": root / "derived/clips/table1/t1-00004.wav",
    }
    _write_tone_wav(clips["t1-00001"], 1)  # 熬 áo but audio is flat T1
    _write_tone_wav(clips["t1-00002"], 1)  # 炮 pāo (lexicon mismatch)
    _write_tone_wav(clips["t1-00003"], 4)  # 艾 ài with falling T4 audio
    _write_tone_wav(clips["t1-00004"], 3)  # 板 bǎn with dipping T3 audio
    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO source_pages
                (source_key, table_kind, page_no, url, expected_items,
                 audio_path, audio_sha256, fetch_status)
            VALUES ('t1-p001', 'table1', 1, 'http://fixture/t1', 4,
                    'raw/audio/table1/001.wav', 'x', 'fetched')
            """
        )
        page_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        words = {
            "t1-00001": ("熬", "áo"),
            "t1-00002": ("炮", "pāo"),
            "t1-00003": ("艾", "ài"),
            "t1-00004": ("板", "bǎn"),
        }
        for position, (item_id, (word, pinyin)) in enumerate(words.items(), start=1):
            connection.execute(
                """
                INSERT INTO entries
                    (item_id, source_page_id, table_kind, page_position, global_seq,
                     word_raw, pinyin_raw, pinyin_nfc)
                VALUES (?, ?, 'table1', ?, ?, ?, ?, ?)
                """,
                (item_id, page_id, position, position, word, pinyin, pinyin),
            )
            connection.execute(
                """
                INSERT INTO segments
                    (item_id, clip_path, clip_sha256, algorithm_version,
                     confidence, start_ms, end_ms)
                VALUES (?, ?, 'abc', 'test', 0.9, 0, 600)
                """,
                (item_id, f"derived/clips/table1/{item_id}.wav"),
            )
    return db_path, root


def test_normalize_db_pinyin_variants():
    assert normalize_db_pinyin("bái•tiān") == ([("bai", 2), ("tian", 1)], False)
    assert normalize_db_pinyin("bàr") == ([("ba", 4)], True)
    assert normalize_db_pinyin("bǎméner") == ([("ba", 3), ("men", 2)], True)
    assert normalize_db_pinyin("bāzhanɡ") == ([("ba", 1), ("zhang", None)], False)
    assert single_syllable_info("áo") == ("ao", 2)
    assert single_syllable_info("bàr") == (None, None)


def test_pinyin_lexicon_check():
    assert check_pinyin_lexicon("炮", "pāo")["status"] == "mismatch"
    assert check_pinyin_lexicon("炮", "pào")["status"] == "ok"
    assert check_pinyin_lexicon("熬", "áo")["status"] == "ok"
    assert check_pinyin_lexicon("艾", "ài")["status"] == "ok"
    assert check_pinyin_lexicon("把儿", "bàr")["status"] == "ok"
    assert check_pinyin_lexicon("把门儿", "bǎméner")["status"] == "ok"
    assert check_pinyin_lexicon("白天", "bái•tiān")["status"] == "ok"
    assert check_pinyin_lexicon("巴掌", "bāzhanɡ")["status"] == "ok"
    assert check_pinyin_lexicon("把子", "bǎzi")["status"] == "ok"
    assert check_pinyin_lexicon("儿", "ér")["status"] == "ok"
    assert check_pinyin_lexicon("一般", "yībān")["status"] == "ok"
    assert check_pinyin_lexicon("不要", "bùyào")["status"] == "ok"
    assert check_pinyin_lexicon("老虎", "ǎohǔ")["status"] == "mismatch"
    assert check_pinyin_lexicon("师长", "zhīzhǎng")["status"] == "mismatch"
    assert check_pinyin_lexicon("把子", "bàzǐ")["status"] == "context_mismatch"
    assert check_pinyin_lexicon("安分", "ānfēn")["status"] == "context_mismatch"


def test_tone_contour_classification(tmp_path):
    for tone in (1, 2, 3, 4):
        path = tmp_path / f"tone{tone}.wav"
        _write_tone_wav(path, tone)
        result = tone_contour(path)
        assert result["confident"] is True, (tone, result)
        assert result["tone"] == tone, (tone, result)


def test_audio_tone_check_matches_synthetic_clips(tmp_path):
    path = tmp_path / "t2.wav"
    _write_tone_wav(path, 2)
    ok = check_audio_tone("áo", path)
    assert ok["status"] == "ok"
    bad = check_audio_tone("āo", path)
    assert bad["status"] == "mismatch"
    assert bad["expected_tone"] == 1 and bad["tone"] == 2


def test_run_source_quality_flags_and_never_writes_db(tmp_path):
    db_path, root = _seed_db(tmp_path)
    report_path = root / "derived/source_quality_report.json"
    before = {
        item_id: (word, pinyin)
        for item_id, word, pinyin in sqlite3.connect(db_path).execute(
            "SELECT item_id, word_raw, pinyin_nfc FROM entries ORDER BY item_id"
        ).fetchall()
    }
    report = run_source_quality(db_path, root, out_path="derived/source_quality_report.json")
    assert report["checked_items"] == 4
    kinds = {(flag["item_id"], flag["kind"]) for flag in report["flags"]}
    assert ("t1-00001", "audio_tone_mismatch") in kinds
    assert ("t1-00002", "pinyin_mismatch") in kinds
    assert ("t1-00003", "audio_tone_mismatch") not in kinds
    assert ("t1-00004", "audio_tone_mismatch") not in kinds
    assert report_path.is_file()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["stats"]["flag_count"] == 2
    after = {
        item_id: (word, pinyin)
        for item_id, word, pinyin in sqlite3.connect(db_path).execute(
            "SELECT item_id, word_raw, pinyin_nfc FROM entries ORDER BY item_id"
        ).fetchall()
    }
    assert after == before
