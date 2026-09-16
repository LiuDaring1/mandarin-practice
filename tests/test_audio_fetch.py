from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import httpx
import pytest

from pth_corpus.audio_fetch import (
    AudioFetchError,
    AudioMetadata,
    fetch_pilot_audio,
    probe_mp3,
)
from pth_corpus.db import connect_db, init_db


FAKE_MP3 = b"ID3" + bytes(range(256)) * 32
METADATA = AudioMetadata(
    codec="mp3", duration_ms=1234, sample_rate=16000, channels=2, bitrate=48000
)


def _seed_db(tmp_path: Path, *, audio_urls: tuple[str, str] | None = None):
    db_path = tmp_path / "corpus.sqlite3"
    data_root = tmp_path / "data"
    init_db(db_path)
    urls = audio_urls or (
        "http://fixture.test/audio/table1/001.mp3",
        "http://fixture.test/audio/table2/001.mp3",
    )
    with connect_db(db_path) as connection:
        for key, kind, page_url, audio_url in (
            ("t1-p001", "table1", "http://fixture.test/t1/01.html", urls[0]),
            ("t2-p001", "table2", "http://fixture.test/t2/001.html", urls[1]),
        ):
            connection.execute(
                "INSERT INTO source_pages "
                "(source_key, table_kind, page_no, url, audio_url, fetch_status) "
                "VALUES (?, ?, 1, ?, ?, 'fetched')",
                (key, kind, page_url, audio_url),
            )
    return db_path, data_root


def _run(
    db_path: Path,
    data_root: Path,
    handler,
    *,
    probe=lambda _path: METADATA,
    retries=0,
):
    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        return fetch_pilot_audio(
            db_path=db_path,
            data_root=data_root,
            timeout=1,
            retries=retries,
            client=client,
            sleep=lambda _seconds: None,
            probe=probe,
        )


def _body_response(request: httpx.Request, body: bytes = FAKE_MP3):
    return httpx.Response(200, content=body, request=request)


def test_audio_200_download_hash_metadata_and_manifest(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        assert "range" not in request.headers
        return _body_response(request)

    summary = _run(db_path, data_root, handler)
    assert summary["status"] == "succeeded"
    assert summary["fetched"] == 2
    for kind in ("table1", "table2"):
        path = data_root / "raw" / "audio" / kind / "001.mp3"
        assert path.read_bytes() == FAKE_MP3
        assert not path.with_name(path.name + ".part").exists()
    assert all(value["user-agent"].startswith("Mozilla/5.0") for value in seen)
    with connect_db(db_path) as connection:
        rows = connection.execute(
            "SELECT audio_path, audio_sha256, audio_codec, audio_duration_ms, "
            "audio_sample_rate, audio_channels, audio_bitrate, fetch_error "
            "FROM source_pages ORDER BY source_key"
        ).fetchall()
    assert all(row[0].startswith("raw/audio/") for row in rows)
    assert all(row[1] == hashlib.sha256(FAKE_MP3).hexdigest() for row in rows)
    assert all(tuple(row[i] for i in range(2, 7)) == ("mp3", 1234, 16000, 2, 48000) for row in rows)
    assert all(row[7] is None for row in rows)


def test_audio_206_resume_validates_content_range(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    prefix = FAKE_MP3[:100]
    for kind in ("table1", "table2"):
        part = data_root / "raw" / "audio" / kind / "001.mp3.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(prefix)
    ranges: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        value = request.headers.get("range")
        ranges.append(value or "")
        assert value == "bytes=100-"
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes 100-{len(FAKE_MP3)-1}/{len(FAKE_MP3)}"},
            content=FAKE_MP3[100:],
            request=request,
        )

    summary = _run(db_path, data_root, handler)
    assert summary["fetched"] == 2
    assert ranges == ["bytes=100-", "bytes=100-"]
    assert (data_root / "raw/audio/table1/001.mp3").read_bytes() == FAKE_MP3


def test_audio_200_ignoring_range_rewrites_part_safely(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    for kind in ("table1", "table2"):
        part = data_root / "raw" / "audio" / kind / "001.mp3.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(b"old-prefix")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") == "bytes=10-"
        return _body_response(request)

    summary = _run(db_path, data_root, handler)
    assert summary["fetched"] == 2
    assert (data_root / "raw/audio/table1/001.mp3").read_bytes() == FAKE_MP3
    assert not list((data_root / "raw/audio/table1").glob("*.rewrite"))


def test_bad_content_range_keeps_part_and_no_final(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    for kind in ("table1", "table2"):
        part = data_root / "raw" / "audio" / kind / "001.mp3.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(b"recoverable")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206,
            headers={"Content-Range": "bytes 0-9/100"},
            content=b"wrong-start",
            request=request,
        )

    summary = _run(db_path, data_root, handler, retries=1)
    assert summary["status"] == "failed"
    for kind in ("table1", "table2"):
        assert (data_root / f"raw/audio/{kind}/001.mp3.part").read_bytes() == b"recoverable"
        assert not (data_root / f"raw/audio/{kind}/001.mp3").exists()
    with connect_db(db_path) as connection:
        assert all(
            "Content-Range start" in row[0]
            for row in connection.execute(
                "SELECT fetch_error FROM source_pages ORDER BY source_key"
            )
        )


def test_truncated_200_body_is_not_published(tmp_path):
    db_path, data_root = _seed_db(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(len(FAKE_MP3))},
            content=FAKE_MP3[:100],
            request=request,
        )

    summary = _run(db_path, data_root, handler)
    assert summary["status"] == "failed"
    for kind in ("table1", "table2"):
        assert not (data_root / f"raw/audio/{kind}/001.mp3").exists()
        assert (data_root / f"raw/audio/{kind}/001.mp3.part").read_bytes() == FAKE_MP3[:100]


