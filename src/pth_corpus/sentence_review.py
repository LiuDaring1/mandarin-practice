"""Local-only listening review app for sentence-practice clips.

为「句子练习」的人耳听检服务：一个页面列出待听清单（qa_human_checklist.csv
36 条抽样+提示项，或 alignment_review.csv 82 条低置信复核队列），每条附
句子全文（逐字前鼻青/后鼻橙高亮 + 拼音）、示范音/来源区间预览音、whisper
匹配文本与机器提示。按键判定（A/S/D/F/X），判定由服务端原子落盘到
``data/review/sentence_decisions_<batch>.csv``，刷新即断点续判。

Keybindings:

    A  ok        内容正确、起止干净
    S  boundary  起止边界稍偏（内容仍是这句）
    D  wrong     音频读的不是这句
    F  unclear   听不清/无法判定
    X  skip      跳过待定

复核队列（alignment_review.csv）里没有现成切片：首次请求时用 ffmpeg 从
源音频按对齐区间生成预览 WAV 并缓存到 previews/（不入 git）。
"""

from __future__ import annotations

import csv
import ipaddress
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .sentence_reading import is_hanzi

DECISIONS = ("ok", "boundary", "wrong", "unclear", "skip")
DECISION_LABELS = {
    "ok": "正确",
    "boundary": "边界问题",
    "wrong": "内容不对",
    "unclear": "听不清",
    "skip": "待定",
}
DECISION_KEYS = {
    "a": "ok",
    "s": "boundary",
    "d": "wrong",
    "f": "unclear",
    "x": "skip",
}
DECISION_CSV_COLUMNS = [
    "sentence_id",
    "verdict",
    "notes",
    "reviewed_at",
    "reviewer",
]

PREVIEW_PAD_SEC = 0.5


class SentenceReviewError(RuntimeError):
    """Raised when the sentence review app cannot serve its data."""


class DecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence_id: str = Field(min_length=1, max_length=200)
    verdict: str
    notes: str | None = None
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
        raise SentenceReviewError(
            f"sentence review host must be loopback (127.0.0.1/localhost/::1), "
            f"got {host!r}"
        ) from exc
    if not address.is_loopback:
        raise SentenceReviewError(
            f"sentence review host must be loopback, got {host!r}"
        )
    return value


