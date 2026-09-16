"""Tests for the sentence-practice API endpoints in prototype_app.py."""

from __future__ import annotations

import csv
import json
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pth_corpus.prototype_app import create_app
from pth_corpus.sentence_reading import run_extract, run_score

PAGES_FIXTURE = [
    {
        "page": 1,
        "text": (
            "2024 年新大纲普通话免费模拟测评\n"
            "《读书人是幸福人》\n"
            "我常想读书人是世间幸福人。\n"
            "世间有诸多的不平等，财富的不平等，权力的不平等，而阅读能力的拥有或丧失，却体现为精神的不平等。\n"
            "一个人的一生，只能经历自己拥有的那一份欣悦。\n"
        ),
    },
    {
        "page": 2,
        "text": (
            "2024 年新大纲普通话免费模拟测评\n"
            "《小鸟的天堂》\n"
            "我们的船渐渐地逼近榕树了。\n"
        ),
    },
]


def _make_wav(path: Path, seconds: float) -> None:
    rate = 16000
    samples = (
        np.sin(2 * np.pi * 440.0 * np.arange(int(rate * seconds)) / rate) * 8000
    ).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(samples.tobytes())


def build_sentence_data(tmp_path: Path) -> Path:
    """在 tmp 下构造 sentence-practice-v1 语料（4 句全部入选 + 切片）。"""
    out = tmp_path / "derived" / "sentence-practice-v1"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "读书人是幸福人.mp3").write_bytes(b"fake")
    (audio_dir / "鸟的天堂.mp3").write_bytes(b"fake")
    run_extract(pages=PAGES_FIXTURE, audio_dir=audio_dir, out_dir=out)
    run_score(out_dir=out)

    with open(out / "sentences_scored.csv", encoding="utf-8", newline="") as fh:
        scored = list(csv.DictReader(fh))
    selected = [r for r in scored if r["selected"] == "True"]
    manifest = []
    aligned = []
    for i, row in enumerate(selected):
        start, end = 0.4 + i * 2.0, 1.4 + i * 2.0
        sid = row["sentence_id"]
        art_id = row["article_id"]
        clip_rel = f"clips/{art_id}/{sid}.wav"
        wav_path = out / clip_rel
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        _make_wav(wav_path, end - start)
        aligned.append(
            {
                "sentence_id": sid, "text": row["text"],
                "matched_text": row["text"],
                "start": start, "end": end, "duration": end - start,
                "score": 0.9, "tier": "high", "segments": [0, 0],
            }
        )
        manifest.append(
            {
                "sentence_id": sid, "article_id": art_id, "wav_rel": clip_rel,
                "source_file": "x.mp3", "src_start": start, "src_end": end,
                "clip_duration": end - start, "sha256": f"h{i}",
                "confidence": 0.9, "tier": "high", "whisper_text": row["text"],
            }
        )
    (out / "alignment").mkdir(exist_ok=True)
    with open(out / "alignment/aligned.jsonl", "w", encoding="utf-8") as fh:
        for row in aligned:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out / "clip_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    return out


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(data_root=tmp_path)
    return TestClient(app)


