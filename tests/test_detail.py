from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

import httpx
import pytest

from pth_corpus.db import connect_db, init_db
from pth_corpus.detail_fetch import fetch_pilot_html
from pth_corpus.detail_parse import DetailParseError, parse_detail_page, parse_pilot


def _detail_html(
    table_kind: str,
    *,
    bad_row_cells: bool = False,
    empty_at: int | None = None,
    break_at: int | None = None,
    special: bool = False,
) -> bytes:
    folder = "02_zici_1" if table_kind == "table1" else "03_zici_2"
    filename = "01" if table_kind == "table1" else "001"
    rows: list[str] = []
    for start in range(1, 101, 5):
        end = start + 4
        label_start = start + 1 if break_at == start else start
        cells = [f'<td class="xuhao">{label_start}-{end}</td>']
        for position in range(start, end + 1):
            word = f"词{position}"
            pinyin = f"ci{position}"
            if special and position == 1:
                pinyin = "a\u0301"
            elif special and position == 2:
                pinyin = "bái•tiān"
            elif special and position == 3:
                pinyin = "bǎ*shǒu"
            elif special and position == 4:
                pinyin = "cèlüè"
            elif special and position == 5:
                pinyin = "āishānɡ"
            if empty_at == position:
                pinyin = ""
            cells.extend([f"<td>{word}</td>", f"<td>{pinyin}</td>"])
        if bad_row_cells and start == 1:
            cells.pop()
        rows.append(f"<tr>{''.join(cells)}</tr>")
    body = "".join(rows)
    return (
        f'<html><body><audio><source src="../../b_audio/pthxx_com_mp3/{folder}/{filename}.mp3" '
        f'type="audio/mp3"></audio><div id="main3"><table>{body}</table></div></body></html>'
    ).encode("utf-8")


def _seed_db(tmp_path: Path, *, html_paths: bool = True) -> tuple[Path, Path]:
    db_path = tmp_path / "corpus.sqlite3"
    data_root = tmp_path / "data"
    init_db(db_path)
    with connect_db(db_path) as connection:
        for source_key, table_kind, url in (
            ("t1-p001", "table1", "http://fixture.test/t1/01.html"),
            ("t2-p001", "table2", "http://fixture.test/t2/001.html"),
        ):
            html_path = f"raw/html/detail/{table_kind}/001.html" if html_paths else None
            connection.execute(
                "INSERT INTO source_pages "
                "(source_key, table_kind, page_no, url, html_path) VALUES (?, ?, 1, ?, ?)",
                (source_key, table_kind, url, html_path),
            )
    return db_path, data_root


def test_fetch_pilot_html_writes_atomic_paths_and_hashes(tmp_path):
    db_path, data_root = _seed_db(tmp_path, html_paths=False)
    payloads = {
        "http://fixture.test/t1/01.html": _detail_html("table1"),
        "http://fixture.test/t2/001.html": _detail_html("table2"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payloads[str(request.url)], request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        summary = fetch_pilot_html(
            db_path=db_path,
            data_root=data_root,
            timeout=1,
            retries=0,
            client=client,
            sleep=lambda _: None,
        )

    assert summary["status"] == "succeeded"
    for table_kind, expected in (("table1", payloads["http://fixture.test/t1/01.html"]), ("table2", payloads["http://fixture.test/t2/001.html"])):
        path = data_root / "raw" / "html" / "detail" / table_kind / "001.html"
        assert path.read_bytes() == expected
        assert hashlib.sha256(expected).hexdigest()
        assert not list(path.parent.glob("*.part"))
    with connect_db(db_path) as connection:
        rows = connection.execute(
            "SELECT source_key, html_path, html_sha256, http_status, fetch_status, audio_url "
            "FROM source_pages ORDER BY source_key"
        ).fetchall()
    assert [row[0] for row in rows] == ["t1-p001", "t2-p001"]
    assert all(row[4] == "fetched" and row[5] is None for row in rows)
    assert all(row[2] == hashlib.sha256(payloads["http://fixture.test/t1/01.html" if row[0].startswith("t1") else "http://fixture.test/t2/001.html"]).hexdigest() for row in rows)


def test_parse_pilot_validates_200_rows_nfc_specials_and_is_idempotent(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    for table_kind in ("table1", "table2"):
        path = data_root / "raw" / "html" / "detail" / table_kind / "001.html"
        path.parent.mkdir(parents=True)
        path.write_bytes(_detail_html(table_kind, special=True))

    first = parse_pilot(db_path=db_path, data_root=data_root)
    first_json = (data_root / "derived" / "pilot_entries.jsonl").read_bytes()
    second = parse_pilot(db_path=db_path, data_root=data_root)
    assert first["entries"] == second["entries"] == 200
    assert first_json == (data_root / "derived" / "pilot_entries.jsonl").read_bytes()
    with connect_db(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 200
        assert connection.execute("SELECT COUNT(*) FROM entries WHERE item_id LIKE 't1-%'").fetchone()[0] == 100
        assert connection.execute("SELECT COUNT(*) FROM entries WHERE item_id LIKE 't2-%'").fetchone()[0] == 100
        row = connection.execute(
            "SELECT word_raw, pinyin_raw, pinyin_nfc FROM entries WHERE item_id = 't1-00001'"
        ).fetchone()
        assert row[1] == "a\u0301"
        assert row[2] == unicodedata.normalize("NFC", row[1]) == "á"
        assert connection.execute("SELECT audio_url FROM source_pages WHERE source_key='t1-p001'").fetchone()[0].startswith("http://")
    records = [json.loads(line) for line in first_json.decode("utf-8").splitlines()]
    assert [records[0]["item_id"], records[99]["item_id"], records[100]["item_id"]] == ["t1-00001", "t1-00100", "t2-00001"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bad_row_cells": True},
        {"empty_at": 7},
        {"break_at": 6},
    ],
)
def test_parse_detail_page_rejects_shape_empty_and_sequence_errors(kwargs):
    with pytest.raises(DetailParseError):
        parse_detail_page(
            _detail_html("table1", **kwargs),
            source_page_id=1,
            source_key="t1-p001",
            table_kind="table1",
            page_no=1,
            page_url="http://fixture.test/t1/01.html",
        )


def test_parse_transaction_does_not_leave_half_populated_entries(tmp_path):
    db_path, data_root = _seed_db(tmp_path)
    t1 = data_root / "raw/html/detail/table1/001.html"
    t2 = data_root / "raw/html/detail/table2/001.html"
    t1.parent.mkdir(parents=True)
    t1.write_bytes(_detail_html("table1"))
    t2.parent.mkdir(parents=True)
    t2.write_bytes(_detail_html("table2", break_at=6))

    with pytest.raises(DetailParseError):
        parse_pilot(db_path=db_path, data_root=data_root)
    with connect_db(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    assert not (data_root / "derived/pilot_entries.jsonl").exists()
