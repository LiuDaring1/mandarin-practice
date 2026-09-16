"""Tests for the sentence-practice listening review app (sentence_review.py)."""

from __future__ import annotations

import csv
import json
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pth_corpus.sentence_review import create_app


def _make_wav(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    samples = (
        np.sin(2 * np.pi * 440.0 * np.arange(int(rate * seconds)) / rate) * 8000
    ).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(samples.tobytes())


def build_review_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """构造最小 sentence-practice-v1 数据 + 听检清单 CSV。"""
    sp = tmp_path / "derived" / "sentence-practice-v1"
    sp.mkdir(parents=True)
    (sp / "alignment").mkdir()
    # 两句：一句有切片，一句仅有对齐区间（走预览生成需要源音频，
    # 测试里跳过音频请求，只验证 /api/items 与判定落盘）
    articles = [
        {"article_id": "01-测试文章", "page": 1, "title": "测试文章",
         "audio_file": "测试文章.mp3", "has_audio": True},
    ]
    with open(sp / "articles.jsonl", "w", encoding="utf-8") as fh:
        for row in articles:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    scored = [
        {"sentence_id": "01-测试文章-0001", "article_id": "01-测试文章",
         "page": "1", "seq": "1", "text": "读书人是幸福人",
         "char_count": "7", "pinyin_seq": "dú shū rén shì xìng fú rén",
         "label_seq": "OOFOBFO", "front_count": "2", "back_count": "1",
         "nasal_density": "0.43", "selected": "True"},
        {"sentence_id": "01-测试文章-0002", "article_id": "01-测试文章",
         "page": "1", "seq": "2", "text": "我们的船渐渐逼近榕树",
         "char_count": "10", "pinyin_seq": "wǒ men de chuán jiàn jiàn bī jìn róng shù",
         "label_seq": "OOOOOOFFBO", "front_count": "3", "back_count": "1",
         "nasal_density": "0.40", "selected": "True"},
    ]
    with open(sp / "sentences_scored.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(scored[0].keys()))
        writer.writeheader()
        writer.writerows(scored)
    _make_wav(sp / "clips/01-测试文章/01-测试文章-0001.wav", 2.0)
    with open(sp / "clip_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(
            [{
                "sentence_id": "01-测试文章-0001", "article_id": "01-测试文章",
                "wav_rel": "clips/01-测试文章/01-测试文章-0001.wav",
                "source_file": "测试文章.mp3", "src_start": 0.5, "src_end": 2.5,
                "clip_duration": 2.0, "sha256": "h", "confidence": 0.9,
                "tier": "high", "whisper_text": "读书人是幸福人",
            }],
            fh, ensure_ascii=False,
        )
    with open(sp / "alignment/aligned.jsonl", "w", encoding="utf-8") as fh:
        for row in [
            {"sentence_id": "01-测试文章-0001", "text": "读书人是幸福人",
             "matched_text": "读书人是幸福人", "start": 0.5, "end": 2.0,
             "score": 0.95, "tier": "high"},
            {"sentence_id": "01-测试文章-0002", "text": "我们的船渐渐逼近榕树",
             "matched_text": "我们的船渐渐逼近榕树", "start": 2.5, "end": 5.0,
             "score": 0.55, "tier": "mid"},
        ]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    checklist = tmp_path / "checklist.csv"
    with open(checklist, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sentence_id", "wav_rel", "text", "note"])
        writer.writerow(["01-测试文章-0001", "clips/x.wav", "读书人是幸福人", ""])
        writer.writerow(["01-测试文章-0002", "", "我们的船渐渐逼近榕树", "低置信复核"])
    return checklist, sp


def make_client(tmp_path: Path, checklist: Path) -> TestClient:
    decisions = tmp_path / "review" / "sentence_decisions_checklist.csv"
    app = create_app(
        data_root=tmp_path,
        batch_csv=checklist,
        decisions_csv=decisions,
        batch_label="checklist",
        audio_dir=tmp_path / "audio",
    )
    return TestClient(app)


def test_items_and_context(tmp_path: Path) -> None:
    checklist, sp = build_review_fixture(tmp_path)
    with make_client(tmp_path, checklist) as client:
        resp = client.get("/api/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["judged"] == 0
    items = {r["sentence_id"]: r for r in body["items"]}
    first = items["01-测试文章-0001"]
    assert first["article_title"] == "测试文章"
    assert first["units"][0] == {"ch": "读", "py": "dú", "label": "O"}
    assert first["has_clip"] is True
    assert first["tier"] == "high"
    second = items["01-测试文章-0002"]
    assert second["has_clip"] is False
    assert second["note"] == "低置信复核"
    assert second["matched_text"] == "我们的船渐渐逼近榕树"


def test_decision_roundtrip_and_resume(tmp_path: Path) -> None:
    checklist, sp = build_review_fixture(tmp_path)
    decisions = tmp_path / "review" / "sentence_decisions_checklist.csv"
    with make_client(tmp_path, checklist) as client:
        resp = client.post(
            "/api/decisions",
            json={"sentence_id": "01-测试文章-0001", "verdict": "ok",
                  "notes": "干净"},
        )
        assert resp.status_code == 201
        # 重开 app（模拟刷新）：已判状态持久化
        app2 = create_app(
            data_root=tmp_path, batch_csv=checklist,
            decisions_csv=decisions, batch_label="checklist",
            audio_dir=tmp_path / "audio",
        )
        client2 = TestClient(app2)
        body = client2.get("/api/items").json()
        assert body["judged"] == 1
        assert body["counts"]["ok"] == 1
        items = {r["sentence_id"]: r for r in body["items"]}
        assert items["01-测试文章-0001"]["verdict"] == "ok"
        assert items["01-测试文章-0001"]["notes"] == "干净"
        # 撤销
        resp = client2.delete("/api/decisions/01-测试文章-0001")
        assert resp.status_code == 200
        assert client2.get("/api/items").json()["judged"] == 0
        assert client2.delete("/api/decisions/01-测试文章-0001").status_code == 404


def test_decision_invalid_verdict(tmp_path: Path) -> None:
    checklist, sp = build_review_fixture(tmp_path)
    with make_client(tmp_path, checklist) as client:
        assert (
            client.post(
                "/api/decisions",
                json={"sentence_id": "01-测试文章-0001", "verdict": "bogus"},
            ).status_code
            == 422
        )


def test_audio_route(tmp_path: Path) -> None:
    checklist, sp = build_review_fixture(tmp_path)
    with make_client(tmp_path, checklist) as client:
        resp = client.get("/api/audio/01-测试文章-0001")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        # 无切片且无源音频 → 404
        assert client.get("/api/audio/01-测试文章-0002").status_code == 404
        # 越界 id → 404
        assert client.get("/api/audio/../../etc/passwd").status_code == 404


def test_index_page(tmp_path: Path) -> None:
    checklist, sp = build_review_fixture(tmp_path)
    with make_client(tmp_path, checklist) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "人耳听检" in resp.text
    assert "checklist" in resp.text
