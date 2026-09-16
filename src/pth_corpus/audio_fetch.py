"""Direct MP3 fetching for the two pilot source pages.

This module intentionally does not know about RAR/OGG assets, advertisement
matching, or segment cutting.  It only downloads the direct ``audio_url``
recorded by the detail parser and records a verified MP3 plus ffprobe metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .db import DEFAULT_DB_PATH, connect_db, init_db
from .detail_fetch import PILOT_SOURCE_KEYS
from .discovery import USER_AGENT


MAX_RETRIES = 10
_CHUNK_SIZE = 64 * 1024
_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


class AudioFetchError(RuntimeError):
    """Raised for invalid audio assets, transport failures, or bad metadata."""


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    codec: str
    duration_ms: int
    sample_rate: int
    channels: int
    bitrate: int


@dataclass(frozen=True, slots=True)
class AudioOutcome:
    source_key: str
    table_kind: str
    page_no: int
    status: str
    path: str | None
    sha256: str | None
    metadata: AudioMetadata | None
    attempts: int
    bytes: int | None
    http_status: int | None
    error: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_manifest(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _parse_content_range(value: str | None) -> tuple[int, int, int | None]:
    if not value:
        raise AudioFetchError("206 response missing Content-Range")
    match = _CONTENT_RANGE_RE.fullmatch(value.strip())
    if match is None:
        raise AudioFetchError(f"invalid Content-Range: {value!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if end < start:
        raise AudioFetchError(f"invalid Content-Range end before start: {value!r}")
    total_text = match.group(3)
    total = None if total_text == "*" else int(total_text)
    if total is not None and end >= total:
        raise AudioFetchError(f"invalid Content-Range total: {value!r}")
    return start, end, total


def _validate_options(timeout: float, retries: int) -> None:
    if timeout <= 0:
        raise AudioFetchError(f"timeout must be > 0, got {timeout!r}")
    if retries < 0 or retries > MAX_RETRIES:
        raise AudioFetchError(
            f"retries must be between 0 and {MAX_RETRIES}, got {retries!r}"
        )


def _direct_mp3_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise AudioFetchError(f"audio URL must remain HTTP: {url!r}")
    if not parts.netloc:
        raise AudioFetchError(f"audio URL has no host: {url!r}")
    if not parts.path.lower().endswith(".mp3"):
        raise AudioFetchError(
            f"audio asset is not a direct .mp3 (RAR/OGG are forbidden): {url!r}"
        )


def _stream_once(
    client: httpx.Client,
    url: str,
    part_path: Path,
    *,
    timeout: float,
) -> tuple[int, int]:
    """Run one ranged request, preserving ``part_path`` on all failures."""

    part_path.parent.mkdir(parents=True, exist_ok=True)
    existing_size = part_path.stat().st_size if part_path.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing_size:
        headers["Range"] = f"bytes={existing_size}-"

    rewrite_path: Path | None = None
    range_path: Path | None = None
    target_path = part_path
    mode = "ab" if existing_size else "wb"
    bytes_written = 0
    expected_total: int | None = None
    expected_body_bytes: int | None = None
    status = 0
    try:
        with client.stream(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            status = int(response.status_code)
            if status == 206:
                start, end, expected_total = _parse_content_range(
                    response.headers.get("Content-Range")
                )
                if start != existing_size:
                    raise AudioFetchError(
                        "Content-Range start "
                        f"{start} does not match part size {existing_size}"
                    )
                expected_body_bytes = end - start + 1
                # Stage the ranged body separately.  A truncated or oversized
                # response must not corrupt the existing resumable prefix.
                range_path = part_path.with_name(part_path.name + ".range")
                target_path = range_path
                mode = "wb"
            elif status == 200:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        expected_body_bytes = int(content_length)
                    except ValueError as exc:
                        raise AudioFetchError(
                            f"invalid Content-Length: {content_length!r}"
                        ) from exc
                    if expected_body_bytes < 0:
                        raise AudioFetchError(
                            f"invalid Content-Length: {content_length!r}"
                        )
                if existing_size:
                    # The server ignored Range.  Stream into a separate file,
                    # then replace the old part only after the full response is
                    # present; this never appends a full body to a partial one.
                    rewrite_path = part_path.with_name(part_path.name + ".rewrite")
                    target_path = rewrite_path
                mode = "wb"
            else:
                location = response.headers.get("location")
                suffix = f" location={location!r}" if location else ""
                raise AudioFetchError(
                    f"HTTP {status} (expected 200 or 206){suffix}"
                )

            with target_path.open(mode) as handle:
                for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    bytes_written += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        target_size = target_path.stat().st_size if target_path.exists() else 0
        if expected_body_bytes is not None and target_size != expected_body_bytes:
            raise AudioFetchError(
                f"truncated response body: have {target_size} bytes, "
                f"expected {expected_body_bytes}"
            )

        if status == 206 and range_path is not None:
            # The Content-Range span is authoritative for a 206 body.
            if bytes_written != expected_body_bytes:
                raise AudioFetchError(
                    f"ranged body length {bytes_written} does not match "
                    f"Content-Range length {expected_body_bytes}"
                )
            append_mode = "ab" if existing_size else "wb"
            with part_path.open(append_mode) as destination_handle, range_path.open(
                "rb"
            ) as range_handle:
                for chunk in iter(lambda: range_handle.read(_CHUNK_SIZE), b""):
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            range_path.unlink()

        if rewrite_path is not None:
            os.replace(rewrite_path, part_path)
            _fsync_directory(part_path.parent)

        if not part_path.exists() or part_path.stat().st_size == 0:
            raise AudioFetchError("empty audio response")
        if expected_total is not None and part_path.stat().st_size != expected_total:
            raise AudioFetchError(
                f"incomplete ranged body: have {part_path.stat().st_size} bytes, "
                f"expected {expected_total}"
            )
        return status, bytes_written
    except (httpx.HTTPError, OSError) as exc:
        raise AudioFetchError(f"streaming request failed: {exc}") from exc
    finally:
        if rewrite_path is not None and rewrite_path.exists():
            try:
                rewrite_path.unlink()
            except OSError:
                pass
        if range_path is not None and range_path.exists():
            try:
                range_path.unlink()
            except OSError:
                pass


def download_audio(
    client: httpx.Client,
    url: str,
    destination: Path,
    *,
    timeout: float,
    retries: int,
    sleep: Callable[[float], None] = time.sleep,
    finalize: bool = True,
) -> tuple[int, int, int]:
    """Download a direct MP3 using a resumable ``.part``.

    When ``finalize`` is false, the verified byte stream remains at
    ``destination + '.part'`` so the caller can run ffprobe before publishing
    the final path.
    """

    _direct_mp3_url(url)
    part_path = destination.with_name(destination.name + ".part")
    failures: list[str] = []
    for attempt in range(retries + 1):
        try:
            status, bytes_written = _stream_once(
                client, url, part_path, timeout=timeout
            )
            _fsync_file(part_path)
            if finalize:
                os.replace(part_path, destination)
                _fsync_directory(destination.parent)
            return status, bytes_written, attempt + 1
        except (AudioFetchError, httpx.HTTPError, OSError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
            if attempt < retries:
                sleep(0.1 * (2**attempt))
    detail = "; ".join(failures[-3:]) or "unknown download failure"
    raise AudioFetchError(
        f"failed to download {url!r} after {retries + 1} attempts: {detail}"
    )


def probe_mp3(path: Path) -> AudioMetadata:
    """Validate a file with ffprobe and return stable metadata."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-of",
        "json",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,bit_rate,duration:format=duration,bit_rate",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AudioFetchError(f"ffprobe unavailable: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or f"exit {completed.returncode}"
        raise AudioFetchError(f"ffprobe failed for {path}: {detail}")
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise AudioFetchError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc

    streams = payload.get("streams") or []
    stream = next(
        (item for item in streams if str(item.get("codec_name", "")).lower() == "mp3"),
        None,
    )
    if stream is None:
        raise AudioFetchError(f"ffprobe codec is not mp3 for {path}")
    format_info = payload.get("format") or {}

    def positive_int(value: Any, label: str) -> int:
        try:
            result = int(float(value))
        except (TypeError, ValueError) as exc:
            raise AudioFetchError(f"ffprobe {label} is invalid for {path}: {value!r}") from exc
        if result <= 0:
            raise AudioFetchError(f"ffprobe {label} must be positive for {path}: {value!r}")
        return result

    duration_value = stream.get("duration") or format_info.get("duration")
    try:
        duration_ms = int(round(float(duration_value) * 1000))
    except (TypeError, ValueError) as exc:
        raise AudioFetchError(
            f"ffprobe duration is invalid for {path}: {duration_value!r}"
        ) from exc
    if duration_ms <= 0:
        raise AudioFetchError(f"ffprobe duration must be positive for {path}")
    codec = str(stream.get("codec_name", "")).lower()
    return AudioMetadata(
        codec=codec,
        duration_ms=duration_ms,
        sample_rate=positive_int(stream.get("sample_rate"), "sample_rate"),
        channels=positive_int(stream.get("channels"), "channels"),
        bitrate=positive_int(stream.get("bit_rate") or format_info.get("bit_rate"), "bitrate"),
    )


