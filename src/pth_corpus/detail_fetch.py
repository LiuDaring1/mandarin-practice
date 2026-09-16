"""Fetch the two pilot detail HTML pages without touching audio assets."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .db import DEFAULT_DB_PATH, connect_db, init_db
from .discovery import USER_AGENT

PILOT_SOURCE_KEYS = ("t1-p001", "t2-p001")
MAX_RETRIES = 10


class DetailFetchError(RuntimeError):
    """Raised for invalid fetch arguments or an unavailable pilot database."""


@dataclass(frozen=True, slots=True)
class FetchAttempt:
    source_key: str
    status: str
    path: str | None
    sha256: str | None
    http_status: int | None
    attempts: int
    error: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes through a same-directory ``.part`` file and replace atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _request_once(
    client: httpx.Client, url: str, *, timeout: float
) -> tuple[bytes, int]:
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise DetailFetchError(f"detail URL must remain HTTP (got {url!r})")
    response = client.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=False,
    )
    status = int(response.status_code)
    if status != 200:
        location = response.headers.get("location")
        suffix = f" location={location!r}" if location else ""
        raise DetailFetchError(f"HTTP {status}{suffix}")
    body = bytes(response.content or b"")
    if not body:
        raise DetailFetchError("empty response body")
    return body, status


def fetch_detail_bytes(
    client: httpx.Client,
    url: str,
    *,
    timeout: float,
    retries: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, int, int]:
    """Fetch one HTTP detail page with a finite retry budget."""

    failures: list[str] = []
    for attempt in range(retries + 1):
        try:
            body, status = _request_once(client, url, timeout=timeout)
            return body, status, attempt + 1
        except (httpx.RequestError, DetailFetchError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
            if attempt < retries:
                sleep(0.1 * (2**attempt))
    detail = "; ".join(failures[-3:]) or "unknown fetch failure"
    raise DetailFetchError(
        f"failed to fetch detail {url!r} after {retries + 1} attempts: {detail}"
    )


def _page_path(data_root: Path, table_kind: str, page_no: int) -> Path:
    return data_root / "raw" / "html" / "detail" / table_kind / f"{page_no:03d}.html"


def _validate_options(timeout: float, retries: int) -> None:
    if timeout <= 0:
        raise DetailFetchError(f"timeout must be > 0, got {timeout!r}")
    if retries < 0 or retries > MAX_RETRIES:
        raise DetailFetchError(
            f"retries must be between 0 and {MAX_RETRIES}, got {retries!r}"
        )


def _fetch_html(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    scope: str = "pilot",
    source_keys: tuple[str, ...] | None = PILOT_SOURCE_KEYS,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch detail HTML for the requested source pages (``None`` = all)."""

    _validate_options(timeout, retries)
    init_db(db_path)
    root = Path(data_root)
    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=False)
    outcomes: list[FetchAttempt] = []
    try:
        with connect_db(db_path) as connection:
            if source_keys is None:
                rows = connection.execute(
                    """
                    SELECT id, source_key, table_kind, page_no, url
                    FROM source_pages
                    ORDER BY table_kind, page_no
                    """
                ).fetchall()
            else:
                placeholders = ", ".join("?" for _ in source_keys)
                rows = connection.execute(
                    f"""
                    SELECT id, source_key, table_kind, page_no, url
                    FROM source_pages
                    WHERE source_key IN ({placeholders})
                    ORDER BY table_kind, page_no
                    """,
                    tuple(source_keys),
                ).fetchall()
                found = {str(row["source_key"]) for row in rows}
                missing = [key for key in source_keys if key not in found]
                if missing:
                    raise DetailFetchError(
                        "source_pages missing: " + ", ".join(missing)
                    )

            for row in rows:
                source_key = str(row["source_key"])
                table_kind = str(row["table_kind"])
                page_no = int(row["page_no"])
                url = str(row["url"])
                destination = _page_path(root, table_kind, page_no)
                relative_path = destination.relative_to(root).as_posix()
                fetched_at = datetime.now(timezone.utc).isoformat()
                try:
                    body, status, attempts = fetch_detail_bytes(
                        http_client,
                        url,
                        timeout=timeout,
                        retries=retries,
                        sleep=sleep,
                    )
                    digest = _sha256(body)
                    atomic_write_bytes(destination, body)
                    connection.execute(
                        """
                        UPDATE source_pages
                        SET html_path = ?, html_sha256 = ?, http_status = ?,
                            fetched_at = ?, fetch_status = 'fetched', fetch_error = NULL
                        WHERE id = ?
                        """,
                        (relative_path, digest, status, fetched_at, int(row["id"])),
                    )
                    outcomes.append(
                        FetchAttempt(
                            source_key=source_key,
                            status="fetched",
                            path=relative_path,
                            sha256=digest,
                            http_status=status,
                            attempts=attempts,
                        )
                    )
                except (DetailFetchError, httpx.RequestError) as exc:
                    # A failed page is recorded, but no partial .part file can
                    # become the final HTML path.
                    connection.execute(
                        """
                        UPDATE source_pages
                        SET http_status = NULL, fetched_at = ?, fetch_status = 'failed',
                            fetch_error = ?
                        WHERE id = ?
                        """,
                        (fetched_at, str(exc), int(row["id"])),
                    )
                    outcomes.append(
                        FetchAttempt(
                            source_key=source_key,
                            status="failed",
                            path=None,
                            sha256=None,
                            http_status=None,
                            attempts=retries + 1,
                            error=str(exc),
                        )
                    )
    finally:
        if own_client:
            http_client.close()

    failures = [outcome for outcome in outcomes if outcome.status == "failed"]
    return {
        "command": "fetch",
        "scope": scope,
        "asset": "html",
        "status": "failed" if failures else "succeeded",
        "db": str(db_path),
        "data_root": str(root),
        "pages": [asdict(outcome) for outcome in outcomes],
        "fetched": len(outcomes) - len(failures),
        "failed": len(failures),
    }


def fetch_pilot_html(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch only ``t1-p001`` and ``t2-p001`` HTML pages from the DB URLs."""

    return _fetch_html(
        db_path=db_path,
        data_root=data_root,
        timeout=timeout,
        retries=retries,
        scope="pilot",
        source_keys=PILOT_SOURCE_KEYS,
        client=client,
        sleep=sleep,
    )


def fetch_full_html(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch detail HTML for every registered source page."""

    return _fetch_html(
        db_path=db_path,
        data_root=data_root,
        timeout=timeout,
        retries=retries,
        scope="full",
        source_keys=None,
        client=client,
        sleep=sleep,
    )


__all__ = [
    "DetailFetchError",
    "FetchAttempt",
    "PILOT_SOURCE_KEYS",
    "atomic_write_bytes",
    "fetch_detail_bytes",
    "fetch_full_html",
    "fetch_pilot_html",
]