class DecisionStore:
    """按句一条的判定 CSV，原子替换写入，追加式幂等。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, dict[str, str]]:
        if not self.path.is_file():
            return {}
        with open(self.path, encoding="utf-8", newline="") as handle:
            return {
                str(row["sentence_id"]): dict(row)
                for row in csv.DictReader(handle)
            }

    def _write(self, rows: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=str(self.path.parent)
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=DECISION_CSV_COLUMNS, extrasaction="ignore"
                )
                writer.writeheader()
                for sentence_id in sorted(rows):
                    writer.writerow(rows[sentence_id])
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def upsert(self, row: dict[str, str]) -> None:
        rows = self.load()
        rows[str(row["sentence_id"])] = row
        self._write(rows)

    def delete(self, sentence_id: str) -> bool:
        rows = self.load()
        if sentence_id not in rows:
            return False
        del rows[sentence_id]
        self._write(rows)
        return True


def _safe_clip_path(data_root: Path, sentence_id: str) -> Path | None:
    root = data_root.expanduser().resolve()
    candidate = (
        root / "derived" / "sentence-practice-v1" / "clips"
        / sentence_id.rsplit("-", 1)[0] / f"{sentence_id}.wav"
    )
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _build_preview(
    audio_dir: Path,
    source_file: str,
    start: float,
    end: float,
    sentence_id: str,
    out_dir: Path,
) -> Path | None:
    """对没有现成切片的复核队列条目，从源音频按对齐区间生成预览 WAV。"""
    source = audio_dir / source_file
    if not source.is_file():
        return None
    ffmpeg = subprocess.run(
        ["ffmpeg", "-version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ffmpeg.returncode != 0:
        raise SentenceReviewError(
            "生成预览音频需要 ffmpeg（/opt/homebrew/bin/ffmpeg，请确保 PATH 包含）"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sentence_id}.wav"
    if out_path.is_file():
        return out_path
    s = max(0.0, start - PREVIEW_PAD_SEC)
    dur = max(0.5, (end - start) + 2 * PREVIEW_PAD_SEC)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{s:.2f}", "-i", str(source), "-t", f"{dur:.2f}",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(out_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not out_path.is_file():
        return None
    return out_path


def load_batch(batch_csv: Path) -> list[dict[str, Any]]:
    with open(batch_csv, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SentenceReviewError(f"batch CSV is empty: {batch_csv}")
    for row in rows:
        if not row.get("sentence_id"):
            raise SentenceReviewError(
                f"batch CSV row without sentence_id: {batch_csv}"
            )
    return rows


def _units_of(pinyin_seq: str, label_seq: str, text: str) -> list[dict[str, str]]:
    pys = pinyin_seq.split()
    units: list[dict[str, str]] = []
    k = 0
    for ch in text:
        if is_hanzi(ch) and k < len(pys):
            units.append({"ch": ch, "py": pys[k], "label": label_seq[k]})
            k += 1
        else:
            units.append({"ch": ch, "py": "", "label": ""})
    return units


class SentenceRuntime:
    """句子听检的清单与上下文组装。"""

    def __init__(self, data_root: str | Path, batch_csv: str | Path,
                 decisions_csv: str | Path, batch_label: str,
                 audio_dir: str | Path | None = None) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.batch_label = batch_label
        self.batch_rows = load_batch(Path(batch_csv))
        self.store = DecisionStore(Path(decisions_csv))
        self.audio_dir = (
            Path(audio_dir).resolve()
            if audio_dir
            else self.data_root.parent / "新大纲普通话水平测试用朗读作品音频"
        )
        self._scored: dict[str, dict[str, str]] | None = None
        self._articles: dict[str, dict[str, Any]] | None = None
        self._aligned: dict[str, dict[str, Any]] | None = None
        self._manifest: dict[str, dict[str, Any]] | None = None

    def scored(self) -> dict[str, dict[str, str]]:
        if self._scored is None:
            import csv as _csv

            path = (
                self.data_root / "derived" / "sentence-practice-v1"
                / "sentences_scored.csv"
            )
            self._scored = {}
            if path.is_file():
                with open(path, encoding="utf-8", newline="") as fh:
                    self._scored = {
                        r["sentence_id"]: r for r in _csv.DictReader(fh)
                    }
        return self._scored

    def articles(self) -> dict[str, dict[str, Any]]:
        if self._articles is None:
            import json

            path = (
                self.data_root / "derived" / "sentence-practice-v1"
                / "articles.jsonl"
            )
            self._articles = {}
            if path.is_file():
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            row = json.loads(line)
                            self._articles[row["article_id"]] = row
        return self._articles

    def aligned(self) -> dict[str, dict[str, Any]]:
        if self._aligned is None:
            import json

            path = (
                self.data_root / "derived" / "sentence-practice-v1"
                / "alignment" / "aligned.jsonl"
            )
            self._aligned = {}
            if path.is_file():
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            row = json.loads(line)
                            self._aligned[row["sentence_id"]] = row
        return self._aligned

    def manifest(self) -> dict[str, dict[str, Any]]:
        if self._manifest is None:
            import json

            path = (
                self.data_root / "derived" / "sentence-practice-v1"
                / "clip_manifest.json"
            )
            self._manifest = {}
            if path.is_file():
                with open(path, encoding="utf-8") as fh:
                    for row in json.load(fh):
                        self._manifest[row["sentence_id"]] = row
        return self._manifest

    def items(self) -> list[dict[str, Any]]:
        scored = self.scored()
        articles = self.articles()
        aligned = self.aligned()
        manifest = self.manifest()
        decisions = self.store.load()
        items: list[dict[str, Any]] = []
        for row in self.batch_rows:
            sid = str(row["sentence_id"])
            score_row = scored.get(sid, {})
            article_id = sid.rsplit("-", 1)[0]
            article = articles.get(article_id, {})
            align_row = aligned.get(sid, {})
            clip_row = manifest.get(sid, {})
            text = row.get("text") or score_row.get("text", "")
            pinyin_seq = score_row.get("pinyin_seq", "")
            label_seq = score_row.get("label_seq", "")
            note = row.get("note") or ""
            # 复核队列行没有现成切片：用对齐区间 + 源文件生成预览
            start = align_row.get("start") if align_row else None
            end = align_row.get("end") if align_row else None
            has_clip = bool(clip_row)
            items.append(
                {
                    "sentence_id": sid,
                    "text": text,
                    "units": _units_of(pinyin_seq, label_seq, text),
                    "article_title": article.get("title", ""),
                    "page": score_row.get("page") or article.get("page", ""),
                    "nasal_density": score_row.get("nasal_density", ""),
                    "front_count": score_row.get("front_count", ""),
                    "back_count": score_row.get("back_count", ""),
                    "note": note,
                    "matched_text": align_row.get("matched_text", "")[:80],
                    "score": align_row.get("score", ""),
                    "tier": clip_row.get("tier") or align_row.get("tier", ""),
                    "clip_duration": clip_row.get("clip_duration", ""),
                    "src_interval": (
                        f"{clip_row['src_start']}–{clip_row['src_end']}"
                        if clip_row else (
                            f"{start}–{end}" if start is not None else ""
                        )
                    ),
                    "has_clip": has_clip,
                    "start": start,
                    "end": end,
                    "source_file": (
                        clip_row.get("source_file")
                        or article.get("audio_file", "")
                    ),
                    "verdict": decisions.get(sid, {}).get("verdict", ""),
                    "notes": decisions.get(sid, {}).get("notes", ""),
                }
            )
        return items

    def audio_path(self, sentence_id: str) -> Path | None:
        clip = _safe_clip_path(self.data_root, sentence_id)
        if clip is not None:
            return clip
        align = self.aligned().get(sentence_id, {})
        article_id = sentence_id.rsplit("-", 1)[0]
        source_file = self.articles().get(article_id, {}).get("audio_file", "")
        start = align.get("start")
        end = align.get("end")
        if source_file and start is not None and end is not None:
            return _build_preview(
                self.audio_dir,
                source_file,
                float(start),
                float(end),
                sentence_id,
                self.data_root / "derived" / "sentence-practice-v1" / "previews",
            )
        return None


def create_app(
    data_root: str | Path,
    batch_csv: str | Path,
    decisions_csv: str | Path,
    batch_label: str = "checklist",
    audio_dir: str | Path | None = None,
) -> FastAPI:
    runtime = SentenceRuntime(
        data_root, batch_csv, decisions_csv, batch_label, audio_dir=audio_dir
    )
    app = FastAPI(title="sentence practice listening review")

    @app.middleware("http")
    async def no_store_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page_html(batch_label)

    @app.get("/api/items")
    def items() -> dict[str, Any]:
        rows = runtime.items()
        judged = sum(1 for r in rows if r["verdict"])
        counts: dict[str, int] = {d: 0 for d in DECISIONS}
        for r in rows:
            if r["verdict"] in counts:
                counts[r["verdict"]] += 1
        return {
            "batch_label": runtime.batch_label,
            "total": len(rows),
            "judged": judged,
            "counts": counts,
            "items": rows,
            "decisions": {
                k: v for k, v in DECISION_LABELS.items()
            },
        }

    @app.get("/api/audio/{sentence_id}")
    def audio(sentence_id: str) -> FileResponse:
        path = runtime.audio_path(sentence_id)
        if path is None:
            raise HTTPException(status_code=404, detail="audio not found")
        return FileResponse(path, media_type="audio/wav")

    @app.post("/api/decisions", status_code=201)
    def decide(event: DecisionEvent) -> dict[str, Any]:
        row = {
            "sentence_id": event.sentence_id,
            "verdict": event.verdict,
            "notes": event.notes or "",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": event.reviewer or "",
        }
        runtime.store.upsert(row)
        return {"status": "recorded", "sentence_id": event.sentence_id}

    @app.delete("/api/decisions/{sentence_id}")
    def undecide(sentence_id: str) -> dict[str, Any]:
        removed = runtime.store.delete(sentence_id)
        if not removed:
            raise HTTPException(status_code=404, detail="no decision recorded")
        return {"status": "removed", "sentence_id": sentence_id}

    return app


_PAGE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>句子练习 · 人耳听检 · __BATCH__</title>
<style>
:root {
  --bg:#f7f3ec; --surface:#fffdf9; --ink:#26221b; --muted:#8a8172;
  --line:#e7dfd1; --teal:#179d8c; --teal-deep:#0e7e70; --teal-soft:#e1f2ee;
  --orange:#ef8a35; --orange-deep:#d06f1f; --orange-soft:#fbeedd;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; }
.shell { max-width:760px; margin:0 auto; padding:18px 16px 80px; }
h1 { font-size:20px; margin:6px 0 2px; }
.sub { font-size:12.5px; color:var(--muted); margin:0 0 14px; }
.progress { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:14px; }
.pill { padding:6px 12px; border-radius:999px; background:var(--surface);
  border:1px solid var(--line); font-size:13px; }
.pill b { color:var(--teal-deep); }
.keys { font-size:12px; color:var(--muted); margin:0 0 18px; line-height:1.9; }
kbd { display:inline-block; min-width:20px; text-align:center; padding:2px 6px;
  border:1px solid var(--line); border-bottom-width:2px; border-radius:6px;
  background:var(--surface); font-size:12px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:16px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.04); }
.card.judged { opacity:.62; }
.card-head { display:flex; justify-content:space-between; gap:10px; font-size:12px;
  color:var(--muted); margin-bottom:10px; flex-wrap:wrap; }
.badge { padding:3px 8px; border-radius:8px; background:var(--teal-soft);
  color:var(--teal-deep); font-weight:650; }
.badge.orange { background:var(--orange-soft); color:var(--orange-deep); }
.chars { display:flex; flex-wrap:wrap; align-items:flex-end; gap:6px 4px;
  line-height:1; margin:10px 0 6px; }
.sc { display:inline-flex; flex-direction:column; align-items:center; gap:4px;
  padding:6px 4px 8px; border-radius:8px; background:#faf7f1;
  box-shadow:inset 0 0 0 1px var(--line); }
.sc.f { background:var(--teal-soft); box-shadow:inset 0 0 0 1.5px var(--teal); }
.sc.b { background:var(--orange-soft); box-shadow:inset 0 0 0 1.5px var(--orange); }
.sc .py { font-size:10.5px; color:var(--muted); }
.sc.f .py { color:var(--teal-deep); font-weight:650; }
.sc.b .py { color:var(--orange-deep); font-weight:650; }
.sc .ch { font-size:24px; font-weight:640; }
.punct { align-self:flex-end; padding:0 1px 6px; color:var(--muted); font-size:20px; }
.meta { font-size:12.5px; color:var(--muted); line-height:1.9; margin:6px 0 2px; }
.meta .matched { color:#9c5b2a; }
.audio-row { margin:12px 0 4px; }
audio { width:100%; height:40px; }
.verdict-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
.vbtn { flex:1; min-width:86px; padding:11px 6px; border-radius:12px; border:1.5px solid var(--line);
  background:var(--surface); font-size:13.5px; font-weight:650; color:var(--ink); }
.vbtn.on { border-color:var(--teal-deep); background:var(--teal-soft); color:var(--teal-deep); }
.vbtn:active { transform:scale(.97); }
.undo { border:none; background:none; color:var(--muted); font-size:12px;
  text-decoration:underline; padding:6px 2px; }
.filters { display:flex; gap:8px; margin:0 0 12px; }
.fbtn { padding:7px 12px; border-radius:10px; border:1px solid var(--line);
  background:var(--surface); font-size:13px; }
.fbtn.on { background:var(--ink); color:var(--surface); }
.hidden { display:none; }
</style>
</head>
<body>
<div class="shell">
  <h1>句子练习 · 人耳听检</h1>
  <p class="sub" id="sub">批次 __BATCH__ · 判定自动落盘，刷新续判</p>
  <div class="progress" id="progress"></div>
  <p class="keys">
    <kbd>A</kbd>正确 &nbsp; <kbd>S</kbd>边界问题 &nbsp; <kbd>D</kbd>内容不对 &nbsp;
    <kbd>F</kbd>听不清 &nbsp; <kbd>X</kbd>待定 &nbsp;·&nbsp; 按完自动跳到下一条；改判点卡片上的「撤销」
  </p>
  <div class="filters" id="filters">
    <button class="fbtn on" data-filter="all">全部</button>
    <button class="fbtn" data-filter="todo">未判</button>
    <button class="fbtn" data-filter="judged">已判</button>
  </div>
  <div id="list"></div>
</div>
<script>
const DEC_LABEL = {"ok":"正确","boundary":"边界问题","wrong":"内容不对","unclear":"听不清","skip":"待定"};
let ITEMS = [], FILTER = "all", FOCUS = null;

function unitsHtml(units) {
  let html = "";
  for (const u of units) {
    if (!u.label) { html += `<span class="punct">${esc(u.ch)}</span>`; continue; }
    const cls = u.label === "F" ? "f" : (u.label === "B" ? "b" : "");
    html += `<span class="sc ${cls}"><span class="py">${esc(u.py)}</span><span class="ch">${esc(u.ch)}</span></span>`;
  }
  return html;
}
function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;"); }

function render() {
  const rows = ITEMS.filter(r =>
    FILTER === "all" ? true : FILTER === "todo" ? !r.verdict : !!r.verdict);
  const judged = ITEMS.filter(r => r.verdict).length;
  const counts = ITEMS.reduce((acc,r) => { if (r.verdict) acc[r.verdict]=(acc[r.verdict]||0)+1; return acc; }, {});
  document.getElementById("progress").innerHTML =
    `<span class="pill">进度 <b>${judged}</b> / ${ITEMS.length}</span>` +
    Object.entries(counts).map(([k,v]) =>
      `<span class="pill">${DEC_LABEL[k]} <b>${v}</b></span>`).join("");
  const list = document.getElementById("list");
  list.textContent = "";
  if (!rows.length) {
    list.innerHTML = `<p style="color:var(--muted);text-align:center;padding:40px 0">${FILTER==="todo"?"全部听完了 🎉":"暂无条目"}</p>`;
    return;
  }
  for (const r of rows) {
    const card = document.createElement("div");
    card.className = "card" + (r.verdict ? " judged" : "");
    card.dataset.sid = r.sentence_id;
    const interval = r.src_interval ? ` · 区间 ${esc(r.src_interval)}s` : "";
    const dur = r.clip_duration ? ` · ${esc(r.clip_duration)}s` : "";
    const score = r.score !== "" ? ` · 置信度 ${esc(r.score)}` : "";
    const tier = r.tier ? ` · ${esc(r.tier)}` : "";
    card.innerHTML =
      `<div class="card-head"><span>${esc(r.sentence_id)}</span>` +
      `<span><span class="badge">${esc(r.article_title||"—")}</span> ` +
      (r.nasal_density ? `<span class="badge orange">密度 ${Math.round(r.nasal_density*100)}%</span> ` : "") +
      `<span class="badge">前鼻 ${esc(r.front_count)} · 后鼻 ${esc(r.back_count)}</span></span></div>` +
      `<div class="chars">${unitsHtml(r.units)}</div>` +
      `<div class="meta">${esc(r.note)}</div>` +
      `<div class="meta">whisper：<span class="matched">${esc(r.matched_text||"—")}</span>${score}${tier}${dur}${interval}</div>` +
      `<div class="audio-row"><audio controls preload="none" src="/api/audio/${encodeURIComponent(r.sentence_id)}"></audio></div>` +
      `<div class="verdict-row">` +
      Object.entries(DEC_LABEL).map(([k,v]) =>
        `<button class="vbtn${r.verdict===k?" on":""}" data-v="${k}">${v}</button>`).join("") +
      `</div>` +
      (r.verdict ? `<button class="undo" data-undo="1">撤销（当前判定：${DEC_LABEL[r.verdict]}${r.notes?" · "+esc(r.notes):""}）</button>` : "");
    card.querySelectorAll(".vbtn").forEach(btn => {
      btn.addEventListener("click", async () => {
        await decide(r.sentence_id, btn.dataset.v);
      });
    });
    const undo = card.querySelector("[data-undo]");
    if (undo) undo.addEventListener("click", async () => { await undecide(r.sentence_id); });
    list.appendChild(card);
  }
  // 自动滚动到当前焦点条目
  if (FOCUS) {
    const el = list.querySelector(`[data-sid="${CSS.escape(FOCUS)}"]`);
    if (el) el.scrollIntoView({block:"center", behavior:"smooth"});
  }
}

async function decide(sid, verdict) {
  await fetch("/api/decisions", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({sentence_id: sid, verdict}),
  });
  // 焦点移到下一条未判条目（自动续判）
  const idx = ITEMS.findIndex(r => r.sentence_id === sid);
  let next = null;
  if (idx >= 0) {
    for (let k = 1; k <= ITEMS.length; k++) {
      const r = ITEMS[(idx + k) % ITEMS.length];
      if (!r.verdict) { next = r.sentence_id; break; }
    }
  }
  FOCUS = next;
  await load();
}
async function undecide(sid) {
  await fetch("/api/decisions/" + encodeURIComponent(sid), { method:"DELETE" });
  FOCUS = sid;
  await load();
}
async function load() {
  const data = await fetch("/api/items").then(r => r.json());
  ITEMS = data.items;
  render();
}
document.getElementById("filters").addEventListener("click", e => {
  const btn = e.target.closest(".fbtn");
  if (!btn) return;
  document.querySelectorAll(".fbtn").forEach(b => b.classList.remove("on"));
  btn.classList.add("on");
  FILTER = btn.dataset.filter;
  render();
});
document.addEventListener("keydown", async e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const key = e.key.toLowerCase();
  if (!(key in {"a":1,"s":1,"d":1,"f":1,"x":1})) return;
  const visible = [...document.querySelectorAll(".card")];
  let target = (FOCUS && visible.find(c => c.dataset.sid === FOCUS)) || visible[0];
  if (!target) return;
  const map = {"a":"ok","s":"boundary","d":"wrong","f":"unclear","x":"skip"};
  await decide(target.dataset.sid, map[key]);
});
load();
</script>
</body>
</html>
"""


def _page_html(batch_label: str) -> str:
    return _PAGE_HTML.replace("__BATCH__", batch_label)
