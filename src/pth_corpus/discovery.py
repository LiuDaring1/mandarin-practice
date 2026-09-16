"""Discover the source detail pages from the pthxx directory indexes.

The discovery stage deliberately stops at the detail-page URLs.  It fetches
only the seven known HTTP index pages, stores those responses for provenance,
and upserts the discovered pages into ``source_pages``.  Detail-page parsing
and audio retrieval belong to later stages.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
import re

import httpx
from lxml import etree, html

from .db import DEFAULT_DB_PATH, connect_db, init_db


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# Keep these URLs explicitly HTTP.  ``follow_redirects`` is disabled below so
# an HTTP -> HTTPS redirect is reported instead of silently changing provenance.
INDEX_URLS: dict[str, tuple[str, ...]] = {
    "table1": (
        "http://www.pthxx.com/e_download/02_zici_1/index.html",
        "http://www.pthxx.com/e_download/02_zici_1/index_2.html",
        "http://www.pthxx.com/e_download/02_zici_1/index_3.html",
    ),
    "table2": (
        "http://www.pthxx.com/e_download/03_zici_2/index.html",
        "http://www.pthxx.com/e_download/03_zici_2/index_2.html",
        "http://www.pthxx.com/e_download/03_zici_2/index_3.html",
        "http://www.pthxx.com/e_download/03_zici_2/index_4.html",
    ),
}

EXPECTED_PAGE_COUNTS: dict[str, int] = {"table1": 66, "table2": 105}
_NUMERIC_DETAIL_RE = re.compile(r"^(?P<page>\d+)\.html$", re.IGNORECASE)
_DEFAULT_BACKOFF_SECONDS = 0.1
_MAX_RETRIES = 10


class DiscoveryError(RuntimeError):
    """Raised when an index cannot be fetched or fails validation."""


@dataclass(frozen=True, slots=True)
class SourcePage:
    """A validated numeric detail-page link discovered from an index."""

    table_kind: str
    page_no: int
    url: str

    @property
    def source_key(self) -> str:
        return f"{'t1' if self.table_kind == 'table1' else 't2'}-p{self.page_no:03d}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *data* and atomically replace *path* in the same directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        # os.replace removes the temporary path on success.  If writing or
        # replacing failed, clean it up without masking the original error.
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _index_file_name(table_kind: str, index_url: str) -> str:
    stem = Path(urlsplit(index_url).path).stem or "index"
    return f"{table_kind}_{stem}.html"


def _fetch_index(
    client: httpx.Client,
    url: str,
    *,
    timeout: float,
    retries: int,
    sleep: Callable[[float], None] = time.sleep,
    backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
) -> tuple[bytes, int, int]:
    """Fetch one index with a finite retry budget.

    Returns ``(body, status_code, attempts)``.  Redirects are intentionally
    not followed: preserving the configured HTTP URL is part of provenance.
    """

    failures: list[str] = []
    for attempt in range(retries + 1):
        try:
            response = client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                follow_redirects=False,
            )
        except TypeError:
            # A small fake client used by callers/tests may not accept the
            # follow_redirects keyword.  It is safe to retry the request
            # without it because httpx.Client itself accepts the keyword.
            try:
                response = client.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=timeout,
                )
            except httpx.RequestError as exc:
                failures.append(f"request error ({type(exc).__name__}): {exc}")
                response = None
        except httpx.RequestError as exc:
            failures.append(f"request error ({type(exc).__name__}): {exc}")
            response = None

        if response is not None:
            status_code = int(response.status_code)
            body = bytes(response.content or b"")
            if status_code != 200:
                failures.append(f"HTTP {status_code} (expected 200)")
            elif not body:
                failures.append("empty response body")
            else:
                return body, status_code, attempt + 1

        if attempt < retries:
            sleep(backoff_seconds * (2**attempt))

    detail = "; ".join(failures[-3:]) or "unknown fetch failure"
    raise DiscoveryError(
        f"failed to fetch index {url!r} after {retries + 1} attempts: {detail}"
    )


def parse_index_links(content: bytes | str, index_url: str, table_kind: str) -> list[SourcePage]:
    """Extract numeric detail links from one index response.

    Only ``<a href=".../digits.html">`` links in the same HTTP directory are
    considered.  A numeric HTTPS link is an explicit error rather than being
    silently downgraded or ignored.
    """

    if table_kind not in EXPECTED_PAGE_COUNTS:
        raise DiscoveryError(f"unknown table kind: {table_kind!r}")
    index_parts = urlsplit(index_url)
    if index_parts.scheme != "http":
        raise DiscoveryError(f"index URL must use http (https is rejected): {index_url}")
    if not index_parts.netloc:
        raise DiscoveryError(f"index URL has no host: {index_url}")
    source_directory = posixpath.dirname(index_parts.path).rstrip("/") + "/"

    try:
        root = html.fromstring(content)
    except (TypeError, ValueError, etree.LxmlError) as exc:
        raise DiscoveryError(f"invalid HTML in index {index_url}: {exc}") from exc

    pages: list[SourcePage] = []
    for anchor in root.xpath("//a[@href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        absolute_url = urljoin(index_url, href)
        parts = urlsplit(absolute_url)
        filename = posixpath.basename(parts.path)
        match = _NUMERIC_DETAIL_RE.fullmatch(filename)
        if match is None:
            continue

        # Numeric links are intended to be details.  Reject HTTPS (including
        # an HTTP index that redirects an individual link) explicitly.
        if parts.scheme != "http":
            raise DiscoveryError(
                f"HTTPS detail URL rejected for {index_url}: {absolute_url}"
            )
        if parts.netloc != index_parts.netloc or not parts.path.startswith(source_directory):
            # Ignore unrelated numeric links elsewhere on the page.
            continue
        if parts.query or parts.fragment:
            raise DiscoveryError(
                f"detail href is not a pure numeric filename for {index_url}: {href!r}"
            )

        pages.append(
            SourcePage(
                table_kind=table_kind,
                page_no=int(match.group("page")),
                url=absolute_url,
            )
        )
    return pages


def validate_pages(
    pages: Sequence[SourcePage], *, expected_count: int, table_kind: str
) -> list[SourcePage]:
    """Validate uniqueness and exact page-number continuity for one table."""

    by_number: dict[int, SourcePage] = {}
    duplicates: list[int] = []
    for page in pages:
        if page.table_kind != table_kind:
            raise DiscoveryError(
                f"table mismatch while validating {table_kind}: {page.table_kind}"
            )
        if page.page_no in by_number:
            duplicates.append(page.page_no)
        else:
            by_number[page.page_no] = page
    if duplicates:
        duplicate_text = ", ".join(str(value) for value in sorted(set(duplicates)))
        raise DiscoveryError(f"duplicate {table_kind} page number(s): {duplicate_text}")

    expected = set(range(1, expected_count + 1))
    actual = set(by_number)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra or len(actual) != expected_count:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(str(value) for value in missing))
        if extra:
            details.append("extra=" + ",".join(str(value) for value in extra))
        if not details:
            details.append(f"count={len(actual)} expected={expected_count}")
        raise DiscoveryError(f"non-contiguous {table_kind} page set: {'; '.join(details)}")
    return [by_number[number] for number in range(1, expected_count + 1)]


def _normalise_index_urls(
    index_urls: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    configured = INDEX_URLS if index_urls is None else index_urls
    result: dict[str, tuple[str, ...]] = {}
    for table_kind in ("table1", "table2"):
        values = tuple(configured.get(table_kind, ()))
        if not values:
            raise DiscoveryError(f"no index URLs configured for {table_kind}")
        result[table_kind] = values
    return result


def _manifest(
    *,
    index_records: Sequence[dict[str, Any]],
    pages: Sequence[SourcePage],
    data_root: Path,
) -> dict[str, Any]:
    # Keep the manifest deterministic so an idempotent run produces the same
    # bytes (the raw HTML and checksums carry the fetch provenance).
    return {
        "schema_version": 1,
        "index_pages": list(index_records),
        "source_pages": [
            {
                "source_key": page.source_key,
                "table_kind": page.table_kind,
                "page_no": page.page_no,
                "url": page.url,
                "fetch_status": "pending",
            }
            for page in pages
        ],
        "counts": {
            "table1": sum(page.table_kind == "table1" for page in pages),
            "table2": sum(page.table_kind == "table2" for page in pages),
            "total": len(pages),
        },
        "data_root": str(data_root),
    }


def _upsert_source_pages(db_path: str | Path, pages: Sequence[SourcePage]) -> dict[str, int]:
    init_db(db_path)
    with connect_db(db_path) as connection:
        for page in pages:
            connection.execute(
                """
                INSERT INTO source_pages
                    (source_key, table_kind, page_no, url, fetch_status)
                VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT(table_kind, page_no) DO UPDATE SET
                    source_key = excluded.source_key,
                    url = excluded.url
                """,
                (page.source_key, page.table_kind, page.page_no, page.url),
            )
        rows = connection.execute(
            "SELECT fetch_status, COUNT(*) AS count FROM source_pages GROUP BY fetch_status"
        ).fetchall()
    return {str(row["fetch_status"]): int(row["count"]) for row in rows}


def discover_sources(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = Path("data"),
    timeout: float = 10.0,
    retries: int = 2,
    client: httpx.Client | None = None,
    index_urls: Mapping[str, Sequence[str]] | None = None,
    expected_page_counts: Mapping[str, int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch indexes, validate detail links, persist provenance, and upsert DB rows."""

    if timeout <= 0:
        raise DiscoveryError(f"timeout must be > 0, got {timeout!r}")
    if retries < 0 or retries > _MAX_RETRIES:
        raise DiscoveryError(f"retries must be between 0 and {_MAX_RETRIES}, got {retries!r}")

    configured_urls = _normalise_index_urls(index_urls)
    expected_counts = dict(EXPECTED_PAGE_COUNTS)
    if expected_page_counts is not None:
        expected_counts.update({key: int(value) for key, value in expected_page_counts.items()})
    for table_kind in ("table1", "table2"):
        if expected_counts.get(table_kind, 0) <= 0:
            raise DiscoveryError(f"expected page count must be positive for {table_kind}")

    root = Path(data_root)
    raw_index_root = root / "raw" / "html" / "index"
    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=False)
    index_records: list[dict[str, Any]] = []
    all_pages: dict[str, list[SourcePage]] = {"table1": [], "table2": []}
    attempts_total = 0
    try:
        for table_kind in ("table1", "table2"):
            for index_url in configured_urls[table_kind]:
                if urlsplit(index_url).scheme != "http":
                    raise DiscoveryError(
                        f"index URL must use http (https is rejected): {index_url}"
                    )
                body, status_code, attempts = _fetch_index(
                    http_client,
                    index_url,
                    timeout=timeout,
                    retries=retries,
                    sleep=sleep,
                )
                attempts_total += attempts
                filename = _index_file_name(table_kind, index_url)
                raw_path = raw_index_root / filename
                _atomic_write(raw_path, body)
                relative_path = raw_path.relative_to(root).as_posix()
                digest = _sha256(body)
                index_records.append(
                    {
                        "table_kind": table_kind,
                        "url": index_url,
                        "path": relative_path,
                        "html_path": relative_path,
                        "sha256": digest,
                        "html_sha256": digest,
                        "bytes": len(body),
                        "http_status": status_code,
                        "attempts": attempts,
                    }
                )
                all_pages[table_kind].extend(
                    parse_index_links(body, index_url, table_kind)
                )
    finally:
        if own_client:
            http_client.close()

    validated_pages: list[SourcePage] = []
    for table_kind in ("table1", "table2"):
        validated_pages.extend(
            validate_pages(
                all_pages[table_kind],
                expected_count=expected_counts[table_kind],
                table_kind=table_kind,
            )
        )

    pages = sorted(validated_pages, key=lambda page: (page.table_kind, page.page_no))
    manifest = _manifest(index_records=index_records, pages=pages, data_root=root)
    manifest_path = root / "derived" / "source_manifest.json"
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    status_counts = _upsert_source_pages(db_path, pages)
    _atomic_write(manifest_path, manifest_bytes)
    return {
        "command": "discover",
        "status": "succeeded",
        "db": str(db_path),
        "data_root": str(root),
        "manifest": str(manifest_path),
        "index_pages": len(index_records),
        "source_pages": len(pages),
        "table_counts": {
            "table1": len(all_pages["table1"]),
            "table2": len(all_pages["table2"]),
        },
        "fetch_attempts": attempts_total,
        "fetch_status_counts": status_counts,
        "index_files": index_records,
    }


# Short alias for callers that use the stage name directly.
discover = discover_sources


__all__ = [
    "EXPECTED_PAGE_COUNTS",
    "INDEX_URLS",
    "USER_AGENT",
    "DiscoveryError",
    "SourcePage",
    "discover",
    "discover_sources",
    "parse_index_links",
    "validate_pages",
]
