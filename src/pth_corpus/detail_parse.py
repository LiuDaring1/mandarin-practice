"""Strict DOM parsing and transactional ingestion for the pilot pages."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from lxml import etree, html

from .db import DEFAULT_DB_PATH, connect_db, init_db
from .detail_fetch import PILOT_SOURCE_KEYS, atomic_write_bytes


class DetailParseError(RuntimeError):
    """Raised when a pilot detail page fails strict structural validation."""


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    item_id: str
    source_page_id: int
    table_kind: str
    source_local: str
    page_position: int
    global_seq: int
    word_raw: str
    pinyin_raw: str
    pinyin_nfc: str


@dataclass(frozen=True, slots=True)
class ParsedPage:
    source_page_id: int
    source_key: str
    table_kind: str
    page_no: int
    page_url: str
    audio_url: str
    entries: tuple[ParsedEntry, ...]


_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_XUHAO_XPATH = './/td[contains(concat(" ", normalize-space(@class), " "), " xuhao ")]'


def _cell_text(node: etree._Element) -> str:
    # Only surrounding layout whitespace is removed; raw interior characters
    # (including punctuation and tone marks) remain unchanged.
    return "".join(node.itertext()).strip()


def _find_audio_url(root: etree._Element, page_url: str) -> str:
    sources = []
    for source in root.xpath('//audio/source[@src]'):
        source_type = (source.get("type") or "").strip().lower()
        if source_type == "audio/mp3":
            sources.append((source.get("src") or "").strip())
    if not sources or not sources[0]:
        raise DetailParseError("missing <source type=\"audio/mp3\">")
    audio_url = urljoin(page_url, sources[0])
    if urlsplit(audio_url).scheme != "http":
        raise DetailParseError(f"audio URL must remain HTTP: {audio_url!r}")
    return audio_url


def parse_detail_page(
    content: bytes | str,
    *,
    source_page_id: int,
    source_key: str,
    table_kind: str,
    page_no: int,
    page_url: str,
    expected_items: int | None = 100,
) -> ParsedPage:
    """Parse one detail page using the unique table containing ``td.xuhao``."""

    try:
        root = html.fromstring(
            content,
            # The source pages are XHTML-transitional but include legacy
            # media tags that strict libxml rejects; recover mode still gives
            # us a DOM, after which the table shape is validated strictly.
            parser=html.HTMLParser(encoding="utf-8", recover=True),
        )
    except (TypeError, ValueError, etree.LxmlError) as exc:
        raise DetailParseError(f"invalid HTML for {source_key}: {exc}") from exc

    tables = root.xpath(f"//table[{_XUHAO_XPATH}]")
    if len(tables) != 1:
        raise DetailParseError(
            f"{source_key}: expected exactly one table containing td.xuhao, got {len(tables)}"
        )
    table = tables[0]
    rows = [row for row in table.xpath(".//tr") if row.xpath(_XUHAO_XPATH)]
    entries: list[ParsedEntry] = []
    items_per_page = expected_items if expected_items is not None else 100
    expected_page_start = (page_no - 1) * items_per_page + 1
    expected_start = expected_page_start
    prefix = "t1" if table_kind == "table1" else "t2"
    for row_index, row in enumerate(rows, start=1):
        cells = row.xpath("./td")
        if len(cells) != 11:
            raise DetailParseError(
                f"{source_key}: row {row_index} expected 11 td cells, got {len(cells)}"
            )
        xuhao_indices = [
            index for index, cell in enumerate(cells)
            if "xuhao" in (cell.get("class") or "").split()
        ]
        if xuhao_indices != [0]:
            raise DetailParseError(
                f"{source_key}: row {row_index} must have exactly one leading td.xuhao"
            )
        raw_range = _cell_text(cells[0])
        match = _RANGE_RE.fullmatch(raw_range)
        if match is None:
            raise DetailParseError(
                f"{source_key}: row {row_index} has invalid xuhao {raw_range!r}"
            )
        start, end = int(match.group(1)), int(match.group(2))
        if end - start + 1 != 5 or start != expected_start:
            raise DetailParseError(
                f"{source_key}: row {row_index} sequence {raw_range!r} "
                f"is not the next five positions from {expected_start}"
            )
        for offset in range(5):
            word_raw = _cell_text(cells[1 + offset * 2])
            pinyin_raw = _cell_text(cells[2 + offset * 2])
            if not word_raw or not pinyin_raw:
                raise DetailParseError(
                    f"{source_key}: row {row_index} position {start + offset} has an empty word or pinyin"
                )
            page_position = start + offset
            global_seq = page_position
            entries.append(
                ParsedEntry(
                    item_id=f"{prefix}-{global_seq:05d}",
                    source_page_id=source_page_id,
                    table_kind=table_kind,
                    source_local=raw_range,
                    page_position=page_position,
                    global_seq=global_seq,
                    word_raw=word_raw,
                    pinyin_raw=pinyin_raw,
                    pinyin_nfc=unicodedata.normalize("NFC", pinyin_raw),
                )
            )
        expected_start = end + 1

    actual_count = len(entries)
    expected_positions = list(
        range(expected_page_start, expected_page_start + actual_count)
    )
    if [entry.page_position for entry in entries] != expected_positions:
        raise DetailParseError(
            f"{source_key}: page positions are not contiguous from {expected_page_start}"
        )
    if expected_items is not None and actual_count != expected_items:
        raise DetailParseError(
            f"{source_key}: expected {expected_items} entries, got {actual_count}"
        )
    audio_url = _find_audio_url(root, page_url)
    return ParsedPage(
        source_page_id=source_page_id,
        source_key=source_key,
        table_kind=table_kind,
        page_no=page_no,
        page_url=page_url,
        audio_url=audio_url,
        entries=tuple(entries),
    )


def _jsonl_bytes(pages: Iterable[ParsedPage]) -> bytes:
    records: list[dict[str, Any]] = []
    for page in pages:
        for entry in page.entries:
            record = asdict(entry)
            # The SQLite integer page id is an implementation detail and can
            # differ between databases; omit it so the JSONL bytes depend only
            # on source content and stable IDs.
            record.pop("source_page_id", None)
            record.update(
                {
                    "source_key": page.source_key,
                    "page_no": page.page_no,
                    "page_url": page.page_url,
                    "audio_url": page.audio_url,
                }
            )
            records.append(record)
    records.sort(key=lambda record: (record["table_kind"], record["global_seq"]))
    return b"".join(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def _parse_pages(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    source_keys: tuple[str, ...] | None = PILOT_SOURCE_KEYS,
) -> tuple[Path, list[ParsedPage]]:
    """Load and strictly parse the fetched detail pages."""

    root_path = Path(data_root)
    parsed_pages: list[ParsedPage] = []
    with connect_db(db_path) as connection:
        if source_keys is None:
            rows = connection.execute(
                """
                SELECT id, source_key, table_kind, page_no, url, html_path
                FROM source_pages
                ORDER BY table_kind, page_no
                """
            ).fetchall()
        else:
            placeholders = ", ".join("?" for _ in source_keys)
            rows = connection.execute(
                f"""
                SELECT id, source_key, table_kind, page_no, url, html_path
                FROM source_pages
                WHERE source_key IN ({placeholders})
                ORDER BY table_kind, page_no
                """,
                tuple(source_keys),
            ).fetchall()
            found = {str(row["source_key"]) for row in rows}
            missing = [key for key in source_keys if key not in found]
            if missing:
                raise DetailParseError(
                    "source_pages missing: " + ", ".join(missing)
                )
        for row in rows:
            html_path_value = row["html_path"]
            if not html_path_value:
                raise DetailParseError(
                    f"{row['source_key']}: html_path is empty; fetch the page first"
                )
            html_path = Path(str(html_path_value))
            if not html_path.is_absolute():
                html_path = root_path / html_path
            try:
                content = html_path.read_bytes()
            except OSError as exc:
                raise DetailParseError(
                    f"{row['source_key']}: cannot read {html_path}: {exc}"
                ) from exc
            parsed_pages.append(
                parse_detail_page(
                    content,
                    source_page_id=int(row["id"]),
                    source_key=str(row["source_key"]),
                    table_kind=str(row["table_kind"]),
                    page_no=int(row["page_no"]),
                    page_url=str(row["url"]),
                    expected_items=100 if source_keys is not None else None,
                )
            )
    return root_path, parsed_pages


def _ingest_parsed_pages(
    *,
    db_path: str | Path,
    root_path: Path,
    parsed_pages: list[ParsedPage],
    scope: str,
    json_name: str,
) -> dict[str, Any]:
    """Write the JSONL artifact and upsert entries in one DB transaction."""

    # JSON is prepared before any DB write so malformed pages cannot leave a
    # half-written output artifact or a half-populated entries table.
    json_bytes = _jsonl_bytes(parsed_pages)
    json_path = root_path / "derived" / json_name
    with connect_db(db_path) as connection:
        connection.execute("BEGIN")
        try:
            for page in parsed_pages:
                connection.execute(
                    "UPDATE source_pages SET expected_items = ?, audio_url = ? WHERE id = ?",
                    (len(page.entries), page.audio_url, page.source_page_id),
                )
                for entry in page.entries:
                    connection.execute(
                        """
                        INSERT INTO entries
                            (item_id, source_page_id, table_kind, source_local,
                             page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(item_id) DO UPDATE SET
                            source_page_id = excluded.source_page_id,
                            table_kind = excluded.table_kind,
                            source_local = excluded.source_local,
                            page_position = excluded.page_position,
                            global_seq = excluded.global_seq,
                            word_raw = excluded.word_raw,
                            pinyin_raw = excluded.pinyin_raw,
                            pinyin_nfc = excluded.pinyin_nfc
                        """,
                        (
                            entry.item_id,
                            entry.source_page_id,
                            entry.table_kind,
                            entry.source_local,
                            entry.page_position,
                            entry.global_seq,
                            entry.word_raw,
                            entry.pinyin_raw,
                            entry.pinyin_nfc,
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    atomic_write_bytes(json_path, json_bytes)
    table_counts: dict[str, int] = defaultdict(int)
    for page in parsed_pages:
        table_counts[page.table_kind] += len(page.entries)
    return {
        "command": "parse",
        "scope": scope,
        "status": "succeeded",
        "db": str(db_path),
        "data_root": str(root_path),
        "output": str(json_path),
        "pages": len(parsed_pages),
        "entries": sum(len(page.entries) for page in parsed_pages),
        "table_counts": dict(table_counts),
    }


def parse_pilot(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
) -> dict[str, Any]:
    """Validate both pilot pages, then upsert entries in one DB transaction."""

    if timeout <= 0:
        raise DetailParseError(f"timeout must be > 0, got {timeout!r}")
    if retries < 0:
        raise DetailParseError(f"retries must be >= 0, got {retries!r}")
    init_db(db_path)
    root_path, parsed_pages = _parse_pages(
        db_path=db_path,
        data_root=data_root,
        source_keys=PILOT_SOURCE_KEYS,
    )
    return _ingest_parsed_pages(
        db_path=db_path,
        root_path=root_path,
        parsed_pages=parsed_pages,
        scope="pilot",
        json_name="pilot_entries.jsonl",
    )


def parse_full(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
) -> dict[str, Any]:
    """Validate every fetched page, then upsert all entries transactionally."""

    if timeout <= 0:
        raise DetailParseError(f"timeout must be > 0, got {timeout!r}")
    if retries < 0:
        raise DetailParseError(f"retries must be >= 0, got {retries!r}")
    init_db(db_path)
    root_path, parsed_pages = _parse_pages(
        db_path=db_path,
        data_root=data_root,
        source_keys=None,
    )
    return _ingest_parsed_pages(
        db_path=db_path,
        root_path=root_path,
        parsed_pages=parsed_pages,
        scope="full",
        json_name="full_entries.jsonl",
    )


__all__ = [
    "DetailParseError",
    "ParsedEntry",
    "ParsedPage",
    "parse_detail_page",
    "parse_full",
    "parse_pilot",
]