def _audio_path(data_root: Path, table_kind: str, page_no: int) -> Path:
    return data_root / "raw" / "audio" / table_kind / f"{page_no:03d}.mp3"


def _metadata_dict(metadata: AudioMetadata | None) -> dict[str, Any] | None:
    return asdict(metadata) if metadata is not None else None


def _manifest_bytes(
    root: Path, outcomes: Iterable[AudioOutcome], *, scope: str
) -> bytes:
    ordered = sorted(outcomes, key=lambda outcome: (outcome.table_kind, outcome.page_no))
    records: list[dict[str, Any]] = []
    for outcome in ordered:
        available = outcome.status in {"fetched", "skipped"}
        record: dict[str, Any] = {
            "source_key": outcome.source_key,
            "table_kind": outcome.table_kind,
            "page_no": outcome.page_no,
            # The manifest describes the stable artifact state, not the
            # action taken in this run (``fetched`` vs ``skipped``).  That
            # keeps a successful rerun byte-for-byte deterministic.
            "status": "available" if available else "failed",
            "path": outcome.path,
            "sha256": outcome.sha256,
            "bytes": outcome.bytes,
        }
        if not available and outcome.error:
            record["error"] = outcome.error
        if outcome.metadata is not None:
            record.update(
                {
                    "codec": outcome.metadata.codec,
                    "duration_ms": outcome.metadata.duration_ms,
                    "sample_rate": outcome.metadata.sample_rate,
                    "channels": outcome.metadata.channels,
                    "bitrate": outcome.metadata.bitrate,
                }
            )
        records.append(record)
    summary = {
        "schema_version": 1,
        "scope": scope,
        "asset": "audio",
        "files": records,
        "counts": {
            "available": sum(item.status in {"fetched", "skipped"} for item in ordered),
            "failed": sum(item.status == "failed" for item in ordered),
            "total": len(ordered),
        },
    }
    return (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _fetch_audio(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    scope: str = "pilot",
    source_keys: tuple[str, ...] | None = PILOT_SOURCE_KEYS,
    manifest_name: str = "pilot_audio_manifest.json",
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    probe: Callable[[Path], AudioMetadata] = probe_mp3,
) -> dict[str, Any]:
    """Fetch and verify MP3 assets for the requested source pages."""

    _validate_options(timeout, retries)
    init_db(db_path)
    root = Path(data_root)
    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=False)
    outcomes: list[AudioOutcome] = []
    try:
        with connect_db(db_path) as connection:
            if source_keys is None:
                rows = connection.execute(
                    """
                    SELECT id, source_key, table_kind, page_no, audio_url,
                           audio_path, audio_sha256
                    FROM source_pages
                    ORDER BY table_kind, page_no
                    """
                ).fetchall()
            else:
                placeholders = ", ".join("?" for _ in source_keys)
                rows = connection.execute(
                    f"""
                    SELECT id, source_key, table_kind, page_no, audio_url,
                           audio_path, audio_sha256
                    FROM source_pages
                    WHERE source_key IN ({placeholders})
                    ORDER BY table_kind, page_no
                    """,
                    tuple(source_keys),
                ).fetchall()
            found = {str(row["source_key"]) for row in rows}
            missing = [key for key in (source_keys or ()) if key not in found]
            if missing:
                raise AudioFetchError(
                    "source_pages missing: " + ", ".join(missing)
                )

        for row in rows:
            source_key = str(row["source_key"])
            table_kind = str(row["table_kind"])
            page_no = int(row["page_no"])
            destination = _audio_path(root, table_kind, page_no)
            relative_path = destination.relative_to(root).as_posix()
            db_sha = str(row["audio_sha256"] or "")
            try:
                if destination.exists() and db_sha:
                    digest = _sha256_file(destination)
                    if digest == db_sha:
                        metadata = probe(destination)
                        with connect_db(db_path) as connection:
                            connection.execute(
                                """
                                UPDATE source_pages
                                SET audio_path = ?, audio_sha256 = ?, audio_codec = ?,
                                    audio_duration_ms = ?, audio_sample_rate = ?,
                                    audio_channels = ?, audio_bitrate = ?, fetch_error = NULL
                                WHERE id = ?
                                """,
                                (
                                    relative_path,
                                    digest,
                                    metadata.codec,
                                    metadata.duration_ms,
                                    metadata.sample_rate,
                                    metadata.channels,
                                    metadata.bitrate,
                                    int(row["id"]),
                                ),
                            )
                        outcomes.append(
                            AudioOutcome(
                                source_key,
                                table_kind,
                                page_no,
                                "skipped",
                                relative_path,
                                digest,
                                metadata,
                                0,
                                destination.stat().st_size,
                                None,
                            )
                        )
                        continue

                audio_url = str(row["audio_url"] or "")
                if not audio_url:
                    raise AudioFetchError(f"{source_key}: audio_url is empty")
                status, _written, attempts = download_audio(
                    http_client,
                    audio_url,
                    destination,
                    timeout=timeout,
                    retries=retries,
                    sleep=sleep,
                    finalize=False,
                )
                part_path = destination.with_name(destination.name + ".part")
                digest = _sha256_file(part_path)
                metadata = probe(part_path)
                _fsync_file(part_path)
                os.replace(part_path, destination)
                _fsync_directory(destination.parent)
                with connect_db(db_path) as connection:
                    connection.execute(
                        """
                        UPDATE source_pages
                        SET audio_path = ?, audio_sha256 = ?, audio_codec = ?,
                            audio_duration_ms = ?, audio_sample_rate = ?,
                            audio_channels = ?, audio_bitrate = ?, fetch_error = NULL
                        WHERE id = ?
                        """,
                        (
                            relative_path,
                            digest,
                            metadata.codec,
                            metadata.duration_ms,
                            metadata.sample_rate,
                            metadata.channels,
                            metadata.bitrate,
                            int(row["id"]),
                        ),
                    )
                outcomes.append(
                    AudioOutcome(
                        source_key,
                        table_kind,
                        page_no,
                        "fetched",
                        relative_path,
                        digest,
                        metadata,
                        attempts,
                        destination.stat().st_size,
                        status,
                    )
                )
            except (AudioFetchError, httpx.HTTPError, OSError) as exc:
                with connect_db(db_path) as connection:
                    connection.execute(
                        "UPDATE source_pages SET fetch_error = ? WHERE id = ?",
                        (str(exc), int(row["id"])),
                    )
                part_path = destination.with_name(destination.name + ".part")
                outcomes.append(
                    AudioOutcome(
                        source_key,
                        table_kind,
                        page_no,
                        "failed",
                        None,
                        None,
                        None,
                        retries + 1,
                        part_path.stat().st_size if part_path.exists() else None,
                        None,
                        str(exc),
                    )
                )
    finally:
        if own_client:
            http_client.close()

    manifest_path = root / "derived" / manifest_name
    _atomic_manifest(manifest_path, _manifest_bytes(root, outcomes, scope=scope))
    failures = [item for item in outcomes if item.status == "failed"]
    return {
        "command": "fetch",
        "scope": scope,
        "asset": "audio",
        "status": "failed" if failures else "succeeded",
        "db": str(db_path),
        "data_root": str(root),
        "manifest": str(manifest_path),
        "files": [asdict(item) | {"metadata": _metadata_dict(item.metadata)} for item in outcomes],
        "fetched": sum(item.status == "fetched" for item in outcomes),
        "skipped": sum(item.status == "skipped" for item in outcomes),
        "failed": len(failures),
    }


