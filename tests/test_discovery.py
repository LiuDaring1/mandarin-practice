from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from pth_corpus.db import connect_db
from pth_corpus.discovery import (
    DiscoveryError,
    discover_sources,
    parse_index_links,
    validate_pages,
)


FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def _fixture_client(mapping: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        body = mapping.get(str(request.url))
        if body is None:
            return httpx.Response(404, request=request)
        return httpx.Response(200, content=body.encode("utf-8"), request=request)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _custom_urls() -> dict[str, tuple[str, ...]]:
    return {
        "table1": ("http://fixture.test/t1/index.html",),
        "table2": ("http://fixture.test/t2/index.html",),
    }


def test_discover_success_writes_manifest_and_upserts_pending_pages(tmp_path):
    t1_url, t2_url = _custom_urls()["table1"][0], _custom_urls()["table2"][0]
    mapping = {
        t1_url: (FIXTURES / "table1_success.html").read_text(encoding="utf-8"),
        t2_url: (FIXTURES / "table2_success.html").read_text(encoding="utf-8"),
    }
    db_path = tmp_path / "corpus.sqlite3"
    data_root = tmp_path / "data"
    with _fixture_client(mapping) as client:
        summary = discover_sources(
            db_path=db_path,
            data_root=data_root,
            timeout=1,
            retries=0,
            client=client,
            index_urls=_custom_urls(),
            expected_page_counts={"table1": 3, "table2": 2},
            sleep=lambda _: None,
        )

    assert summary["status"] == "succeeded"
    assert summary["source_pages"] == 5
    manifest_path = data_root / "derived" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"] == {"table1": 3, "table2": 2, "total": 5}
    assert [row["source_key"] for row in manifest["source_pages"]] == [
        "t1-p001",
        "t1-p002",
        "t1-p003",
        "t2-p001",
        "t2-p002",
    ]
    for record in manifest["index_pages"]:
        raw_path = data_root / record["path"]
        body = raw_path.read_bytes()
        assert hashlib.sha256(body).hexdigest() == record["sha256"]

    with connect_db(db_path) as connection:
        rows = connection.execute(
            "SELECT source_key, fetch_status FROM source_pages ORDER BY table_kind, page_no"
        ).fetchall()
    assert len(rows) == 5
    assert {row["fetch_status"] for row in rows} == {"pending"}


def test_discover_is_idempotent_for_manifest_and_rows(tmp_path):
    urls = _custom_urls()
    mapping = {
        urls["table1"][0]: (FIXTURES / "table1_success.html").read_text(encoding="utf-8"),
        urls["table2"][0]: (FIXTURES / "table2_success.html").read_text(encoding="utf-8"),
    }
    db_path = tmp_path / "corpus.sqlite3"
    data_root = tmp_path / "data"
    with _fixture_client(mapping) as client:
        kwargs = dict(
            db_path=db_path,
            data_root=data_root,
            timeout=1,
            retries=0,
            client=client,
            index_urls=urls,
            expected_page_counts={"table1": 3, "table2": 2},
            sleep=lambda _: None,
        )
        discover_sources(**kwargs)
        first_manifest = (data_root / "derived" / "source_manifest.json").read_bytes()
        discover_sources(**kwargs)
        second_manifest = (data_root / "derived" / "source_manifest.json").read_bytes()

    assert first_manifest == second_manifest
    with connect_db(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0] == 5


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("table1_duplicate.html", "duplicate"),
        ("table1_missing.html", "non-contiguous"),
        ("table1_https.html", "HTTPS detail URL rejected"),
    ],
)
def test_validation_rejects_duplicate_missing_and_https(fixture, message):
    body = (FIXTURES / fixture).read_bytes()
    if fixture == "table1_https.html":
        with pytest.raises(DiscoveryError, match=message):
            parse_index_links(body, "http://fixture.test/t1/index.html", "table1")
        return

    pages = parse_index_links(body, "http://fixture.test/t1/index.html", "table1")
    with pytest.raises(DiscoveryError, match=message):
        validate_pages(pages, expected_count=3, table_kind="table1")


def test_https_index_url_is_rejected_before_fetch(tmp_path):
    with pytest.raises(DiscoveryError, match="must use http"):
        discover_sources(
            db_path=tmp_path / "corpus.sqlite3",
            data_root=tmp_path / "data",
            index_urls={
                "table1": ("https://fixture.test/t1/index.html",),
                "table2": ("http://fixture.test/t2/index.html",),
            },
            expected_page_counts={"table1": 1, "table2": 1},
            client=_fixture_client({}),
            retries=0,
            sleep=lambda _: None,
        )