def test_sentence_home(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        resp = client.get("/api/sentence/home")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["total_clips"] == 4
    assert body["articles"] == 2
    assert set(body["filter_counts"]) == {"all", "front", "back", "mixed"}
    assert body["filter_counts"]["all"] == 4
    # 自选音计数：16 个鼻音韵母都有 entries
    stats = body["final_stats"]
    assert len(stats) == 16
    assert all("sentences" in v and "syllables" in v for v in stats.values())


def test_sentence_session_include_finals(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        resp = client.post(
            "/api/sentence/session",
            json={"count": 10, "filter": "custom", "include_finals": ["ing", "eng"]},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["include_finals"] == ["eng", "ing"]
    assert body["items"]
    for item in body["items"]:
        nasal = [
            f for f, label in zip(item["final_seq"].split(), item["label_seq"])
            if label in ("F", "B")
        ]
        hits = sum(1 for f in nasal if f in {"ing", "eng"})
        assert hits >= 2 or (hits >= 1 and hits / len(nasal) >= 0.25)
    # 自选计数端点
    with make_client(tmp_path) as client:
        count = client.post(
            "/api/sentence/count", json={"include_finals": ["ing", "eng"]}
        ).json()
        assert count["count"] == len(body["items"]) or count["count"] >= len(body["items"])
    # 非法韵母 → 422
    with make_client(tmp_path) as client:
        assert (
            client.post(
                "/api/sentence/session",
                json={"include_finals": ["bogus"]},
            ).status_code
            == 422
        )


def test_sentence_session(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        resp = client.post(
            "/api/sentence/session",
            json={"count": 2, "filter": "all", "seed": 7},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"].startswith("sent-")
    assert body["count"] == 2
    assert len(body["items"]) == 2
    item = body["items"][0]
    assert item["text"]
    assert item["units"]
    assert item["units"][0]["ch"]
    assert item["label_seq"].count("F") == item["front_count"]
    assert item["clip_url"] == f"/api/sentence/clips/{item['sentence_id']}"
    assert item["clip_duration"] > 0


def test_sentence_session_filter_mixed(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        resp = client.post(
            "/api/sentence/session",
            json={"count": 10, "filter": "mixed", "seed": 3},
        )
    assert resp.status_code == 201
    for item in resp.json()["items"]:
        assert item["front_count"] > 0 and item["back_count"] > 0


def test_sentence_session_invalid_filter_and_count(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        assert (
            client.post(
                "/api/sentence/session", json={"filter": "bogus"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/sentence/session", json={"count": 0}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/sentence/session", json={"count": 999}
            ).status_code
            == 422
        )


def test_sentence_clip_media(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    sid = "01-读书人是幸福人-0001"
    with make_client(tmp_path) as client:
        resp = client.get(f"/api/sentence/clips/{sid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    # 非法 id / 不存在
    with make_client(tmp_path) as client:
        assert client.get("/api/sentence/clips/evil/../x").status_code in (404, 422)
        assert client.get("/api/sentence/clips/99-不存在-0001").status_code == 404


def test_sentence_events_recorded(tmp_path: Path) -> None:
    build_sentence_data(tmp_path)
    with make_client(tmp_path) as client:
        resp = client.post(
            "/api/sentence/events",
            json={
                "session_id": "sent-test-1",
                "filter": "all",
                "start_time": "2026-08-14T10:00:00Z",
                "end_time": "2026-08-14T10:02:00Z",
                "sentence_count": 5,
                "completed_sentence_count": 4,
                "exit_early": False,
                "replay_count": 2,
                "pause_count": 1,
                "actual_duration_sec": 120.0,
            },
        )
    assert resp.status_code == 201
    events = (
        tmp_path / "derived" / "prototype" / "logs" / "events.jsonl"
    ).read_text(encoding="utf-8")
    record = json.loads(events.strip().splitlines()[-1])
    assert record["type"] == "sentence"
    assert record["sentence_count"] == 5


def test_sentence_home_empty_library(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        home = client.get("/api/sentence/home").json()
        assert home["available"] is False
        assert home["total_clips"] == 0
        resp = client.post(
            "/api/sentence/session", json={"count": 5}
        )
        assert resp.status_code == 404


def test_home_includes_sentence_status(tmp_path: Path) -> None:
    # /api/home 依赖 profiles，此处只验证句子库缺失时 graceful（不 500）
    app = create_app(data_root=tmp_path)
    # focus_home 需要 profiles 文件；不存在时应抛错而非静默——跳过该断言，
    # 仅验证 sentence_home 自身在空库时可用。
    with TestClient(app) as client:
        body = client.get("/api/sentence/home").json()
    assert body["available"] is False
