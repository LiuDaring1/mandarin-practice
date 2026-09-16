"""Local-only FastAPI review application.

The application is intentionally self-contained: its HTML, CSS and JavaScript
are inline, media is resolved only from paths already recorded in SQLite, and
review actions append rows to ``reviews`` without modifying segments or audio
files.
"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import mimetypes
import sqlite3
import wave
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .audio_analysis import AudioAnalysisError, decode_audio_ffmpeg
from .db import connect_db


REVIEW_STATUSES = ("pending", "approved", "rejected", "needs_review")
ISSUE_CODES = (
    "cut_to_previous",
    "cut_to_next",
    "residual_ad",
    "text_audio_mismatch",
    "audio_quality",
    "other",
)
LOW_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_LIMIT = 200
MAX_LIMIT = 500


class ReviewAppError(RuntimeError):
    """Raised when the local review application cannot serve its data."""


class ReviewEvent(BaseModel):
    """A single append-only review event submitted by the browser/API."""

    model_config = ConfigDict(extra="forbid")

    status: str
    issue_code: str | None = None
    notes: str | None = None
    reviewer: str | None = None
    adjusted_start_ms: int | None = Field(default=None, ge=0)
    adjusted_end_ms: int | None = Field(default=None, ge=0)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of {', '.join(REVIEW_STATUSES)}")
        return normalized

    @field_validator("issue_code")
    @classmethod
    def validate_issue_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if text not in ISSUE_CODES:
            raise ValueError(f"issue_code must be one of {', '.join(ISSUE_CODES)}")
        return text

    @field_validator("reviewer", "notes")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


def validate_loopback_host(host: str) -> str:
    """Reject network-facing bind addresses for this local-only app."""

    value = str(host).strip()
    if value.lower() == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ReviewAppError(
            f"review app host must be loopback (127.0.0.1/localhost/::1), got {host!r}"
        ) from exc
    if not address.is_loopback:
        raise ReviewAppError(f"review app host must be loopback, got {host!r}")
    return value


def _json_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _safe_path(root: Path, stored_path: str | Path | None) -> Path | None:
    """Resolve a DB-whitelisted path while preventing traversal/symlink escape."""

    if not stored_path:
        return None
    root_resolved = root.expanduser().resolve()
    candidate = Path(str(stored_path))
    resolved = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve(
        strict=False
    )
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ReviewAppError("media path escapes data_root") from exc
    return resolved


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 of a media file without loading it fully into RAM."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versioned_url(base: str, digest: str | None) -> str:
    """Attach a content version so browsers cannot reuse an old cached body."""

    return f"{base}?v={digest}" if digest else base


def _summary_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "table_kind": item["table_kind"],
        "page_position": item["page_position"],
        "global_seq": item["global_seq"],
        "word_raw": item["word_raw"],
        "pinyin_raw": item["pinyin_raw"],
        "pinyin_nfc": item["pinyin_nfc"],
        "confidence": item["confidence"],
        "low_confidence": bool(item["low_confidence"]),
        "status": item["effective_status"],
        "stale": bool(item["stale"]),
    }


class ReviewRepository:
    """Small query/command layer shared by API routes and tests."""

    def __init__(self, db_path: str | Path, data_root: str | Path) -> None:
        self.db_path = Path(db_path)
        self.data_root = Path(data_root)

    def _connection(self) -> sqlite3.Connection:
        return connect_db(self.db_path)

    @staticmethod
    def _effective_review(
        segment: sqlite3.Row | None, latest: sqlite3.Row | None
    ) -> tuple[str, bool]:
        if latest is None:
            return "pending", False
        stale = bool(
            segment is not None
            and latest["clip_sha256"] != segment["clip_sha256"]
        )
        return ("pending" if stale else str(latest["status"])), stale

    def _item_row(self, connection: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT e.item_id, e.source_page_id, e.table_kind, e.source_local,
                   e.page_position, e.global_seq, e.word_raw, e.pinyin_raw,
                   e.pinyin_nfc, sp.source_key, sp.page_no, sp.url AS page_url,
                   sp.audio_path AS source_audio_path,
                   sp.audio_sha256 AS source_audio_sha256,
                   s.segment_id, s.clip_path, s.clip_sha256, s.algorithm_version,
                   s.advert_match, s.confidence, s.start_ms, s.end_ms,
                   s.start_ms_raw, s.end_ms_raw, s.start_ms_adjusted,
                   s.end_ms_adjusted, s.boundary_adjustment_ms
            FROM entries AS e
            JOIN source_pages AS sp ON sp.id = e.source_page_id
            LEFT JOIN segments AS s ON s.item_id = e.item_id
            LEFT JOIN excluded_items AS x ON x.item_id = e.item_id
            WHERE e.item_id = ? AND x.item_id IS NULL
            """,
            (item_id,),
        ).fetchone()

    @staticmethod
    def _latest_review(
        connection: sqlite3.Connection, item_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM reviews WHERE item_id = ? ORDER BY revision DESC LIMIT 1",
            (item_id,),
        ).fetchone()

    def _decorate(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        item = dict(row)
        latest = self._latest_review(connection, str(row["item_id"]))
        segment = row if row["segment_id"] is not None else None
        effective_status, stale = self._effective_review(segment, latest)
        confidence = row["confidence"]
        display_start = row["start_ms"] if segment is not None else None
        display_end = row["end_ms"] if segment is not None else None
        if (
            latest is not None
            and not stale
            and latest["adjusted_start_ms"] is not None
            and latest["adjusted_end_ms"] is not None
        ):
            display_start = latest["adjusted_start_ms"]
            display_end = latest["adjusted_end_ms"]
        item.update(
            {
                "confidence": float(confidence) if confidence is not None else None,
                "low_confidence": bool(
                    confidence is not None and float(confidence) < LOW_CONFIDENCE_THRESHOLD
                ),
                "latest_review": _json_row(latest),
                "effective_status": effective_status,
                "stale": stale,
                "display_start_ms": display_start,
                "display_end_ms": display_end,
            }
        )
        return item

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = self._item_row(connection, item_id)
            return self._decorate(connection, row) if row is not None else None

    def list_items(
        self,
        *,
        status: str | None = None,
        table_kind: str | None = None,
        low_confidence: bool | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        if status is not None:
            status = status.strip().lower()
            if status == "all":
                status = None
            elif status not in REVIEW_STATUSES:
                raise ReviewAppError(f"unknown review status {status!r}")
        if table_kind is not None and table_kind not in {"table1", "table2"}:
            raise ReviewAppError(f"unknown table_kind {table_kind!r}")
        if limit < 1 or limit > MAX_LIMIT or offset < 0:
            raise ReviewAppError("limit or offset is outside the allowed range")
        # The optional table filter is still a bound SQL parameter; status is
        # computed after the latest-review/hash comparison because stale rows
        # intentionally become effective ``pending``.
        query = """
            SELECT e.item_id, e.source_page_id, e.table_kind, e.source_local,
                   e.page_position, e.global_seq, e.word_raw, e.pinyin_raw,
                   e.pinyin_nfc, sp.source_key, sp.page_no, sp.url AS page_url,
                   sp.audio_path AS source_audio_path,
                   sp.audio_sha256 AS source_audio_sha256,
                   s.segment_id, s.clip_path, s.clip_sha256, s.algorithm_version,
                   s.advert_match, s.confidence, s.start_ms, s.end_ms,
                   s.start_ms_raw, s.end_ms_raw, s.start_ms_adjusted,
                   s.end_ms_adjusted, s.boundary_adjustment_ms
            FROM entries AS e
            JOIN source_pages AS sp ON sp.id = e.source_page_id
            LEFT JOIN segments AS s ON s.item_id = e.item_id
            LEFT JOIN excluded_items AS x ON x.item_id = e.item_id
        """
        params: list[Any] = []
        if table_kind is not None:
            query += " WHERE e.table_kind = ?"
            params.append(table_kind)
        query += " WHERE x.item_id IS NULL" if table_kind is None else " AND x.item_id IS NULL"
        # Both source tables restart global_seq at one.  Keep the review queue
        # deterministic and contiguous: all of table1, then all of table2.
        query += " ORDER BY CASE e.table_kind WHEN 'table1' THEN 0 ELSE 1 END, e.global_seq, e.item_id"
        with self._connection() as connection:
            all_items = [
                self._decorate(connection, row)
                for row in connection.execute(query, params).fetchall()
            ]
        if low_confidence is not None:
            all_items = [
                item for item in all_items if item["low_confidence"] is low_confidence
            ]
        counts = {value: 0 for value in REVIEW_STATUSES}
        for item in all_items:
            counts[item["effective_status"]] += 1
        if status is not None:
            all_items = [item for item in all_items if item["effective_status"] == status]
        total = len(all_items)
        return all_items[offset : offset + limit], total, counts

    def adjacent(self, item_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with self._connection() as connection:
            row = self._item_row(connection, item_id)
            if row is None:
                return None, None
            ordered = connection.execute(
                """
                SELECT item_id FROM entries
                ORDER BY CASE table_kind WHEN 'table1' THEN 0 ELSE 1 END,
                         global_seq, item_id
                """
            ).fetchall()
            ordered_ids = [str(entry["item_id"]) for entry in ordered]
            try:
                current_index = ordered_ids.index(item_id)
            except ValueError:
                return None, None
            previous_id = ordered_ids[current_index - 1] if current_index else None
            next_id = (
                ordered_ids[current_index + 1]
                if current_index + 1 < len(ordered_ids)
                else None
            )
            previous_row = self._item_row(connection, previous_id) if previous_id else None
            next_row = self._item_row(connection, next_id) if next_id else None
            previous_item = (
                self._decorate(connection, previous_row) if previous_row is not None else None
            )
            next_item = (
                self._decorate(connection, next_row) if next_row is not None else None
            )
            return previous_item, next_item

    def history(self, item_id: str) -> list[dict[str, Any]] | None:
        with self._connection() as connection:
            if self._item_row(connection, item_id) is None:
                return None
            rows = connection.execute(
                "SELECT * FROM reviews WHERE item_id = ? ORDER BY revision",
                (item_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def append_review(self, item_id: str, event: ReviewEvent) -> dict[str, Any]:
        with self._connection() as connection:
            row = self._item_row(connection, item_id)
            if row is None:
                raise KeyError(item_id)
            if row["segment_id"] is None:
                raise ReviewAppError("item has no segment to review")
            raw_start = row["start_ms_raw"]
            raw_end = row["end_ms_raw"]
            if raw_start is None:
                raw_start = row["start_ms"]
            if raw_end is None:
                raw_end = row["end_ms"]
            adjusted_start = event.adjusted_start_ms
            adjusted_end = event.adjusted_end_ms
            issue_code = event.issue_code
            # Approval clears any accidentally supplied issue so an approved
            # event cannot carry a defect classification.
            if event.status == "approved":
                issue_code = None
            if event.status in {"rejected", "needs_review"} and not issue_code:
                raise ReviewAppError(
                    "issue_code is required for rejected or needs_review events"
                )
            if event.status == "approved" and adjusted_start is None and adjusted_end is None:
                adjusted_start = int(row["start_ms"])
                adjusted_end = int(row["end_ms"])
            if (adjusted_start is None) != (adjusted_end is None):
                raise ReviewAppError("adjusted_start_ms and adjusted_end_ms must be supplied together")
            if adjusted_start is not None and adjusted_end is not None:
                if not (int(raw_start) <= adjusted_start < adjusted_end <= int(raw_end)):
                    raise ReviewAppError(
                        f"adjusted boundaries must satisfy {raw_start} <= start < end <= {raw_end}"
                    )
            reviewer = event.reviewer or "local"
            latest_revision = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM reviews WHERE item_id = ?",
                (item_id,),
            ).fetchone()[0]
            revision = int(latest_revision) + 1
            connection.execute(
                """
                INSERT INTO reviews (
                    item_id, status, revision, issue_code, original_start_ms,
                    original_end_ms, adjusted_start_ms, adjusted_end_ms,
                    clip_sha256, reviewer, notes, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    item_id,
                    event.status,
                    revision,
                    issue_code,
                    int(row["start_ms"]),
                    int(row["end_ms"]),
                    adjusted_start,
                    adjusted_end,
                    row["clip_sha256"],
                    reviewer,
                    event.notes,
                ),
            )
            inserted = connection.execute(
                "SELECT * FROM reviews WHERE item_id = ? AND revision = ?",
                (item_id, revision),
            ).fetchone()
            return dict(inserted)

    def media_path(self, item_id: str, asset: str) -> Path:
        item = self.get_item(item_id)
        if item is None:
            raise KeyError(item_id)
        if asset == "clip":
            stored = item.get("clip_path")
        elif asset == "source":
            stored = item.get("source_audio_path")
        else:
            raise ReviewAppError(f"unknown media asset {asset!r}")
        if not stored:
            raise FileNotFoundError(asset)
        path = _safe_path(self.data_root, stored)
        if path is None or not path.is_file():
            raise FileNotFoundError(str(stored))
        return path

    def media_digest(self, item_id: str, asset: str) -> str | None:
        """Return the DB-recorded content version for a media asset."""

        item = self.get_item(item_id)
        if item is None:
            raise KeyError(item_id)
        if asset == "clip":
            return item.get("clip_sha256")
        if asset == "source":
            return item.get("source_audio_sha256")
        raise ReviewAppError(f"unknown media asset {asset!r}")


def _decode_for_waveform(path: Path) -> tuple[np.ndarray, int]:
    """Read local WAV directly, or use the existing shell-free ffmpeg decoder."""

    if path.suffix.lower() != ".wav":
        try:
            return decode_audio_ffmpeg(path), 16_000
        except AudioAnalysisError as exc:
            raise ReviewAppError(str(exc)) from exc
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise ReviewAppError(f"cannot decode WAV {path}: {exc}") from exc
    if channels <= 0 or sample_rate <= 0:
        raise ReviewAppError(f"invalid WAV metadata for {path}")
    if width == 1:
        values = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        values = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        values = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ReviewAppError(f"unsupported WAV sample width {width}")
    if channels > 1:
        values = values[: values.size - (values.size % channels)].reshape(-1, channels).mean(axis=1)
    return values, sample_rate


def waveform_peaks(path: Path, bins: int = 800) -> dict[str, Any]:
    if bins < 1 or bins > 5000:
        raise ReviewAppError("bins must be between 1 and 5000")
    samples, sample_rate = _decode_for_waveform(path)
    if samples.size == 0:
        peaks: list[dict[str, float]] = []
    else:
        edges = np.linspace(0, samples.size, min(bins, samples.size) + 1, dtype=np.int64)
        peaks = []
        for start, end in zip(edges[:-1], edges[1:]):
            values = samples[int(start) : int(end)]
            if values.size == 0:
                continue
            peaks.append(
                {
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "peak": float(np.max(np.abs(values))),
                }
            )
    return {
        "sample_rate": int(sample_rate),
        "sample_count": int(samples.size),
        "duration_ms": int(round(samples.size * 1000 / sample_rate)) if sample_rate else 0,
        "peaks": peaks,
    }


def _page_html() -> str:
    """Return the offline review SPA; all CSS/JS is inline by design."""

    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>普通话语音审核</title>
<style>
:root{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;color:#202124;background:#f6f7fb}
body{margin:0}.shell{max-width:1100px;margin:auto;padding:18px}.toolbar,.card{background:#fff;border:1px solid #dfe3eb;border-radius:10px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px #0001}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.toolbar select,.toolbar button,.boundary input{font:inherit;padding:6px 9px;border:1px solid #b9c2d0;border-radius:6px;background:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.label{font-size:.8rem;color:#687385}.value{font-weight:600}.low{color:#a33b00;background:#fff1e6;border-radius:4px;padding:2px 5px}.stale{color:#9c2020;background:#ffe5e5;border-radius:4px;padding:2px 5px}.context{display:flex;justify-content:space-between;gap:10px}.context button{flex:1;text-align:left}.audio-row{display:grid;gap:7px;margin-top:10px}audio{width:100%}canvas{width:100%;height:150px;border:1px solid #dfe3eb;border-radius:6px;background:#fafbfe}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{font-size:1rem;font-weight:650;padding:8px 18px;border:0;border-radius:7px;cursor:pointer}.approve{background:#c9f4d1}.reject{background:#ffd0d0}.needs{background:#ffe8ae}.boundary{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.boundary label{font-size:.9rem}.boundary input{width:100px}.hint{color:#687385;font-size:.86rem}.error{color:#a33b00;white-space:pre-wrap}
@media(max-width:750px){.grid{grid-template-columns:1fr}.meta{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body><main class="shell">
<h1>普通话语音审核</h1>
<section class="toolbar"><label>状态 <select id="status-filter"><option value="all">全部</option><option value="pending">待审核</option><option value="approved">已通过</option><option value="rejected">已退回</option><option value="needs_review">需复核</option></select></label><button id="prev">↑ 上一条</button><button id="next">↓ 下一条</button><span id="counter" class="hint"></span><span class="hint">快捷键：A 通过 · R 退回 · N 需复核 · 空格播放 · ←/→ 导航</span></section>
<section class="card"><div class="meta"><div><div class="label">词语</div><div id="word" class="value">—</div></div><div><div class="label">拼音</div><div id="pinyin" class="value">—</div></div><div><div class="label">ID / 表 / 页序</div><div id="identity" class="value">—</div></div><div><div class="label">切分边界置信度</div><div id="confidence" class="value">—</div><div class="hint">仅反映自动切分边界的可靠程度，不评价发音、字音或普通话是否正确。</div></div><div><div class="label">审核状态</div><div id="status" class="value">—</div></div><div><div class="label">问题</div><div id="issue" class="value">—</div></div></div></section>
<section class="grid"><div class="card"><h2>当前切片</h2><audio id="clip-audio" controls preload="metadata"></audio><canvas id="waveform" width="1000" height="180"></canvas><div class="boundary"><label>开始(ms) <input id="start-ms" type="number" step="20" min="0"></label><label>结束(ms) <input id="end-ms" type="number" step="20" min="0"></label><span class="hint">20ms 微调；预览使用来源音频</span><button id="preview-boundary">预览调整区间</button></div><div class="boundary"><label>问题类型 <select id="issue-code"><option value="">无</option><option value="cut_to_previous">切到前音</option><option value="cut_to_next">切到后音</option><option value="residual_ad">残留广告</option><option value="text_audio_mismatch">文本/音频错配</option><option value="audio_quality">音质问题</option><option value="other">其他</option></select></label><label>备注 <textarea id="notes" rows="2" placeholder="可选说明"></textarea></label></div><p class="hint issue-help">问题类型说明：切到前音=含上一条声音；切到后音=含下一条声音；残留广告；文本/音频错配；音质问题；其他。仅在退回或需复核时选择，正常条目直接通过。</p><div class="actions"><button class="approve" data-review="approved">A 通过</button><button class="reject" data-review="rejected">R 退回</button><button class="needs" data-review="needs_review">N 需复核</button></div></div><div class="card"><h2>来源上下文</h2><audio id="source-audio" controls preload="metadata"></audio><div class="context"><button id="previous-context"><span id="previous-info">上一条</span></button><button id="next-context"><span id="next-info">下一条</span></button></div><p id="source-range" class="hint"></p><p id="history" class="hint"></p></div></section>
<p id="error" class="error"></p>
</main>
<script>
const state={items:[],index:0,current:null};
const STATUS_LABELS={pending:"待审核",approved:"已通过",rejected:"已退回",needs_review:"需复核",stale:"审批已失效"};
const $=id=>document.getElementById(id);
async function api(url,opts){const r=await fetch(url,opts);if(!r.ok)throw new Error(await r.text());return r.json()}
function draw(peaks){const c=$("waveform"),ctx=c.getContext("2d");ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle="#3874c8";ctx.beginPath();const mid=c.height/2;peaks.forEach((p,i)=>{const x=i/(Math.max(peaks.length-1,1))*(c.width-1);const h=Math.min(mid,Math.max(Math.abs(p.min),Math.abs(p.max))*mid);ctx.moveTo(x,mid-h);ctx.lineTo(x,mid+h)});ctx.stroke()}
function contextLabel(item){return item?`${item.item_id} · ${item.word_raw||"—"}（${item.pinyin_nfc||item.pinyin_raw||"—"}）`:"无"}
function statusLabel(item){return item.stale?STATUS_LABELS.stale:(STATUS_LABELS[item.effective_status]||item.effective_status)}
function render(){
 const x=state.current;if(!x)return;
 $("word").textContent=x.word_raw||"—";$("pinyin").textContent=x.pinyin_nfc||x.pinyin_raw||"—";
 $("identity").textContent=`${x.item_id} / ${x.table_kind} / ${x.page_position}`;
 $("confidence").innerHTML=x.confidence==null?"—":`${Number(x.confidence).toFixed(3)} ${x.low_confidence?'<span class="low">边界需复核</span>':''}`;
 $("status").textContent=statusLabel(x);$("issue").textContent=x.latest_review?.issue_code||"—";
 $("clip-audio").src=x.clip_media_url||"";$("source-audio").src=x.source_media_url||"";
 $("source-range").textContent=`原始区间 ${x.segment?.start_ms_raw??x.segment?.start_ms??"—"}–${x.segment?.end_ms_raw??x.segment?.end_ms??"—"} ms`;
 $("start-ms").value=x.segment?.start_ms??"";$("end-ms").value=x.segment?.end_ms??"";
 $("issue-code").value=x.latest_review?.issue_code||"";$("notes").value=x.latest_review?.notes||"";
 $("previous-info").textContent=`上一条：${contextLabel(x.previous)}`;$("next-info").textContent=`下一条：${contextLabel(x.next)}`;
 $("history").textContent=`历史审核 ${x.review_history?.length||0} 条`;$("counter").textContent=`${state.index+1} / ${state.items.length}`;
 const clipHash=x.segment?.clip_sha256||"";
 api(`/api/items/${encodeURIComponent(x.item_id)}/waveform?asset=clip&v=${encodeURIComponent(clipHash)}`).then(d=>draw(d.peaks)).catch(e=>$("error").textContent=e.message)
}
async function loadItems(){const d=await api(`/api/items?status=${encodeURIComponent($("status-filter").value)}`);state.items=d.items;state.index=Math.min(state.index,Math.max(0,state.items.length-1));if(state.items.length)await loadItem(state.items[state.index].item_id);else{$("counter").textContent="0 / 0";state.current=null}}
async function loadItem(id){const d=await api(`/api/items/${encodeURIComponent(id)}`);state.current=d;state.index=Math.max(0,state.items.findIndex(x=>x.item_id===id));render();$("start-ms").value=d.display_start_ms??"";$("end-ms").value=d.display_end_ms??""}
async function move(delta){if(!state.items.length)return;state.index=Math.max(0,Math.min(state.items.length-1,state.index+delta));await loadItem(state.items[state.index].item_id)}
async function review(status){if(!state.current)return;const reviewedId=state.current.item_id;const oldIndex=state.index;const issue=status==="approved"?null:$("issue-code").value||null;if((status==="rejected"||status==="needs_review")&&!issue){$("error").textContent="退回或需复核时请选择问题类型";return}const payload={status,issue_code:issue,notes:$("notes").value.trim()||null,adjusted_start_ms:Number($("start-ms").value)||null,adjusted_end_ms:Number($("end-ms").value)||null};$("error").textContent="";try{await api(`/api/items/${encodeURIComponent(reviewedId)}/review`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});const d=await api(`/api/items?status=${encodeURIComponent($("status-filter").value)}`);state.items=d.items;const still=state.items.findIndex(x=>x.item_id===reviewedId);const target=state.items.length?Math.min(still>=0?still+1:oldIndex,state.items.length-1):0;state.index=target;if(state.items.length)await loadItem(state.items[target].item_id);else{$("counter").textContent="0 / 0";state.current=null}$("error").textContent=""}catch(e){$("error").textContent=e.message}}
function previewBoundary(){const audio=$("source-audio"),start=Math.max(0,Number($("start-ms").value)||0)/1000,end=Math.max(start,Number($("end-ms").value)||0)/1000;audio.currentTime=start;audio.play();const stop=()=>{if(audio.currentTime>=end){audio.pause();audio.removeEventListener("timeupdate",stop)}};audio.addEventListener("timeupdate",stop)}
$("status-filter").addEventListener("change",()=>{state.index=0;loadItems().catch(e=>$("error").textContent=e.message)});$("prev").onclick=()=>move(-1);$("next").onclick=()=>move(1);$("previous-context").onclick=()=>move(-1);$("next-context").onclick=()=>move(1);$("preview-boundary").onclick=previewBoundary;document.querySelectorAll("[data-review]").forEach(b=>b.onclick=()=>review(b.dataset.review));document.addEventListener("keydown",e=>{if(["INPUT","SELECT","TEXTAREA"].includes(e.target.tagName))return;if(e.key===" "||e.code==="Space"){e.preventDefault();$("clip-audio").play()}else if(e.key==="ArrowLeft"||e.key==="ArrowUp"){e.preventDefault();move(-1)}else if(e.key==="ArrowRight"||e.key==="ArrowDown"){e.preventDefault();move(1)}else if(e.key.toLowerCase()==="a")review("approved");else if(e.key.toLowerCase()==="r")review("rejected");else if(e.key.toLowerCase()==="n")review("needs_review")});loadItems().catch(e=>$("error").textContent=e.message);
</script></body></html>'''


def _sample_page_html(items_json: str, batch: str) -> str:
    """Return the sample-check SPA with the same shortcuts as the review app."""

    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>正式语料抽样核对</title>
<style>
:root{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;color:#202124;background:#f6f7fb}
body{margin:0}.shell{max-width:820px;margin:auto;padding:18px}
.toolbar,.card{background:#fff;border:1px solid #dfe3eb;border-radius:10px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px #0001}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.toolbar button{font:inherit;padding:7px 14px;border:1px solid #b9c2d0;border-radius:7px;background:#fff;cursor:pointer}
.toolbar .approve{background:#c9f4d1}.toolbar .reject{background:#ffd0d0}
.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.label{font-size:.8rem;color:#687385}.value{font-weight:650;font-size:1.15rem}
.value.good{color:#1d7a2d}.value.bad{color:#c62828}
audio{width:100%}
.notes{margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.notes input{flex:1;min-width:220px;padding:8px;border:1px solid #b9c2d0;border-radius:7px;font:inherit}
.hint{color:#687385;font-size:.86rem;margin-top:10px}
.progress{height:6px;background:#e6e9f0;border-radius:3px;overflow:hidden;margin-top:10px}
.progress i{display:block;height:100%;background:#3874c8;width:0}
</style>
</head>
<body><main class="shell">
<section class="toolbar">
<button id="prev">↑ 上一条</button><button id="next">↓ 下一条</button>
<button class="approve" id="approve">A 没问题</button><button class="reject" id="reject">S 有问题</button>
<button id="export">导出标注</button>
<span id="counter" class="hint"></span><span id="done-count" class="hint"></span>
</section>
<section class="card">
<div class="meta">
<div><div class="label">词语</div><div id="word" class="value">—</div></div>
<div><div class="label">拼音</div><div id="pinyin" class="value">—</div></div>
<div><div class="label">ID</div><div id="identity" class="value">—</div></div>
<div><div class="label">核对状态</div><div id="status" class="value">—</div></div>
</div>
<audio id="clip-audio" controls preload="auto"></audio>
<div class="notes"><label>问题说明（按 S 后填写，回车跳到下一条）：</label><input id="notes" type="text" placeholder="可选，例如：声调不对 / 切到前音 / 字音不符"></div>
<div class="progress"><i id="progress-bar"></i></div>
<textarea id="export-box" rows="8" style="display:none;width:100%;margin-top:10px;font-family:ui-monospace,monospace" readonly></textarea>
<p class="hint">快捷键：A 通过并自动播放下一条 · S 标问题并写备注 · ←/→（或 ↑/↓）切换 · 空格播放/暂停 · Esc 退出备注</p>
</section>
</main>
<script>
const ITEMS=__ITEMS__;
const BATCH='__BATCH__';
const KEY='pthx_sample_'+BATCH;
const state=JSON.parse(localStorage.getItem(KEY)||'{}');
let index=0,current=null;
const $=id=>document.getElementById(id);
function play(){const a=$("clip-audio");a.play&&a.play().catch(()=>{})}
function render(){
 const item=ITEMS[index];if(!item)return;current=item;
 $("word").textContent=item.word_raw||"—";$("pinyin").textContent=item.pinyin_nfc||"—";$("identity").textContent=item.item_id;
 $("clip-audio").src=item.clip_media_url||"";
 const s=state[item.item_id]||{};
 $("status").textContent=s.result==="bad"?"有问题":s.result==="ok"?"没问题":"未核对";
 $("status").className="value "+(s.result==="bad"?"bad":s.result==="ok"?"good":"");
 $("notes").value=s.notes||"";
 $("counter").textContent=`${index+1} / ${ITEMS.length}`;
 const done=Object.values(state).filter(v=>v.result).length;
 const bad=Object.values(state).filter(v=>v.result==="bad").length;
 $("done-count").textContent=`已核对 ${done} · 有问题 ${bad}`;
 $("progress-bar").style.width=`${(done/ITEMS.length*100).toFixed(1)}%`;
 play();
}
function move(delta){index=Math.max(0,Math.min(ITEMS.length-1,index+delta));render()}
function next(){move(1)}
function mark(result){
 if(!current)return;
 state[current.item_id]={result,notes:$("notes").value.trim()};
 localStorage.setItem(KEY,JSON.stringify(state));
 if(result==="ok"){next()}
 else{$("notes").focus();render()}
}
$("prev").onclick=()=>move(-1);$("next").onclick=()=>move(1);
$("approve").onclick=()=>mark("ok");$("reject").onclick=()=>mark("bad");
$("export").onclick=()=>{
 const lines=ITEMS.filter(i=>state[i.item_id]&&state[i.item_id].result)
   .map(i=>`${i.item_id}\t${state[i.item_id].result==="bad"?"有问题":"没问题"}\t${state[i.item_id].notes||""}`);
 const box=$("export-box");
 box.value=lines.length?lines.join("\n"):"（还没有标注记录）";
 box.style.display="block";
 box.select();
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(box.value).catch(()=>{})}
};
$("notes").addEventListener("keydown",e=>{
 if(e.key==="Enter"){e.preventDefault();next()}
 else if(e.key==="Escape"){e.preventDefault();e.target.blur()}
});
document.addEventListener("keydown",e=>{
 const t=e.target;
 if(t&&(t.tagName==="INPUT"||t.tagName==="TEXTAREA"))return;
 if(e.key===" "||e.code==="Space"){e.preventDefault();const a=$("clip-audio");a.paused?a.play().catch(()=>{}):a.pause()}
 else if(e.key==="ArrowLeft"||e.key==="ArrowUp"){e.preventDefault();move(-1)}
 else if(e.key==="ArrowRight"||e.key==="ArrowDown"){e.preventDefault();move(1)}
 else if(e.key.toLowerCase()==="a"){mark("ok")}
 else if(e.key.toLowerCase()==="s"){mark("bad")}
});
render();
</script></body></html>'''.replace("__ITEMS__", items_json).replace("__BATCH__", batch)


def create_app(db_path: str | Path, data_root: str | Path) -> FastAPI:
    """Create a local-only review app bound to the supplied SQLite/data root."""

    repository = ReviewRepository(db_path, data_root)
    app = FastAPI(title="pth-corpus local review", docs_url="/api/docs", redoc_url=None)
    app.state.repository = repository

    @app.middleware("http")
    async def no_store_cache(request: Request, call_next):
        """Never let the browser reuse local review content from cache.

        Versioned URLs make stale *content* impossible; no-store also makes
        stale *pages* (old media URLs, old waveform links) impossible.
        """

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page_html()

    @app.get("/sample", response_class=HTMLResponse)
    def sample_page() -> str:
        candidates = sorted(Path(data_root).glob("review/sample_200_*.csv"))
        if not candidates:
            raise HTTPException(status_code=404, detail="sample list not found")
        sample_path = candidates[-1]
        items: list[dict[str, Any]] = []
        with sample_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                item_id = str(row.get("item_id") or "")
                item = repository.get_item(item_id)
                if item is None:
                    continue
                items.append(
                    {
                        "item_id": item_id,
                        "word_raw": item.get("word_raw"),
                        "pinyin_nfc": item.get("pinyin_nfc"),
                        "clip_media_url": (
                            _versioned_url(
                                f"/media/items/{item_id}/clip",
                                item.get("clip_sha256"),
                            )
                            if item.get("clip_path")
                            else None
                        ),
                    }
                )
        if not items:
            raise HTTPException(status_code=404, detail="sample list is empty")
        items_json = json.dumps(items, ensure_ascii=False)
        return _sample_page_html(items_json, sample_path.stem)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with repository._connection() as connection:
            entries = int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
            reviews = int(connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0])
        return {"status": "ok", "entries": entries, "reviews": reviews}

    @app.get("/api/items")
    def items(
        status: str | None = Query(default=None),
        table_kind: str | None = Query(default=None),
        low_confidence: bool | None = Query(default=None),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            values, total, counts = repository.list_items(
                status=status,
                table_kind=table_kind,
                low_confidence=low_confidence,
                limit=limit,
                offset=offset,
            )
        except ReviewAppError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": [_summary_from_item(value) for value in values],
            "count": total,
            "total": total,
            "offset": offset,
            "limit": limit,
            "status_counts": counts,
        }

    @app.get("/api/items/{item_id}")
    def item_detail(item_id: str) -> dict[str, Any]:
        value = repository.get_item(item_id)
        if value is None:
            raise HTTPException(status_code=404, detail="item not found")
        previous, following = repository.adjacent(item_id)
        history = repository.history(item_id) or []
        value["segment"] = {
            key: value[key]
            for key in (
                "segment_id",
                "clip_path",
                "clip_sha256",
                "algorithm_version",
                "advert_match",
                "confidence",
                "start_ms",
                "end_ms",
                "start_ms_raw",
                "end_ms_raw",
                "start_ms_adjusted",
                "end_ms_adjusted",
                "boundary_adjustment_ms",
            )
            if value.get(key) is not None
        }
        value["clip_media_url"] = (
            _versioned_url(f"/media/items/{item_id}/clip", value.get("clip_sha256"))
            if value.get("clip_path")
            else None
        )
        value["source_media_url"] = (
            _versioned_url(
                f"/media/items/{item_id}/source", value.get("source_audio_sha256")
            )
            if value.get("source_audio_path")
            else None
        )
        value["review_history"] = history
        value["effective_review"] = {
            "status": value["effective_status"],
            "stale": value["stale"],
            "latest": value["latest_review"],
        }
        value["previous"] = _summary_from_item(previous) if previous else None
        value["next"] = _summary_from_item(following) if following else None
        # Keep the response focused on public item/segment metadata rather
        # than exposing the internal source_page integer ID.
        value.pop("source_page_id", None)
        return value

    @app.get("/api/items/{item_id}/reviews")
    @app.get("/api/items/{item_id}/review-history")
    def review_history(item_id: str) -> dict[str, Any]:
        history = repository.history(item_id)
        if history is None:
            raise HTTPException(status_code=404, detail="item not found")
        return {"item_id": item_id, "reviews": history}

    @app.get("/api/items/{item_id}/waveform")
    def item_waveform(
        item_id: str,
        asset: str = Query(default="clip"),
        bins: int = Query(default=800, ge=1, le=5000),
        v: str | None = Query(default=None),
    ) -> dict[str, Any]:
        path = _resolve_media(item_id, asset)
        _check_media_version(item_id, asset, v, path)
        try:
            result = waveform_peaks(path, bins=bins)
        except ReviewAppError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result.update(
            {
                "item_id": item_id,
                "asset": asset,
                "media_version": repository.media_digest(item_id, asset),
            }
        )
        return result

    def _resolve_media(item_id: str, asset: str) -> Path:
        try:
            return repository.media_path(item_id, asset)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="item not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="media not found") from exc
        except ReviewAppError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _check_media_version(
        item_id: str, asset: str, requested_version: str | None, path: Path
    ) -> None:
        """Refuse stale versions and unverifiable file/hash drift."""

        expected = repository.media_digest(item_id, asset)
        if requested_version is not None and (
            expected is None or requested_version != expected
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{asset} media version changed; "
                    "reload the review page to fetch the current clip"
                ),
            )
        if expected is not None:
            actual = _sha256_file(path)
            if actual != expected:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"{asset} media file hash does not match the database; "
                        "refusing to serve unverifiable content"
                    ),
                )

    def _media_response(
        item_id: str, asset: str, requested_version: str | None = None
    ) -> FileResponse:
        path = _resolve_media(item_id, asset)
        _check_media_version(item_id, asset, requested_version, path)
        # Omit ``filename`` so browsers keep the response inline for the
        # <audio> element instead of treating it as an attachment download.
        return FileResponse(path, media_type=_media_type(path))

    @app.get("/media/items/{item_id}/clip")
    def clip_media(item_id: str, v: str | None = Query(default=None)) -> FileResponse:
        return _media_response(item_id, "clip", v)

    @app.get("/media/items/{item_id}/source")
    def source_media(item_id: str, v: str | None = Query(default=None)) -> FileResponse:
        return _media_response(item_id, "source", v)

    @app.post("/api/items/{item_id}/review", status_code=201)
    def post_review(item_id: str, event: ReviewEvent) -> dict[str, Any]:
        try:
            review = repository.append_review(item_id, event)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="item not found") from exc
        except ReviewAppError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        value = repository.get_item(item_id)
        assert value is not None
        return {
            "item_id": item_id,
            "review": review,
            "effective_review": {
                "status": value["effective_status"],
                "stale": value["stale"],
            },
        }

    return app


__all__ = [
    "ISSUE_CODES",
    "REVIEW_STATUSES",
    "ReviewAppError",
    "ReviewEvent",
    "ReviewRepository",
    "create_app",
    "validate_loopback_host",
    "waveform_peaks",
]
