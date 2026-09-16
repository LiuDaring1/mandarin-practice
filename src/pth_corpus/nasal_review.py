"""Local-only front/back-nasal listening review app.

Drives the human listening pass for the nasal audit batches produced by
``nasal_audit``.  One page per batch (≤200 items, ~1s clips): the reviewer
presses a single key per item and the app auto-advances.  Decisions are the
single source of truth and are appended idempotently (one row per item) to
``data/review/nasal_decisions_<batch>.csv`` by the server, so the browser
never owns the truth and a refresh resumes exactly where the reviewer left
off.

Keybindings:

    A  ok           音频与词/拼音一致
    S  wrong_word   音频读的是别的词
    D  shift        切分串位（可附重切边界）
    F  tone         声调错
    Q  quality      音质差
    X  skip         跳过待定

Machine clues (whisper text, old Qwen3 text, neighbour words, duration,
segment confidence) are displayed as hints only; the human ear decides.
"""

from __future__ import annotations

import csv
import ipaddress
import json
import mimetypes
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import connect_db

DECISIONS = ("ok", "wrong_word", "shift", "tone", "quality", "skip")
DECISION_LABELS = {
    "ok": "正确",
    "wrong_word": "读错词",
    "shift": "串位",
    "tone": "声调错",
    "quality": "音质差",
    "skip": "待定",
}
DECISION_KEYS = {
    "a": "ok",
    "s": "wrong_word",
    "d": "shift",
    "f": "tone",
    "q": "quality",
    "x": "skip",
}
DECISION_CSV_COLUMNS = [
    "item_id",
    "word",
    "pinyin",
    "tier",
    "verdict",
    "notes",
    "adjusted_start_ms",
    "adjusted_end_ms",
    "reviewed_at",
    "reviewer",
]

DEFAULT_AUDIT_DIR = Path("data/derived/nasal-audit-2026-08-13")


class NasalReviewError(RuntimeError):
    """Raised when the nasal review app cannot serve its data."""


class DecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=64)
    verdict: str
    notes: str | None = None
    adjusted_start_ms: int | None = Field(default=None, ge=0)
    adjusted_end_ms: int | None = Field(default=None, ge=0)
    reviewer: str | None = None

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in DECISIONS:
            raise ValueError(f"verdict must be one of {', '.join(DECISIONS)}")
        return normalized

    @field_validator("notes", "reviewer")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


def validate_loopback_host(host: str) -> str:
    value = str(host).strip()
    if value.lower() == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise NasalReviewError(
            f"nasal review host must be loopback (127.0.0.1/localhost/::1), got {host!r}"
        ) from exc
    if not address.is_loopback:
        raise NasalReviewError(f"nasal review host must be loopback, got {host!r}")
    return value