def fetch_pilot_audio(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    probe: Callable[[Path], AudioMetadata] = probe_mp3,
) -> dict[str, Any]:
    """Fetch and verify only the two pilot direct MP3 assets."""

    return _fetch_audio(
        db_path=db_path,
        data_root=data_root,
        timeout=timeout,
        retries=retries,
        scope="pilot",
        source_keys=PILOT_SOURCE_KEYS,
        manifest_name="pilot_audio_manifest.json",
        client=client,
        sleep=sleep,
        probe=probe,
    )


def fetch_full_audio(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    data_root: str | Path = "data",
    timeout: float = 10.0,
    retries: int = 2,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    probe: Callable[[Path], AudioMetadata] = probe_mp3,
) -> dict[str, Any]:
    """Fetch and verify MP3 assets for every registered source page."""

    return _fetch_audio(
        db_path=db_path,
        data_root=data_root,
        timeout=timeout,
        retries=retries,
        scope="full",
        source_keys=None,
        manifest_name="full_audio_manifest.json",
        client=client,
        sleep=sleep,
        probe=probe,
    )


__all__ = [
    "AudioFetchError",
    "AudioMetadata",
    "AudioOutcome",
    "download_audio",
    "fetch_full_audio",
    "fetch_pilot_audio",
    "probe_mp3",
]
