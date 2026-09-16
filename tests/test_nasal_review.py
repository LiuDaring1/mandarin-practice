"""Tests for the front/back-nasal listening review app."""

from __future__ import annotations

import hashlib
import sqlite3
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pth_corpus.db import connect_db, init_db
from pth_corpus.nasal_review import (
    DecisionStore,
    NasalReviewError,
    create_nasal_review_app,
    load_batch,
    validate_loopback_host,
)


def _write_wav(path: Path, *, duration_s: float = 0.5) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    samples = np.sin(
        2 * np.pi * 440.0 * np.arange(int(sample_rate * duration_s)) / sample_rate
    ) * 0.25
    pcm = np.rint(samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


BATCH_HEADER = (
    "item_id,table_kind,word,pinyin,syllable_count,finals,clip_path,"
    "clip_duration_ms,segment_confidence,has_front,has_back,whisper_text,"
    "whisper_text_freq,old_qwen3_asr,old_score,both_asr_agree,prev_word,"
    "next_word,tier,reason,qwen3_mismatch"
)


def _seed(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "data"
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    source_hash = _write_wav(root / "raw/audio/table1/001.wav", duration_s=2.0)
    clip_hash_1 = _write_wav(root / "derived/clips-v2/table1/t1-00001.wav", duration_s=0.5)
    clip_hash_2 = _write_wav(root / "derived/clips-v2/table1/t1-00002.wav", duration_s=0.5)
    with connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO source_pages (
                source_key, table_kind, page_no, url, expected_items,
                audio_path, audio_sha256
            ) VALUES ('t1-p001', 'table1', 1, 'https://fixture/t1-p001', 2, ?, ?)
            """,
            ("raw/audio/table1/001.wav", source_hash),
        )
        page_id = connection.execute(
            "SELECT id FROM source_pages WHERE source_key = 't1-p001'"
        ).fetchone()[0]
        for item_id, word, pinyin, seq, clip_hash in (
            ("t1-00001", "成人", "chéngrén", 1, clip_hash_1),
            ("t1-00002", "安全", "ānquán", 2, clip_hash_2),
        ):
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
                (item_id, f"derived/clips-v2/table1/{item_id}.wav", clip_hash),
            )
    batch_csv = tmp_path / "review_batch_01.csv"
    batch_csv.write_text(
        BATCH_HEADER
        + "\n"
        + "t1-00001,table1,成人,chéngrén,2,eng,derived/clips-v2/table1/t1-00001.wav,"
        "500,0.95,0,1,行人,1,,,1,前词,后词,T2_mismatch,高度相似但不完全一致,0\n"
        + "t1-00002,table1,安全,ānquán,2,an,derived/clips-v2/table1/t1-00002.wav,"
        "500,0.95,1,0,安全,1,,,0,前词,后词,OK,whisper与词完全一致,0\n",
        encoding="utf-8",
    )
    decisions_csv = tmp_path / "review" / "nasal_decisions_batch_01.csv"
    return root, db_path, batch_csv, decisions_csv


def _client(tmp_path: Path):
    root, db_path, batch_csv, decisions_csv = _seed(tmp_path)
    app = create_nasal_review_app(
        data_root=root,
        db_path=db_path,
        batch_csv=batch_csv,
        decisions_csv=decisions_csv,
        batch_label="batch_01",
    )
    return TestClient(app), root, decisions_csv


def test_validate_loopback_host():
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("localhost") == "localhost"
    try:
        validate_loopback_host("0.0.0.0")
    except NasalReviewError:
        pass
    else:
        raise AssertionError("non-loopback host must be rejected")


def test_load_batch_rejects_empty_and_missing_item_id(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text(BATCH_HEADER + "\n", encoding="utf-8")
    try:
        load_batch(empty)
    except NasalReviewError:
        pass
    else:
        raise AssertionError("empty batch must be rejected")
    bad = tmp_path / "bad.csv"
    bad.write_text(BATCH_HEADER + "\n,table1,x\n", encoding="utf-8")
    try:
        load_batch(bad)
    except NasalReviewError:
        pass
    else:
        raise AssertionError("row without item_id must be rejected")


def test_decision_store_upsert_delete_atomic(tmp_path):
    store = DecisionStore(tmp_path / "dec.csv")
    assert store.load() == {}
    store.upsert(
        {
            "item_id": "t1-00001",
            "word": "成人",
            "pinyin": "chéngrén",
            "tier": "T2_mismatch",
            "verdict": "wrong_word",
            "notes": "",
            "adjusted_start_ms": "",
            "adjusted_end_ms": "",
            "reviewed_at": "2026-08-13T00:00:00+00:00",
            "reviewer": "human",
        }
    )
    rows = store.load()
    assert rows["t1-00001"]["verdict"] == "wrong_word"
    store.upsert({**rows["t1-00001"], "verdict": "ok"})
    assert store.load()["t1-00001"]["verdict"] == "ok"
    assert store.delete("t1-00001") is True
    assert store.delete("t1-00001") is False
    assert store.load() == {}


def test_review_page_and_media(tmp_path):
    client, root, _decisions = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "成人" in page.text
    media = client.get("/media/t1-00001/clip")
    assert media.status_code == 200
    source = client.get("/media/t1-00001/source")
    assert source.status_code == 200


def test_post_decision_persists_and_validates(tmp_path):
    client, root, decisions_csv = _client(tmp_path)
    response = client.post(
        "/api/decision",
        json={"item_id": "t1-00001", "verdict": "wrong_word"},
    )
    assert response.status_code == 201
    assert response.json()["decision"]["verdict"] == "wrong_word"
    assert decisions_csv.is_file()
    listed = client.get("/api/decisions").json()
    assert listed["t1-00001"]["verdict"] == "wrong_word"
    # Restart the app over the same decisions file: decisions survive.
    bad = client.post(
        "/api/decision", json={"item_id": "t1-00001", "verdict": "bogus"}
    )
    assert bad.status_code == 422
    missing = client.post(
        "/api/decision", json={"item_id": "t9-99999", "verdict": "ok"}
    )
    assert missing.status_code == 404
    half_bounds = client.post(
        "/api/decision",
        json={
            "item_id": "t1-00001",
            "verdict": "shift",
            "adjusted_start_ms": 10,
        },
    )
    assert half_bounds.status_code == 422


def test_shift_decision_requires_bounds_within_raw(tmp_path):
    client, root, _decisions = _client(tmp_path)
    out_of_range = client.post(
        "/api/decision",
        json={
            "item_id": "t1-00001",
            "verdict": "shift",
            "adjusted_start_ms": 0,
            "adjusted_end_ms": 700,
        },
    )
    assert out_of_range.status_code == 422
    inside = client.post(
        "/api/decision",
        json={
            "item_id": "t1-00001",
            "verdict": "shift",
            "adjusted_start_ms": 10,
            "adjusted_end_ms": 490,
        },
    )
    assert inside.status_code == 201
    assert inside.json()["decision"]["adjusted_start_ms"] == "10"


def test_delete_decision(tmp_path):
    client, root, decisions_csv = _client(tmp_path)
    client.post(
        "/api/decision", json={"item_id": "t1-00001", "verdict": "wrong_word"}
    )
    response = client.delete("/api/decision/t1-00001")
    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert client.get("/api/decisions").json() == {}


def test_decisions_csv_single_source_of_truth(tmp_path):
    """A second app instance over the same CSV sees the first one's rows."""
    root, db_path, batch_csv, decisions_csv = _seed(tmp_path)
    app1 = create_nasal_review_app(
        data_root=root,
        db_path=db_path,
        batch_csv=batch_csv,
        decisions_csv=decisions_csv,
    )
    client1 = TestClient(app1)
    client1.post(
        "/api/decision", json={"item_id": "t1-00001", "verdict": "wrong_word"}
    )
    app2 = create_nasal_review_app(
        data_root=root,
        db_path=db_path,
        batch_csv=batch_csv,
        decisions_csv=decisions_csv,
    )
    client2 = TestClient(app2)
    listed = client2.get("/api/decisions").json()
    assert listed["t1-00001"]["verdict"] == "wrong_word"