def load_batch(batch_csv: Path) -> list[dict[str, Any]]:
    """Load one review batch CSV produced by ``nasal_audit``."""
    with open(batch_csv, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise NasalReviewError(f"batch CSV is empty: {batch_csv}")
    for row in rows:
        if not row.get("item_id"):
            raise NasalReviewError(f"batch CSV row without item_id: {batch_csv}")
    return rows


class DecisionStore:
    """Append-only-per-item decision CSV with atomic replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, dict[str, str]]:
        if not self.path.is_file():
            return {}
        with open(self.path, encoding="utf-8", newline="") as handle:
            return {
                str(row["item_id"]): dict(row)
                for row in csv.DictReader(handle)
            }

    def _payload(self, rows: dict[str, dict[str, str]]) -> bytes:
        import io

        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=DECISION_CSV_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for item_id in sorted(rows):
            writer.writerow(rows[item_id])
        return buffer.getvalue().encode("utf-8")

    def _atomic_write(self, payload: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=str(self.path.parent)
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def upsert(self, row: dict[str, str]) -> None:
        rows = self.load()
        rows[str(row["item_id"])] = row
        self._atomic_write(self._payload(rows))

    def delete(self, item_id: str) -> bool:
        rows = self.load()
        if item_id not in rows:
            return False
        del rows[item_id]
        self._atomic_write(self._payload(rows))
        return True


def _safe_media_path(data_root: Path, stored: str | None) -> Path | None:
    if not stored:
        return None
    root = data_root.expanduser().resolve()
    candidate = Path(str(stored))
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(
        strict=False
    )
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _item_context(
    db_path: Path, data_root: Path, item_id: str
) -> dict[str, Any] | None:
    """Segment + source-page media facts for one batch item."""
    with connect_db(db_path) as connection:
        row = connection.execute(
            """
            SELECT e.item_id, e.word_raw, e.pinyin_nfc, e.table_kind,
                   s.segment_id, s.clip_path, s.clip_sha256,
                   s.start_ms, s.end_ms, s.start_ms_raw, s.end_ms_raw,
                   sp.audio_path AS source_audio_path,
                   sp.audio_sha256 AS source_audio_sha256
            FROM entries AS e
            JOIN segments AS s ON s.item_id = e.item_id
            JOIN source_pages AS sp ON sp.id = e.source_page_id
            WHERE e.item_id = ?
            """,
            (item_id,),
        ).fetchone()
    if row is None:
        return None
    clip = _safe_media_path(data_root, row["clip_path"])
    source = _safe_media_path(data_root, row["source_audio_path"])
    return {
        "item_id": str(row["item_id"]),
        "word_raw": str(row["word_raw"] or ""),
        "pinyin_nfc": str(row["pinyin_nfc"] or ""),
        "table_kind": str(row["table_kind"] or ""),
        "clip_path": str(row["clip_path"] or ""),
        "clip_sha256": str(row["clip_sha256"] or ""),
        "clip_file": clip,
        "start_ms": row["start_ms"],
        "end_ms": row["end_ms"],
        "start_ms_raw": row["start_ms_raw"],
        "end_ms_raw": row["end_ms_raw"],
        "source_audio_path": str(row["source_audio_path"] or ""),
        "source_audio_sha256": str(row["source_audio_sha256"] or ""),
        "source_file": source,
    }


def _page_html(items_json: str, batch_label: str) -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>前后鼻音听检 · __BATCH__</title>
<style>
:root{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;color:#202124;background:#f6f7fb}
body{margin:0}.shell{max-width:860px;margin:auto;padding:16px}
.card{background:#fff;border:1px solid #dfe3eb;border-radius:10px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px #0001}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.toolbar button{font:inherit;padding:6px 12px;border:1px solid #b9c2d0;border-radius:7px;background:#fff;cursor:pointer}
.wordline{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.word{font-size:2.2rem;font-weight:700}
.pinyin{font-size:1.2rem;color:#3874c8;font-weight:600}
.identity{color:#687385;font-size:.85rem}
.tier{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.78rem;font-weight:650}
.tier.T1_strong{background:#fde2e2;color:#9c2020}
.tier.T2_mismatch{background:#ffedd5;color:#a33b00}
.tier.T2_repeat{background:#fff3cd;color:#7a5b00}
.tier.T3_shift{background:#e8d9ff;color:#5b2a91}
.tier.T4_homophone{background:#dbeafe;color:#1d4ed8}
.tier.other{background:#eef1f6;color:#4a5468}
.reason{color:#4a5468;font-size:.9rem;margin-top:6px}
.asr{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.asr .box{border:1px solid #e3e8f0;border-radius:8px;padding:8px}
.asr .label{font-size:.76rem;color:#687385}
.asr .text{font-size:1.05rem;font-weight:600;margin-top:2px}
.asr .text.diff{color:#c62828}
.meta{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;color:#4a5468;font-size:.86rem}
audio{width:100%;margin-top:10px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.actions button{flex:1;min-width:96px;font-size:1rem;font-weight:650;padding:10px 8px;border:0;border-radius:8px;cursor:pointer}
.actions button kbd{display:block;font-size:.72rem;font-weight:500;opacity:.75}
.ok{background:#c9f4d1}.wrong{background:#ffd0d0}.shift{background:#e8d9ff}.tone{background:#ffe8ae}.quality{background:#dbeafe}.skip{background:#eef1f6}
.boundary{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
.boundary input{width:96px;font:inherit;padding:5px 8px;border:1px solid #b9c2d0;border-radius:6px}
.hint{color:#687385;font-size:.84rem}
.error{color:#a33b00;white-space:pre-wrap}
.progress{height:8px;background:#e6e9f0;border-radius:4px;overflow:hidden;margin-top:10px}
.progress i{display:block;height:100%;background:#3874c8;width:0}
.decided{color:#1d7a2d}
</style>
</head>
<body><main class="shell">
<h1>前后鼻音听检 <span id="batch-label" class="hint">__BATCH__</span></h1>
<section class="toolbar">
<button id="prev">↑ 上一条</button><button id="next">↓ 下一条</button>
<button id="autoplay-toggle">自动连播：开</button>
<button id="clear-current">撤销当前判定 (Backspace)</button>
<button id="export">导出判定 CSV</button>
<span id="counter" class="hint"></span>
</section>
<section class="card">
<div class="wordline"><span id="word" class="word">—</span><span id="pinyin" class="pinyin">—</span><span id="tier" class="tier other">—</span><span id="identity" class="identity"></span></div>
<div id="reason" class="reason"></div>
<div class="asr">
<div class="box"><div class="label">whisper 听写（本词应为「<span id="whisper-word-ref">—</span>」）</div><div id="whisper" class="text">—</div></div>
<div class="box"><div class="label">旧 Qwen3 听写</div><div id="qwen3" class="text">—</div></div>
</div>
<div class="meta">
<span id="context">前：— ｜ 后：—</span><span id="dur"></span><span id="conf"></span><span id="freq"></span><span id="status" class="decided"></span>
</div>
<audio id="clip-audio" controls preload="auto"></audio>
<div class="boundary">
<span class="hint">串位重切（可选，仅按 D 时生效）：</span>
<label>开始(ms) <input id="start-ms" type="number" step="20" min="0"></label>
<label>结束(ms) <input id="end-ms" type="number" step="20" min="0"></label>
<button id="preview-boundary">预览区间（来源音频）</button>
<button id="preview-context">听前后±300ms</button>
</div>
<div class="actions">
<button class="ok" data-verdict="ok">A 正确<kbd>ok</kbd></button>
<button class="wrong" data-verdict="wrong_word">S 读错词<kbd>wrong_word</kbd></button>
<button class="shift" data-verdict="shift">D 串位<kbd>shift</kbd></button>
<button class="tone" data-verdict="tone">F 声调错<kbd>tone</kbd></button>
<button class="quality" data-verdict="quality">Q 音质差<kbd>quality</kbd></button>
<button class="skip" data-verdict="skip">X 跳过待定<kbd>skip</kbd></button>
</div>
<div class="progress"><i id="progress-bar"></i></div>
<textarea id="export-box" rows="10" style="display:none;width:100%;margin-top:10px;font-family:ui-monospace,monospace" readonly></textarea>
<p id="error" class="error"></p>
</section>
</main>
<script>
const ITEMS=__ITEMS__;
const BATCH='__BATCH__';
let decisions={};
let index=0;
const $=id=>document.getElementById(id);
const LABELS={ok:"正确",wrong_word:"读错词",shift:"串位",tone:"声调错",quality:"音质差",skip:"待定"};
function autoplayOn(){return $("autoplay-toggle").textContent.includes("开")}
function play(){const a=$("clip-audio");a.play&&a.play().catch(()=>{})}
async function api(url,opts){const r=await fetch(url,opts);if(!r.ok)throw new Error(await r.text());return r.json()}
async function saveDecision(verdict){
  const item=ITEMS[index];if(!item)return;
  const s=Number($("start-ms").value),e=Number($("end-ms").value);
  const hasBounds=Number.isFinite(s)&&Number.isFinite(e)&&(s!==item.current_start_ms||e!==item.current_end_ms);
  const payload={item_id:item.item_id,verdict,notes:null,adjusted_start_ms:hasBounds?s:null,adjusted_end_ms:hasBounds?e:null,reviewer:"human"};
  const d=await api("/api/decision",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
  decisions[item.item_id]=d.decision;
  $("error").textContent="";
  return d.decision;
}
function render(){
  const item=ITEMS[index];if(!item)return;
  const d=decisions[item.item_id];
  $("word").textContent=item.word||"—";$("pinyin").textContent=item.pinyin||"—";
  $("identity").textContent=`${item.item_id} · 第${index+1}条 · ${item.syllable_count}音节 · ${item.finals||""}`;
  const t=item.tier;$("tier").textContent=t;$("tier").className="tier "+(t.startsWith("T")?t:"other");
  $("reason").textContent=item.reason||"";
  $("whisper-word-ref").textContent=item.word||"";
  const w=$("whisper");w.textContent=item.whisper_text||"—";
  w.className="text "+(item.whisper_text&&item.whisper_text!==item.word?"diff":"");
  $("qwen3").textContent=item.old_qwen3_asr||"—";
  $("context").textContent=`前：${item.prev_word||"—"} ｜ 后：${item.next_word||"—"}`;
  $("dur").textContent=`时长 ${(Number(item.clip_duration_ms)/1000).toFixed(2)}s`;
  $("conf").textContent=`切分置信度 ${item.segment_confidence??"—"}`;
  $("freq").textContent=`同文本×${item.whisper_text_freq??1}`+(item.both_asr_agree==="1"?" · 双ASR一致":"");
  $("clip-audio").src=item.clip_media_url;
  $("start-ms").value=(d&&d.adjusted_start_ms)?d.adjusted_start_ms:(item.current_start_ms??"");
  $("end-ms").value=(d&&d.adjusted_end_ms)?d.adjusted_end_ms:(item.current_end_ms??"");
  $("status").textContent=d?`已判：${LABELS[d.verdict]||d.verdict}`:"";
  const done=Object.keys(decisions).filter(id=>ITEMS.some(i=>i.item_id===id)).length;
  $("counter").textContent=`${index+1} / ${ITEMS.length} · 已判 ${done}`;
  $("progress-bar").style.width=`${(done/ITEMS.length*100).toFixed(1)}%`;
  play();
}
function move(delta){index=Math.max(0,Math.min(ITEMS.length-1,index+delta));render()}
async function mark(verdict){
  const item=ITEMS[index];if(!item)return;
  $("error").textContent="";
  try{
    await saveDecision(verdict);
    if(verdict!=="skip"&&autoplayOn()){setTimeout(()=>{move(1)},80)}else{render()}
  }catch(e){$("error").textContent=e.message}
}
async function clearCurrent(){
  const item=ITEMS[index];if(!item)return;
  if(!decisions[item.item_id])return;
  await api("/api/decision/"+encodeURIComponent(item.item_id),{method:"DELETE"});
  delete decisions[item.item_id];render();
}
function previewBoundary(){const s=Math.max(0,Number($("start-ms").value)||0)/1000,e=Math.max(s,Number($("end-ms").value)||0)/1000;const a=$("clip-audio");a.currentTime=0;const src=a.src;a.src=ITEMS[index].source_media_url;a.currentTime=s;a.play();const stop=()=>{if(a.currentTime>=e){a.pause();a.removeEventListener("timeupdate",stop)}};a.addEventListener("timeupdate",stop)}
function previewContext(){const item=ITEMS[index];const s=Math.max(0,((item.current_start_ms||0)-300))/1000,e=((item.current_end_ms||0)+300)/1000;const a=$("clip-audio");a.src=item.source_media_url;a.currentTime=s;a.play();const stop=()=>{if(a.currentTime>=e){a.pause();a.removeEventListener("timeupdate",stop)}};a.addEventListener("timeupdate",stop)}
$("prev").onclick=()=>move(-1);$("next").onclick=()=>move(1);
$("autoplay-toggle").onclick=()=>{$("autoplay-toggle").textContent="自动连播："+(autoplayOn()?"关":"开")};
$("clear-current").onclick=clearCurrent;
$("preview-boundary").onclick=previewBoundary;$("preview-context").onclick=previewContext;
$("export").onclick=async()=>{const d=await api("/api/decisions");const rows=Object.values(d).map(r=>[r.item_id,r.word,r.verdict,r.notes||"",r.adjusted_start_ms||"",r.adjusted_end_ms||""].join("\t")).join("\n");const box=$("export-box");box.value=rows||"（还没有判定）";box.style.display="block";box.select();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(box.value).catch(()=>{})}};
document.querySelectorAll("[data-verdict]").forEach(b=>b.onclick=()=>mark(b.dataset.verdict));
document.addEventListener("keydown",e=>{
  const t=e.target;
  if(t&&(t.tagName==="INPUT"||t.tagName==="TEXTAREA"))return;
  const k=e.key.toLowerCase();
  if(e.key===" "||e.code==="Space"){e.preventDefault();const a=$("clip-audio");a.paused?a.play().catch(()=>{}):a.pause()}
  else if(e.key==="ArrowLeft"||e.key==="ArrowUp"){e.preventDefault();move(-1)}
  else if(e.key==="ArrowRight"||e.key==="ArrowDown"){e.preventDefault();move(1)}
  else if(e.key==="Backspace"){e.preventDefault();clearCurrent()}
  else if(k==="a")mark("ok");
  else if(k==="s")mark("wrong_word");
  else if(k==="d")mark("shift");
  else if(k==="f")mark("tone");
  else if(k==="q")mark("quality");
  else if(k==="x")mark("skip");
});
(async()=>{
  try{
    const d=await api("/api/decisions");decisions=d;
    const first=ITEMS.findIndex(i=>!decisions[i.item_id]);
    index=first>=0?first:0;
    render();
  }catch(e){$("error").textContent=e.message}
})();
</script></body></html>""".replace(
        "__ITEMS__", items_json
    ).replace("__BATCH__", batch_label)


def create_nasal_review_app(
    *,
    data_root: str | Path,
    db_path: str | Path,
    batch_csv: str | Path,
    decisions_csv: str | Path,
    batch_label: str | None = None,
) -> FastAPI:
    """Create the loopback-only nasal listening review app."""

    root = Path(data_root).expanduser().resolve()
    db = Path(db_path)
    batch_path = Path(batch_csv)
    store = DecisionStore(Path(decisions_csv))
    label = batch_label or batch_path.stem

    batch_rows = load_batch(batch_path)
    items: list[dict[str, Any]] = []
    for row in batch_rows:
        context = _item_context(db, root, str(row["item_id"]))
        if context is None:
            raise NasalReviewError(
                f"item {row['item_id']} has no segment/source in the corpus DB"
            )
        items.append(
            {
                "item_id": str(row["item_id"]),
                "word": str(row.get("word") or ""),
                "pinyin": str(row.get("pinyin") or ""),
                "syllable_count": str(row.get("syllable_count") or ""),
                "finals": str(row.get("finals") or ""),
                "tier": str(row.get("tier") or ""),
                "reason": str(row.get("reason") or ""),
                "whisper_text": str(row.get("whisper_text") or ""),
                "old_qwen3_asr": str(row.get("old_qwen3_asr") or ""),
                "whisper_text_freq": str(row.get("whisper_text_freq") or "1"),
                "both_asr_agree": str(row.get("both_asr_agree") or "0"),
                "prev_word": str(row.get("prev_word") or ""),
                "next_word": str(row.get("next_word") or ""),
                "clip_duration_ms": str(row.get("clip_duration_ms") or "0"),
                "segment_confidence": str(row.get("segment_confidence") or ""),
                "current_start_ms": context["start_ms"],
                "current_end_ms": context["end_ms"],
                "raw_start_ms": context["start_ms_raw"],
                "raw_end_ms": context["end_ms_raw"],
                "clip_media_url": f"/media/{row['item_id']}/clip",
                "source_media_url": f"/media/{row['item_id']}/source",
            }
        )
    items_json = json.dumps(items, ensure_ascii=False)

    app = FastAPI(
        title="pth-corpus nasal listening review",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.items = {item["item_id"]: item for item in items}
    app.state.store = store
    app.state.root = root
    app.state.db = db

    @app.middleware("http")
    async def no_store_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page_html(items_json, label)

    @app.get("/api/decisions")
    def decisions() -> dict[str, Any]:
        return store.load()

    @app.post("/api/decision", status_code=201)
    def post_decision(event: DecisionEvent) -> dict[str, Any]:
        item = app.state.items.get(event.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not in batch")
        if (event.adjusted_start_ms is None) != (event.adjusted_end_ms is None):
            raise HTTPException(
                status_code=422,
                detail="adjusted_start_ms and adjusted_end_ms must be supplied together",
            )
        if (
            event.adjusted_start_ms is not None
            and event.adjusted_end_ms is not None
            and event.adjusted_start_ms >= event.adjusted_end_ms
        ):
            raise HTTPException(
                status_code=422, detail="adjusted_start_ms must be < adjusted_end_ms"
            )
        raw_start = item["raw_start_ms"]
        raw_end = item["raw_end_ms"]
        if (
            raw_start is not None
            and raw_end is not None
            and event.adjusted_start_ms is not None
            and (
                event.adjusted_start_ms < int(raw_start)
                or event.adjusted_end_ms > int(raw_end)
            )
        ):
            raise HTTPException(
                status_code=422,
                detail=f"adjusted bounds must lie within raw bounds "
                f"{raw_start}-{raw_end} ms",
            )
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = {
            "item_id": event.item_id,
            "word": item["word"],
            "pinyin": item["pinyin"],
            "tier": item["tier"],
            "verdict": event.verdict,
            "notes": event.notes or "",
            "adjusted_start_ms": (
                str(event.adjusted_start_ms)
                if event.adjusted_start_ms is not None
                else ""
            ),
            "adjusted_end_ms": (
                str(event.adjusted_end_ms)
                if event.adjusted_end_ms is not None
                else ""
            ),
            "reviewed_at": now,
            "reviewer": event.reviewer or "human",
        }
        store.upsert(row)
        return {"item_id": event.item_id, "decision": row}

    @app.delete("/api/decision/{item_id}")
    def delete_decision(item_id: str) -> dict[str, Any]:
        removed = store.delete(item_id)
        return {"item_id": item_id, "removed": removed}

    def _media(item_id: str, asset: str) -> FileResponse:
        item = app.state.items.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not in batch")
        if asset == "clip":
            path = _item_context(app.state.db, app.state.root, item_id)["clip_file"]
        elif asset == "source":
            path = _item_context(app.state.db, app.state.root, item_id)["source_file"]
        else:
            raise HTTPException(status_code=404, detail="unknown asset")
        if path is None:
            raise HTTPException(status_code=404, detail="media not found")
        guessed, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=guessed or "application/octet-stream")

    @app.get("/media/{item_id}/clip")
    def clip_media(item_id: str) -> FileResponse:
        return _media(item_id, "clip")

    @app.get("/media/{item_id}/source")
    def source_media(item_id: str) -> FileResponse:
        return _media(item_id, "source")

    return app


__all__ = [
    "DECISIONS",
    "DECISION_KEYS",
    "DECISION_LABELS",
    "DecisionEvent",
    "DecisionStore",
    "NasalReviewError",
    "create_nasal_review_app",
    "load_batch",
    "validate_loopback_host",
]
