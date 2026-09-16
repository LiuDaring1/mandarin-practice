from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pth_corpus.db import connect_db, init_db
from pth_corpus.review_app import create_app, validate_loopback_host


def _write_wav(path: Path, *, duration_s: float = 1.0, frequency: float = 440.0) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    samples = np.sin(
        2 * np.pi * frequency * np.arange(int(sample_rate * duration_s)) / sample_rate
    ) * 0.25
    pcm = np.rint(samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_review_db(tmp_path: Path, *, count: int = 200) -> tuple[Path, Path]:
    root = tmp_path / "data"
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    hashes = {
        "table1": _write_wav(root / "raw/audio/table1/001.wav", frequency=440),
        "table2": _write_wav(root / "raw/audio/table2/001.wav", frequency=660),
    }
    clip_hash = _write_wav(root / "derived/clips/table1/t1-00001.wav", duration_s=0.4)
    root.joinpath("derived/clips/table2").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        root / "derived/clips/table1/t1-00001.wav",
        root / "derived/clips/table2/t2-00001.wav",
    )
    with connect_db(db_path) as connection:
        page_ids: dict[str, int] = {}
        for number, kind in ((1, "table1"), (2, "table2")):
            connection.execute(
                """
                INSERT INTO source_pages
                    (source_key, table_kind, page_no, url, expected_items,
                     audio_path, audio_sha256)
                VALUES (?, ?, 1, ?, 100, ?, ?)
                """,
                (
                    f"t{number}-p001",
                    kind,
                    f"http://fixture/t{number}",
                    f"raw/audio/{kind}/001.wav",
                    hashes[kind],
                ),
            )
            page_ids[kind] = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        entries = []
        for number, kind in ((1, "table1"), (2, "table2")):
            for position in range(1, count // 2 + 1):
                item_id = f"t{number}-{position:05d}"
                entries.append(
                    (
                        item_id,
                        page_ids[kind],
                        kind,
                        position,
                        # Real pilot tables each restart global_seq at one;
                        # queue ordering is table1 then table2.
                        position,
                        f"词{position}",
                        f"ci{position}",
                        f"ci{position}",
                    )
                )
        connection.executemany(
            """
            INSERT INTO entries
                (item_id, source_page_id, table_kind, page_position, global_seq,
                 word_raw, pinyin_raw, pinyin_nfc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            entries,
        )
        for number, kind in ((1, "table1"), (2, "table2")):
            for position in range(1, count // 2 + 1):
                item_id = f"t{number}-{position:05d}"
                path = (
                    "derived/clips/table1/t1-00001.wav"
                    if item_id == "t1-00001"
                    else "derived/clips/table2/t2-00001.wav"
                )
                digest = clip_hash
                connection.execute(
                    """
                    INSERT INTO segments
                        (item_id, clip_path, clip_sha256, algorithm_version,
                         confidence, start_ms, end_ms, start_ms_raw, end_ms_raw)
                    VALUES (?, ?, ?, 'test-v1', ?, 200, 600, 100, 900)
                    """,
                    (item_id, path, digest, 0.4 if position == 1 else 0.9),
                )
    return db_path, root


def test_health_items_filters_and_html_controls(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["entries"] == 200
    listing = client.get("/api/items?limit=5")
    assert listing.status_code == 200
    assert listing.json()["count"] == 200
    assert len(listing.json()["items"]) == 5
    assert [item["item_id"] for item in listing.json()["items"]] == [
        "t1-00001",
        "t1-00002",
        "t1-00003",
        "t1-00004",
        "t1-00005",
    ]
    assert client.get("/api/items?status=approved").json()["count"] == 0
    assert client.get("/api/items?low_confidence=true").json()["count"] == 2
    assert listing.json()["items"][0]["status"] == "pending"
    assert client.get("/api/items/t1-00001").json()["effective_status"] == "pending"
    html = client.get("/").text
    for marker in (
        "canvas",
        "A 通过",
        "R 退回",
        "N 需复核",
        "待审核",
        "已通过",
        "已退回",
        "审批已失效",
        "切分边界置信度",
        "边界需复核",
        "自动切分边界的可靠程度",
        "不评价发音、字音或普通话是否正确",
        "切到前音=含上一条声音",
        "切到后音=含下一条声音",
        "残留广告",
        "文本/音频错配",
        "音质问题",
        "仅在退回或需复核时选择",
        "ArrowLeft",
        "previewBoundary",
        "status-filter",
        "issue-code",
        "cut_to_previous",
        "text_audio_mismatch",
        "notes",
        "issue_code",
        "previous-info",
        "next-info",
    ):
        assert marker in html


def test_detail_media_waveform_and_adjacency(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    detail = client.get("/api/items/t1-00001")
    assert detail.status_code == 200
    value = detail.json()
    assert value["word_raw"] == "词1"
    assert value["low_confidence"] is True
    assert value["previous"] is None
    assert value["next"]["item_id"] == "t1-00002"
    assert client.get("/media/items/t1-00001/clip").status_code == 200
    source = client.get("/media/items/t1-00001/source")
    assert source.status_code == 200 and source.headers["content-type"].startswith("audio/")
    assert "content-disposition" not in client.get("/media/items/t1-00001/clip").headers
    peaks = client.get("/api/items/t1-00001/waveform?asset=clip&bins=20")
    assert peaks.status_code == 200
    assert 1 <= len(peaks.json()["peaks"]) <= 20

    boundary = client.get("/api/items/t1-00100")
    assert boundary.status_code == 200
    assert boundary.json()["previous"]["item_id"] == "t1-00099"
    assert boundary.json()["next"]["item_id"] == "t2-00001"
    start = client.get("/api/items/t1-00001")
    assert start.json()["previous"] is None
    end = client.get("/api/items/t2-00100")
    assert end.json()["next"] is None


def test_review_revision_bounds_hash_stale_and_restart_persistence(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    missing_issue = client.post(
        "/api/items/t1-00001/review",
        json={"status": "rejected", "notes": "needs a reason"},
    )
    assert missing_issue.status_code == 422
    unknown_issue = client.post(
        "/api/items/t1-00001/review",
        json={"status": "rejected", "issue_code": "unknown_code"},
    )
    assert unknown_issue.status_code == 422
    bad = client.post(
        "/api/items/t1-00001/review",
        json={"status": "approved", "adjusted_start_ms": 50, "adjusted_end_ms": 700},
    )
    assert bad.status_code == 422
    first = client.post(
        "/api/items/t1-00001/review",
        json={"status": "approved", "reviewer": "alice", "notes": "ok"},
    )
    assert first.status_code == 201
    assert first.json()["review"]["revision"] == 1
    assert first.json()["review"]["status"] == "approved"
    second = client.post(
        "/api/items/t1-00001/review",
        json={
            "status": "needs_review",
            "issue_code": "cut_to_previous",
            "notes": "边界落到了前一个词",
            "adjusted_start_ms": 120,
            "adjusted_end_ms": 580,
        },
    )
    assert second.status_code == 201
    assert second.json()["review"]["revision"] == 2
    history = client.get("/api/items/t1-00001/reviews").json()["reviews"]
    assert [item["revision"] for item in history] == [1, 2]
    assert history[0]["issue_code"] is None
    assert history[0]["notes"] == "ok"
    assert history[1]["issue_code"] == "cut_to_previous"
    assert history[1]["notes"] == "边界落到了前一个词"
    with connect_db(db_path) as connection:
        before = connection.execute(
            "SELECT start_ms, end_ms, clip_sha256 FROM segments WHERE item_id='t1-00001'"
        ).fetchone()
        connection.execute(
            "UPDATE segments SET clip_sha256 = 'changed' WHERE item_id='t1-00001'"
        )
    detail = client.get("/api/items/t1-00001").json()
    assert detail["effective_review"] == {"status": "pending", "stale": True, "latest": history[-1]}
    with connect_db(db_path) as connection:
        after = connection.execute(
            "SELECT start_ms, end_ms FROM segments WHERE item_id='t1-00001'"
        ).fetchone()
    assert tuple(after) == tuple(before[:2])
    restarted = TestClient(create_app(db_path, root))
    assert len(restarted.get("/api/items/t1-00001/review-history").json()["reviews"]) == 2


def test_display_boundaries_restore_adjusted_then_fall_back_when_stale(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    with connect_db(db_path) as connection:
        connection.execute(
            """
            UPDATE segments
            SET start_ms = 4530, end_ms = 5140,
                start_ms_raw = 3500, end_ms_raw = 6200
            WHERE item_id = 't1-00002'
            """
        )
    client = TestClient(create_app(db_path, root))
    posted = client.post(
        "/api/items/t1-00002/review",
        json={
            "status": "needs_review",
            "issue_code": "cut_to_previous",
            "notes": "reviewed boundary",
            "adjusted_start_ms": 4510,
            "adjusted_end_ms": 5160,
        },
    )
    assert posted.status_code == 201
    current = client.get("/api/items/t1-00002").json()
    assert current["display_start_ms"] == 4510
    assert current["display_end_ms"] == 5160
    assert current["stale"] is False
    with connect_db(db_path) as connection:
        connection.execute(
            "UPDATE segments SET clip_sha256 = 'changed' WHERE item_id='t1-00002'"
        )
    stale = client.get("/api/items/t1-00002").json()
    assert stale["stale"] is True
    assert stale["effective_status"] == "pending"
    assert stale["display_start_ms"] == 4530
    assert stale["display_end_ms"] == 5140


def test_media_path_escape_and_host_rejection(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    outside = tmp_path / "outside.wav"
    _write_wav(outside)
    with connect_db(db_path) as connection:
        connection.execute(
            "UPDATE segments SET clip_path = ? WHERE item_id='t1-00002'",
            ("../outside.wav",),
        )
    client = TestClient(create_app(db_path, root))
    assert client.get("/media/items/t1-00002/clip").status_code in {400, 404}
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("::1") == "::1"
    try:
        validate_loopback_host("0.0.0.0")
    except Exception as exc:
        assert "loopback" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-loopback host must be rejected")


def test_media_urls_versioned_and_old_url_rejected_after_hash_change(tmp_path):
    """Same-browser-profile cache regression for v1 -> v2 switching.

    The browser caches the old versioned URL; after the clip hash changes the
    detail API returns a *different* URL, the new URL serves the new bytes,
    and the old cached URL returns 409 instead of stale bytes.
    """

    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    with connect_db(db_path) as connection:
        v1 = connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id='t1-00001'"
        ).fetchone()[0]
        source_v1 = connection.execute(
            "SELECT audio_sha256 FROM source_pages WHERE table_kind='table1'"
        ).fetchone()[0]
    detail = client.get("/api/items/t1-00001").json()
    clip_url_v1 = detail["clip_media_url"]
    source_url = detail["source_media_url"]
    assert clip_url_v1 == f"/media/items/t1-00001/clip?v={v1}"
    assert source_url == f"/media/items/t1-00001/source?v={source_v1}"
    served_v1 = client.get(clip_url_v1)
    assert served_v1.status_code == 200
    assert hashlib.sha256(served_v1.content).hexdigest() == v1
    assert served_v1.headers["cache-control"] == "no-store"

    # Simulate the v1 -> v2 switch: new bytes on disk, new hash in SQLite.
    v2 = _write_wav(
        root / "derived/clips/table1/t1-00001.wav", duration_s=0.6, frequency=880
    )
    with connect_db(db_path) as connection:
        connection.execute(
            "UPDATE segments SET clip_sha256 = ? WHERE item_id='t1-00001'", (v2,)
        )
    refreshed = client.get("/api/items/t1-00001").json()
    clip_url_v2 = refreshed["clip_media_url"]
    assert clip_url_v2 != clip_url_v1
    assert clip_url_v2 == f"/media/items/t1-00001/clip?v={v2}"
    stale = client.get(clip_url_v1)
    assert stale.status_code == 409
    current = client.get(clip_url_v2)
    assert current.status_code == 200
    assert hashlib.sha256(current.content).hexdigest() == v2


def test_waveform_url_version_follows_clip_hash(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    with connect_db(db_path) as connection:
        v1 = connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id='t1-00001'"
        ).fetchone()[0]
    url_v1 = f"/api/items/t1-00001/waveform?asset=clip&v={v1}"
    assert client.get(url_v1).status_code == 200
    v2 = _write_wav(
        root / "derived/clips/table1/t1-00001.wav", duration_s=0.6, frequency=880
    )
    with connect_db(db_path) as connection:
        connection.execute(
            "UPDATE segments SET clip_sha256 = ? WHERE item_id='t1-00001'", (v2,)
        )
    assert client.get(url_v1).status_code == 409
    url_v2 = f"/api/items/t1-00001/waveform?asset=clip&v={v2}"
    response = client.get(url_v2)
    assert response.status_code == 200
    assert response.json()["media_version"] == v2


def test_no_store_cache_headers_on_page_api_waveform_and_media(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    detail = client.get("/api/items/t1-00001").json()
    clip_hash = detail["segment"]["clip_sha256"]
    for url in (
        "/",
        "/api/health",
        "/api/items/t1-00001",
        detail["clip_media_url"],
        detail["source_media_url"],
        f"/api/items/t1-00001/waveform?asset=clip&v={clip_hash}",
    ):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "no-store", url


def test_served_media_body_sha_matches_db_for_clip_and_source(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    with connect_db(db_path) as connection:
        clip_hash = connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id='t1-00001'"
        ).fetchone()[0]
        source_hash = connection.execute(
            "SELECT audio_sha256 FROM source_pages WHERE table_kind='table1'"
        ).fetchone()[0]
    detail = client.get("/api/items/t1-00001").json()
    clip_body = client.get(detail["clip_media_url"]).content
    source_body = client.get(detail["source_media_url"]).content
    assert hashlib.sha256(clip_body).hexdigest() == clip_hash
    assert hashlib.sha256(source_body).hexdigest() == source_hash


def test_unversioned_media_url_still_serves_current_content(tmp_path):
    """Old bookmark/manual URL keeps working and cannot return stale bytes."""

    db_path, root = _seed_review_db(tmp_path)
    client = TestClient(create_app(db_path, root))
    with connect_db(db_path) as connection:
        clip_hash = connection.execute(
            "SELECT clip_sha256 FROM segments WHERE item_id='t1-00001'"
        ).fetchone()[0]
    response = client.get("/media/items/t1-00001/clip")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == clip_hash
    assert response.headers["cache-control"] == "no-store"


def test_excluded_items_hidden_from_review_list_and_detail(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    with connect_db(db_path) as connection:
        connection.execute(
            "INSERT INTO excluded_items (item_id, reason, kind) VALUES (?, 'test', 'test')",
            ("t1-00001",),
        )
    client = TestClient(create_app(db_path, root))
    listing = client.get("/api/items?limit=200").json()
    assert len(listing["items"]) == 199
    assert all(item["item_id"] != "t1-00001" for item in listing["items"])
    assert client.get("/api/items/t1-00001").status_code == 404
    assert client.get("/api/items/t1-00002").status_code == 200


def test_sample_page_renders_shortcut_workflow(tmp_path):
    db_path, root = _seed_review_db(tmp_path)
    sample_dir = root / "review"
    client = TestClient(create_app(db_path, root))
    assert client.get("/sample").status_code == 404  # nothing until CSV exists
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "sample_200_test.csv").write_text(
        "item_id\nt1-00001\nt1-00002\n", encoding="utf-8"
    )
    response = client.get("/sample")
    assert response.status_code == 200
    html_text = response.text
    assert "t1-00001" in html_text and "t1-00002" in html_text
    for marker in ("A 没问题", "S 有问题", "导出标注", "ArrowLeft", "ArrowRight", "keydown", "clip_media_url"):
        assert marker in html_text
    import re
    match = re.search(r"const ITEMS=(\[.*?\]);", html_text, re.S)
    assert match is not None
    items = json.loads(match.group(1))
    assert len(items) == 2
    assert all(item["clip_media_url"] for item in items)
    assert "const BATCH='sample_200_test';" in html_text