def test_truncated_206_body_is_not_appended_or_published(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    prefix = FAKE_MP3[:100]
    for kind in ("table1", "table2"):
        part = data_root / "raw" / "audio" / kind / "001.mp3.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(prefix)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") == "bytes=100-"
        return httpx.Response(
            206,
            headers={
                "Content-Range": f"bytes 100-{len(FAKE_MP3)-1}/{len(FAKE_MP3)}"
            },
            content=FAKE_MP3[100:150],
            request=request,
        )

    summary = _run(db_path, data_root, handler)
    assert summary["status"] == "failed"
    for kind in ("table1", "table2"):
        assert (data_root / f"raw/audio/{kind}/001.mp3.part").read_bytes() == prefix
        assert not (data_root / f"raw/audio/{kind}/001.mp3").exists()


def test_existing_matching_file_skips_network(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    digest = hashlib.sha256(FAKE_MP3).hexdigest()
    for kind in ("table1", "table2"):
        path = data_root / f"raw/audio/{kind}/001.mp3"
        path.parent.mkdir(parents=True)
        path.write_bytes(FAKE_MP3)
    with connect_db(db_path) as connection:
        connection.execute(
            "UPDATE source_pages SET audio_sha256 = ?", (digest,)
        )

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("matching final file must not trigger network")

    summary = _run(db_path, data_root, handler)
    assert summary["status"] == "succeeded"
    assert summary["skipped"] == 2


def test_successful_manifest_is_deterministic_across_skip_rerun(tmp_path):
    db_path, data_root = _seed_db(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return _body_response(request)

    first = _run(db_path, data_root, handler)
    manifest_path = data_root / "derived" / "pilot_audio_manifest.json"
    first_manifest = manifest_path.read_bytes()

    def no_network(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("second run should skip verified files")

    second = _run(db_path, data_root, no_network)
    assert first["fetched"] == 2 and second["skipped"] == 2
    assert first_manifest == manifest_path.read_bytes()


def test_ffprobe_failure_keeps_part_and_does_not_publish_final(tmp_path):
    db_path, data_root = _seed_db(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return _body_response(request)

    def bad_probe(_path: Path) -> AudioMetadata:
        raise AudioFetchError("ffprobe failed: invalid MP3")

    summary = _run(db_path, data_root, handler, probe=bad_probe)
    assert summary["status"] == "failed"
    assert summary["failed"] == 2
    for kind in ("table1", "table2"):
        assert (data_root / f"raw/audio/{kind}/001.mp3.part").exists()
        assert not (data_root / f"raw/audio/{kind}/001.mp3").exists()


def test_rar_or_ogg_url_is_rejected_without_network(tmp_path):
    db_path, data_root = _seed_db(
        tmp_path,
        audio_urls=(
            "http://fixture.test/audio/table1/001.rar",
            "http://fixture.test/audio/table2/001.ogg",
        ),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("RAR/OGG must not be requested")

    summary = _run(db_path, data_root, handler)
    assert summary["status"] == "failed"
    assert summary["failed"] == 2


def test_probe_mp3_surfaces_ffprobe_failure(monkeypatch, tmp_path):
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not-an-mp3")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["ffprobe"], returncode=1, stdout="", stderr="Invalid data"
        )

    monkeypatch.setattr("pth_corpus.audio_fetch.subprocess.run", fake_run)
    with pytest.raises(AudioFetchError, match="ffprobe failed"):
        probe_mp3(path)
