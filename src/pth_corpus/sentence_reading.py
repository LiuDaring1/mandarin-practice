"""句子练习语料管线：朗读作品 → 句子库 → 前后鼻音分析 → 音频对齐切分。

流水线（产物一律落在 ``data/derived/sentence-practice-v1/``，不入 git）：

1. ``sentence extract``   PDF（pymupdf，惰性导入）逐页提取标题+正文 → 断句
   → ``articles.jsonl`` / ``sentences.jsonl``
2. ``sentence score``     pypinyin 逐字拼音 → 韵母归类（前鼻 8 音 / 后鼻 8 音）
   → 每句指标 + 筛选 → ``sentences_scored.csv`` + ``polyphones.csv``
3. whisper 转写          ``tools/whisper_sentence_transcribe.py``（需 faster_whisper，
   用 /opt/miniconda3/bin/python，4 路并行）→ ``transcripts/{article}.jsonl``
4. ``sentence align``     字符相似度 + 拼音相似度双通道滑动窗口模糊匹配 +
   句序单调性约束 → ``alignment/aligned.jsonl`` + ``alignment_review.csv``
5. ``sentence cut``       ffmpeg 切 WAV（前后 0.3s 缓冲）→ ``clips/...`` +
   ``clip_manifest.json`` + 机器 QA 报告 + 30 句人工听检抽样

本模块只新增自己的文件与产物，与鼻音清洗窗口（nasal_*.py 等）无冲突，
不修改母库与 training-generator。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import math
import random
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# 常量：前后鼻音韵母（与 phonology.py 的 39 韵母体系一致：前鼻 8 / 后鼻 8）
# ---------------------------------------------------------------------------

FRONT_NASAL_FINALS = ("an", "en", "ian", "in", "uan", "uen", "üan", "ün")
BACK_NASAL_FINALS = ("ang", "eng", "iang", "ing", "uang", "ueng", "ong", "iong")

FRONT_LABEL = "F"  # 前鼻音
BACK_LABEL = "B"  # 后鼻音
OTHER_LABEL = "O"

DEFAULT_OUT = "derived/sentence-practice-v1"
DEFAULT_AUDIO_DIR = "新大纲普通话水平测试用朗读作品音频"

PAGE_HEADER_MARK = "普通话免费模拟测评"

# 标题变体：PDF 标题 -> 音频文件名（规范化后）
TITLE_AUDIO_VARIANTS = {"小鸟的天堂": "鸟的天堂"}

# 筛选基准句（《读书人是幸福人》），验收要求必须入选
BENCHMARK_SENTENCE = (
    "世间有诸多的不平等，财富的不平等，权力的不平等，"
    "而阅读能力的拥有或丧失，却体现为精神的不平等"
)

SENTENCE_SPLIT_RE = re.compile(r"[。！？；]")
TRIM_PUNCT = "，、：；。！？…—“”\"'‘’《》（）【】·"

CLIP_PAD_SEC = 0.3
CLIP_MIN_SEC = 1.0
# 句子练习切片按整句朗读计：长句可达 30s+，上限放宽到 45s（词条切片才是 1–15s）
CLIP_MAX_SEC = 45.0
# 切分边界策略（人耳听检反馈后收紧）：
# - 缓冲只留 0.15s（≈半个音节），且被邻句边界钳制，不把邻句音节带进来
# - 短句至少切 1.5s（截太短听不清话头）
CUT_PAD_SEC = 0.15
CUT_MIN_SEC = 1.5
CUT_MAX_EXTEND_SEC = 0.35
QA_SAMPLE_SIZE = 30
QA_SAMPLE_SEED = 20260814

# 置信度分级阈值
TIER_HIGH_MIN_SCORE = 0.80
TIER_MID_MIN_SCORE = 0.55
TIER_LEN_RATIO_OK = (0.70, 1.35)


class SentenceReadingError(Exception):
    """句子练习管线的业务错误。"""


# ---------------------------------------------------------------------------
# 文本规范化与断句
# ---------------------------------------------------------------------------

def norm_hanzi(text: str) -> str:
    """归一化：NFKC + 只保留汉字（去标点/空白/数字/拉丁）。"""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[^\u4e00-\u9fff]", "", text)


def is_hanzi(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def trim_sentence_edges(text: str) -> str:
    return text.strip().strip(TRIM_PUNCT).strip()


def split_sentences(body: str) -> list[str]:
    """按 。！？； 断句；去换行/空白，修剪边缘连接标点，丢弃无汉字片段。"""
    body = "".join(body.split())
    sentences: list[str] = []
    for part in SENTENCE_SPLIT_RE.split(body):
        sent = trim_sentence_edges(part)
        if not sent or not any(is_hanzi(ch) for ch in sent):
            continue
        sentences.append(sent)
    return sentences


def parse_page_text(text: str) -> tuple[str | None, str]:
    """解析一页 PDF 文本：返回 (标题, 正文)。标题行形如《...》。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    body_lines = [ln for ln in lines if PAGE_HEADER_MARK not in ln]
    title: str | None = None
    rest: list[str] = []
    for ln in body_lines:
        if title is None and ln.startswith("《") and ln.endswith("》"):
            title = ln[1:-1].strip()
        else:
            rest.append(ln)
    return title, "".join(rest)


# ---------------------------------------------------------------------------
# 拼音与韵母归类
# ---------------------------------------------------------------------------

def _pypinyin() -> Any:
    try:
        import pypinyin
    except ImportError as exc:  # pragma: no cover - 环境问题
        raise SentenceReadingError(
            "需要 pypinyin（仓库 venv 已装：.venv/bin/python）"
        ) from exc
    return pypinyin


def hanzi_pinyin(hanzi: str, *, tone_marks: bool = False) -> list[str]:
    """逐字拼音（多音字取 pypinyin 默认读音）。

    tone_marks=False → TONE3 数字声调（对齐相似度用）；tone_marks=True →
    带声调符号（láng），用于展示（sentences_scored.csv 的 pinyin_seq）。
    """
    if not hanzi:
        return []
    py = _pypinyin()
    style = py.Style.TONE if tone_marks else py.Style.TONE3
    rows = py.pinyin(hanzi, style=style, errors="default")
    return [str(item[0]) for item in rows]


_Y_TO_FINAL = {
    "i": "i", "in": "in", "ing": "ing",
    "u": "ü", "un": "ün", "ue": "üe", "uan": "üan",
    "a": "ia", "an": "ian", "ang": "iang", "ao": "iao",
    "e": "ie", "ou": "iou", "ong": "iong",
}
_W_TO_FINAL = {
    "u": "u", "a": "ua", "o": "uo", "ai": "uai", "ei": "uei",
    "an": "uan", "en": "uen", "ang": "uang", "eng": "ueng",
}
_JQX_U = {"u": "ü", "uan": "üan", "un": "ün", "ue": "üe"}
_NL_V = {"v": "ü", "ve": "üe"}


def final_from_pinyin(py: str) -> str:
    """从单个拼音（TONE3 数字调 / 声调符号 / 无声调均可）提取规范韵母。"""
    py = unicodedata.normalize("NFKC", py).strip().lower()
    py = re.sub(r"[0-9]+", "", py)
    # 声调符号：NFD 分解后只去掉声调附加符（á→a、ǜ→ü），
    # 保留分音符（ü 的分音点 U+0308），再 NFC 合成
    py = unicodedata.normalize("NFD", py)
    tone_marks = {
        "\u0300", "\u0301", "\u0302", "\u0304", "\u0306", "\u030b", "\u030c",
    }
    py = "".join(ch for ch in py if ch not in tone_marks)
    py = unicodedata.normalize("NFC", py)
    if not py:
        return ""
    if py == "er" or py == "r":
        return "er"
    # 儿化：末尾 r 且前面是元音（huar -> hua）
    if len(py) > 1 and py.endswith("r") and py[-2] in "aeiouüv":
        py = py[:-1]
    if py.startswith("y"):
        return _Y_TO_FINAL.get(py[1:], py[1:])
    if py.startswith("w"):
        return _W_TO_FINAL.get(py[1:], py[1:])
    if py[:2] in ("zh", "ch", "sh"):
        initial, rest = py[:2], py[2:]
    elif py[0] in "bpmfdtnlgkhjqxrzcs":
        initial, rest = py[0], py[1:]
    else:
        initial, rest = "", py
    if initial in ("j", "q", "x") and rest in _JQX_U:
        rest = _JQX_U[rest]
    if initial in ("n", "l") and rest in _NL_V:
        rest = _NL_V[rest]
    if rest == "i" and initial in ("z", "c", "s"):
        return "-i_front"
    if rest == "i" and initial in ("zh", "ch", "sh", "r"):
        return "-i_back"
    if rest == "iu":
        return "iou"
    if rest == "ui":
        return "uei"
    if rest == "un":
        return "uen"
    return rest


def nasal_label_of_final(final: str) -> str:
    if final in FRONT_NASAL_FINALS:
        return FRONT_LABEL
    if final in BACK_NASAL_FINALS:
        return BACK_LABEL
    return OTHER_LABEL


def score_sentence(text: str) -> dict[str, Any]:
    """逐字拼音 / 韵母 / 前后鼻音标注 + 每句指标。

    pinyin_seq 用带声调符号的拼音（展示用，如 láng）；对齐相似度内部
    仍用 TONE3 数字调（见 hanzi_pinyin）。
    """
    hanzi = "".join(ch for ch in text if is_hanzi(ch))
    pys = hanzi_pinyin(hanzi, tone_marks=True)
    finals = [final_from_pinyin(p) for p in pys]
    labels = [nasal_label_of_final(f) for f in finals]
    front = labels.count(FRONT_LABEL)
    back = labels.count(BACK_LABEL)
    nasal = front + back
    total = len(finals)
    density = round(nasal / total, 4) if total else 0.0
    return {
        "char_count": len(hanzi),
        "syllable_count": total,
        "pinyin_seq": " ".join(pys),
        "final_seq": " ".join(finals),
        "label_seq": "".join(labels),
        "char_final_pairs": "|".join(
            f"{ch}={fin}" for ch, fin in zip(hanzi, finals)
        ),
        "front_count": front,
        "back_count": back,
        "nasal_count": nasal,
        "nasal_density": density,
        "front_ratio": round(front / nasal, 4) if nasal else 0.0,
        "back_ratio": round(back / nasal, 4) if nasal else 0.0,
        "distinct_finals": "|".join(sorted(set(finals))),
    }


# ---------------------------------------------------------------------------
# 筛选口径（达标即收，无上限；阈值参数化）
# ---------------------------------------------------------------------------

def select_reason(
    metrics: dict[str, Any],
    min_density: float = 0.25,
    short_max_chars: int = 25,
    short_min_nasal: int = 4,
    min_chars: int = 8,
) -> str | None:
    # 人耳反馈：3–7 字的碎片（如「潮在涨」「怎么不珍惜呀」）不是句子，
    # 且短切片边界必错——低于最小字数直接不收
    if metrics["char_count"] < min_chars:
        return None
    if metrics["nasal_density"] >= min_density:
        return "density"
    if (
        metrics["char_count"] <= short_max_chars
        and metrics["nasal_count"] >= short_min_nasal
    ):
        return "short_dense"
    return None


# ---------------------------------------------------------------------------
# P1：PDF 提取 + 断句
# ---------------------------------------------------------------------------

def extract_pdf_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    """用 pymupdf 逐页提取纯文本（惰性导入，缺依赖时报错并给出提示）。"""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - 环境问题
        raise SentenceReadingError(
            "需要 pymupdf（本机 /opt/miniconda3/bin/python 已装；"
            "可先导出 pages JSONL 后用 --pages 走无 PDF 路径）"
        ) from exc
    doc = pymupdf.open(str(pdf_path))
    pages: list[dict[str, Any]] = []
    for pno in range(doc.page_count):
        pages.append({"page": pno + 1, "text": doc[pno].get_text("text")})
    doc.close()
    return pages


def load_pages_file(pages_path: str | Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    with open(pages_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pages.append(row)
    return pages


def _audio_file_map(audio_dir: Path) -> dict[str, str]:
    """音频目录文件名（规范化后）→ 文件名；含 mp3/mp4/wav。"""
    mapping: dict[str, str] = {}
    if not audio_dir.is_dir():
        return mapping
    for path in sorted(audio_dir.iterdir()):
        if path.suffix.lower() not in {".mp3", ".mp4", ".wav"}:
            continue
        key = norm_hanzi(path.stem)
        if key:
            mapping.setdefault(key, path.name)
    return mapping


def article_slug(page: int, title: str) -> str:
    """文章编号：页码（2 位）+ 规范化标题（可读、确定性、无 pypinyin 依赖）。"""
    hanzi = norm_hanzi(title)[:16]
    return f"{page:02d}-{hanzi}"


def run_extract(
    *,
    pdf_path: str | Path | None = None,
    pages: Sequence[dict[str, Any]] | None = None,
    pages_file: str | Path | None = None,
    audio_dir: str | Path = DEFAULT_AUDIO_DIR,
    out_dir: str | Path = DEFAULT_OUT,
) -> dict[str, Any]:
    """PDF/pages → articles.jsonl + sentences.jsonl。"""
    if pages is None:
        if pages_file is not None:
            pages = load_pages_file(pages_file)
        elif pdf_path is not None:
            pages = extract_pdf_pages(pdf_path)
        else:
            raise SentenceReadingError("extract 需要 --pdf 或 --pages")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    audio_map = _audio_file_map(Path(audio_dir))

    articles: list[dict[str, Any]] = []
    sentences: list[dict[str, Any]] = []
    missing_audio: list[str] = []
    for row in pages:
        page = int(row["page"])
        title, body = parse_page_text(str(row["text"]))
        if title is None:
            raise SentenceReadingError(
                f"第 {page} 页未找到《标题》行，请检查页面文本格式"
            )
        key = norm_hanzi(title)
        audio_key = norm_hanzi(TITLE_AUDIO_VARIANTS.get(title, title))
        audio_file = audio_map.get(audio_key)
        article_id = article_slug(page, title)
        if audio_file is None:
            missing_audio.append(f"{article_id}（{title}）")
        sents = split_sentences(body)
        char_count = sum(any(is_hanzi(c) for c in s) for s in sents)
        # 字数按句内汉字计
        body_chars = norm_hanzi(body)
        articles.append(
            {
                "article_id": article_id,
                "page": page,
                "title": title,
                "audio_file": audio_file,
                "audio_ext": Path(audio_file).suffix.lower() if audio_file else None,
                "has_audio": audio_file is not None,
                "char_count": len(body_chars),
                "sentence_count": len(sents),
            }
        )
        for seq, sent in enumerate(sents, start=1):
            sentences.append(
                {
                    "sentence_id": f"{article_id}-{seq:04d}",
                    "article_id": article_id,
                    "page": page,
                    "seq": seq,
                    "text": sent,
                    "char_count": len(norm_hanzi(sent)),
                }
            )
        if char_count == 0:  # 正文无汉字（防呆）
            raise SentenceReadingError(f"{article_id} 正文为空，检查断句逻辑")

    articles_path = out / "articles.jsonl"
    sentences_path = out / "sentences.jsonl"
    _write_jsonl(articles_path, articles)
    _write_jsonl(sentences_path, sentences)
    summary = {
        "command": "sentence",
        "operation": "extract",
        "status": "succeeded",
        "articles": len(articles),
        "sentences": len(sentences),
        "articles_with_audio": sum(1 for a in articles if a["has_audio"]),
        "missing_audio": missing_audio,
        "articles_path": str(articles_path),
        "sentences_path": str(sentences_path),
    }
    return summary


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# P2：拼音 / 前后鼻音分析 + 筛选
# ---------------------------------------------------------------------------

SCORED_CSV_COLUMNS = [
    "sentence_id", "article_id", "page", "seq", "text", "char_count",
    "syllable_count", "pinyin_seq", "final_seq", "label_seq",
    "char_final_pairs", "front_count", "back_count", "nasal_count",
    "nasal_density", "front_ratio", "back_ratio", "distinct_finals",
    "selected", "select_reason",
]


def run_score(
    *,
    out_dir: str | Path = DEFAULT_OUT,
    min_density: float = 0.25,
    short_max_chars: int = 25,
    short_min_nasal: int = 4,
    min_chars: int = 8,
) -> dict[str, Any]:
    """读 sentences.jsonl → 逐句指标 + 筛选 → sentences_scored.csv 等。"""
    out = Path(out_dir)
    sentences = _read_jsonl(out / "sentences.jsonl")
    if not sentences:
        raise SentenceReadingError(
            "sentences.jsonl 为空，请先运行 `sentence extract`"
        )
    rows: list[dict[str, Any]] = []
    benchmark_found = False
    benchmark_selected = False
    selected_count = 0
    for sent in sentences:
        metrics = score_sentence(sent["text"])
        reason = select_reason(
            metrics,
            min_density=min_density,
            short_max_chars=short_max_chars,
            short_min_nasal=short_min_nasal,
            min_chars=min_chars,
        )
        row = {
            "sentence_id": sent["sentence_id"],
            "article_id": sent["article_id"],
            "page": sent["page"],
            "seq": sent["seq"],
            "text": sent["text"],
            **metrics,
            "selected": reason is not None,
            "select_reason": reason or "",
        }
        rows.append(row)
        if reason:
            selected_count += 1
        if norm_hanzi(sent["text"]) == norm_hanzi(BENCHMARK_SENTENCE):
            benchmark_found = True
            benchmark_selected = row["selected"]

    csv_path = out / "sentences_scored.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCORED_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    polyphones = _collect_polyphones(sentences, rows)
    poly_path = out / "polyphones.csv"
    with open(poly_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["char", "readings", "article_id", "page",
                            "occurrences", "occurrences_selected"]
        )
        writer.writeheader()
        writer.writerows(polyphones)

    summary = {
        "command": "sentence",
        "operation": "score",
        "status": "succeeded",
        "sentences": len(rows),
        "selected": selected_count,
        "selection": {
            "min_density": min_density,
            "short_max_chars": short_max_chars,
            "short_min_nasal": short_min_nasal,
            "min_chars": min_chars,
        },
        "benchmark_sentence": {
            "found": benchmark_found,
            "selected": benchmark_selected,
            "normalized": norm_hanzi(BENCHMARK_SENTENCE),
        },
        "polyphones": len(polyphones),
        "scored_csv": str(csv_path),
        "polyphones_csv": str(poly_path),
    }
    summary_path = out / "score_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return summary


def _collect_polyphones(
    sentences: Sequence[dict[str, Any]], rows: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """多音字清单（pypinyin heteronym>1 的字），供抽检。"""
    py = _pypinyin()
    by_article: dict[str, dict[str, Any]] = {}
    selected_by_article: dict[str, set[str]] = {}
    selected_map = {r["sentence_id"]: r["selected"] for r in rows}
    for sent in sentences:
        article = sent["article_id"]
        chars = norm_hanzi(sent["text"])
        bucket = by_article.setdefault(
            article,
            {"article_id": article, "page": sent["page"], "chars": {}},
        )
        sel = selected_by_article.setdefault(article, set())
        for ch in chars:
            bucket["chars"].setdefault(ch, 0)
            bucket["chars"][ch] += 1
            if selected_map.get(sent["sentence_id"]):
                sel.add(ch)
    records: list[dict[str, Any]] = []
    for article, bucket in sorted(by_article.items()):
        for ch, count in sorted(bucket["chars"].items()):
            readings = py.pinyin(ch, style=py.Style.TONE3, heteronym=True)[0]
            if len(readings) <= 1:
                continue
            records.append(
                {
                    "char": ch,
                    "readings": "/".join(readings),
                    "article_id": article,
                    "page": bucket["page"],
                    "occurrences": count,
                    "occurrences_selected": (
                        count if ch in selected_by_article[article] else 0
                    ),
                }
            )
    return records


# ---------------------------------------------------------------------------
# P3：对齐（whisper 分段 + 双通道模糊匹配 + 句序单调）
# ---------------------------------------------------------------------------

def _seg_chars_and_pinyin(seg: dict[str, Any]) -> tuple[str, list[str]]:
    chars = norm_hanzi(str(seg.get("text", "")))
    return chars, hanzi_pinyin(chars)


def _len_penalty(len_ratio: float) -> float:
    if TIER_LEN_RATIO_OK[0] <= len_ratio <= TIER_LEN_RATIO_OK[1]:
        return 1.0
    excess = abs(math.log2(max(len_ratio, 0.02)))
    return max(0.0, 1.0 - 0.4 * (excess - 0.5))


def align_article(
    sentences: Sequence[dict[str, Any]],
    segments: Sequence[dict[str, Any]],
    char_weight: float = 0.35,
) -> list[dict[str, Any]]:
    """对一篇文章的句子序列做字符级滑动窗口单调对齐。

    归一化（去标点/空白）后，把 whisper 分段拼成带时间戳的字符流，
    对每句做滑动窗口模糊匹配：得分 = char_weight*字符相似度 +
    (1-char_weight)*拼音相似度（拼音通道吸收 whisper 的繁体/同音字误差），
    乘以窗口长度比惩罚；再用动态规划施加句序单调性约束
    （后句窗口起点不早于前句窗口起点，结束点亦不早于前句）。
    窗口确定后用 SequenceMatcher 匹配块把起止细化到字符级
    （吸收段内相邻句粘连），返回每句 {start, end, score, tier, ...}。
    """
    segs = [dict(s) for s in segments]
    char_parts: list[str] = []
    per_char_pys: list[str] = []
    char_starts: list[float] = []
    char_ends: list[float] = []
    for seg in segs:
        chars, pys = _seg_chars_and_pinyin(seg)
        char_parts.append(chars)
        per_char_pys.extend(pys)
        n_chars = max(1, len(chars))
        s = float(seg["start"])
        d = max(0.001, float(seg["end"]) - s)
        words = seg.get("words") or []
        word_chars = norm_hanzi("".join(w.get("word", "") for w in words))
        if words and word_chars == chars:
            # 词级时间戳：每词时长按词内字数均分（精度远高于段级均分）
            for w in words:
                wchars = norm_hanzi(w.get("word", ""))
                wn = max(1, len(wchars))
                ws = float(w["start"])
                we = float(w["end"])
                for k in range(len(wchars)):
                    char_starts.append(ws + (we - ws) * k / wn)
                    char_ends.append(ws + (we - ws) * (k + 1) / wn)
        else:
            for k in range(n_chars):
                char_starts.append(s + k * d / n_chars)
                char_ends.append(s + (k + 1) * d / n_chars)
    char_stream = "".join(char_parts)
    total = len(char_stream)
    # 拼音前缀位置：窗口拼音 O(1) 切片
    pys_pos: list[int] = [0]
    for py in per_char_pys:
        pys_pos.append(pys_pos[-1] + len(py) + 1)
    pys_stream = " ".join(per_char_pys) + " "
    sents = []
    for sent in sentences:
        chars = norm_hanzi(sent["text"])
        pys = hanzi_pinyin(chars)
        sents.append(
            {
                "sentence_id": sent["sentence_id"],
                "text": sent["text"],
                "chars": chars,
                "pys": pys,
                "pys_str": " ".join(pys),
            }
        )
    if total == 0:
        return [
            _align_miss(sent, reason="no_segments")
            for sent in sents
        ]

    n = len(sents)
    neg = -1e9
    # cands[i] = [(start, end, combined, char_sim, pinyin_sim)]
    cands: list[list[tuple[int, int, float, float, float]]] = []
    for sent in sents:
        target = max(1, len(sent["chars"]))
        lo = max(2, int(target * 0.4))
        hi = min(total, int(target * 2.6) + 1)
        step = 1 if target <= 24 else 2
        cand: list[tuple[int, int, float, float, float]] = []
        # 锚点剪枝：句首 2 字（字符或拼音）命中才评估该起点，
        # 起点允许比真实句首早 0–2 字（whisper 段首杂音）
        head_chars = sent["chars"][:2]
        head_pys = sent["pys"][:2]
        for s in range(0, total, step):
            hit = False
            for shift in (0, 1, 2):
                if s + shift + 2 > total:
                    break
                if char_stream[s + shift:s + shift + 2] == head_chars:
                    hit = True
                    break
                if per_char_pys[s + shift:s + shift + 2] == head_pys:
                    hit = True
                    break
            if not hit:
                continue
            max_e = min(total, s + hi)
            for e in range(s + lo, max_e + 1, step):
                window = char_stream[s:e]
                char_sim = difflib.SequenceMatcher(
                    None, sent["chars"], window, autojunk=False
                ).ratio()
                pinyin_sim = difflib.SequenceMatcher(
                    None,
                    sent["pys_str"],
                    pys_stream[pys_pos[s]:pys_pos[e]].strip(),
                    autojunk=False,
                ).ratio()
                len_ratio = (e - s) / target
                combined = (
                    char_weight * char_sim + (1 - char_weight) * pinyin_sim
                ) * _len_penalty(len_ratio)
                cand.append((s, e, combined, char_sim, pinyin_sim))
        if not cand:
            # 锚点全落空（whisper 把句首听错）：按句首字拼音出现位置
            # 探测（±2 字移位，命中位置过多时均匀抽样 ≤30 个）
            head_py = sent["pys"][0] if sent["pys"] else ""
            starts: list[int] = []
            if head_py:
                for s in range(0, max(0, total - 1)):
                    if per_char_pys[s] == head_py:
                        starts.append(s)
                if len(starts) > 30:
                    starts = starts[:: max(1, len(starts) // 30)][:30]
            for s0 in starts:
                for s in (s0, s0 + 1, s0 + 2):
                    if s < 0 or s + lo > total:
                        continue
                    max_e = min(total, s + hi)
                    for e in range(s + lo, max_e + 1, step):
                        window = char_stream[s:e]
                        char_sim = difflib.SequenceMatcher(
                            None, sent["chars"], window, autojunk=False
                        ).ratio()
                        pinyin_sim = difflib.SequenceMatcher(
                            None,
                            sent["pys_str"],
                            pys_stream[pys_pos[s]:pys_pos[e]].strip(),
                            autojunk=False,
                        ).ratio()
                        len_ratio = (e - s) / target
                        combined = (
                            char_weight * char_sim
                            + (1 - char_weight) * pinyin_sim
                        ) * _len_penalty(len_ratio)
                        cand.append((s, e, combined, char_sim, pinyin_sim))
        cands.append(cand)

    # dp[i][e] = (总分, 起点 s)；转移约束：当前句起点 >= 前句起点
    # 无候选的句子跳过（不占窗口，不阻断后续句的单调链）
    skipped = [False] * n
    dp: list[list[tuple[float, int] | None]] = [
        [None] * (total + 1) for _ in range(n)
    ]
    for i, cand in enumerate(cands):
        if not cand:
            skipped[i] = True
            if i > 0:
                dp[i] = list(dp[i - 1])
            continue
        if i == 0:
            for s, e, sc, _, _ in cand:
                cur = dp[i][e]
                # 平局保留最早窗口（严格 >）
                if cur is None or sc > cur[0]:
                    dp[i][e] = (sc, s)
        else:
            prev = dp[i - 1]
            pref = [neg] * (total + 1)
            best = neg
            any_prev = False
            for x in range(total + 1):
                v = prev[x][0] if prev[x] is not None else neg
                if prev[x] is not None:
                    any_prev = True
                if v > best:
                    best = v
                pref[x] = best
            # 前句全部无候选时，视作 0 分起点，不阻断本句
            for s, e, sc, _, _ in cand:
                if not any_prev:
                    total_sc = sc
                else:
                    if pref[s] <= neg / 2:
                        continue
                    total_sc = sc + pref[s]
                cur = dp[i][e]
                # 平局保留更晚窗口（>=），推动相同句向前移动
                if cur is None or total_sc >= cur[0]:
                    dp[i][e] = (total_sc, s)

    # 回溯：句序单调（前句起点 <= 后句起点由转移保证；前句终点 <= 后句终点）
    chosen: list[tuple[int, int] | None] = [None] * n
    e_limit = total
    for i in range(n - 1, -1, -1):
        if skipped[i]:
            chosen[i] = None
            continue
        row = dp[i]
        best_e, best_val, best_s = -1, neg, -1
        for e in range(min(e_limit, total) + 1):
            if row[e] is None:
                continue
            # 最后一个非跳过句平局取更晚窗口（>=），其余取更早窗口（严格 >）
            is_last = not any(
                (not skipped[j]) and chosen[j] is not None
                for j in range(i + 1, n)
            )
            better = row[e][0] >= best_val if is_last else row[e][0] > best_val
            if better:
                best_e, best_val, best_s = e, row[e][0], row[e][1]
        if best_e < 0:
            chosen[i] = None
            continue
        chosen[i] = (best_s, best_e)
        e_limit = best_e

    results: list[dict[str, Any]] = []
    for i, sent in enumerate(sents):
        if chosen[i] is None:
            results.append(_align_miss(sent, reason="no_window"))
            continue
        s, e = chosen[i]
        refined = _refine_window(
            sent["chars"], sent["pys_str"], char_stream[s:e], s,
            char_starts, char_ends, char_weight=char_weight,
        )
        refined["sentence_id"] = sent["sentence_id"]
        refined["text"] = sent["text"]
        refined["window"] = [s, e]
        results.append(refined)
    _couple_adjacent_seams(results, char_starts, char_ends)
    return results


def _couple_adjacent_seams(
    results: list[dict[str, Any]],
    char_starts: Sequence[float],
    char_ends: Sequence[float],
) -> None:
    """相邻句缝合：按真实字数把两句之间的未匹配字缝归位。

    whisper 常把本句句尾音节听成同音字（参天→餐廳、响着→…），这些字
    落在两句匹配块之间的缝里；偶尔也把句首字听错。规则：用每句的真实
    字数（sentences 里的 char_count）与匹配块长度算出各句「缺字」数，
    缺字的句子拿走自己缺的字：
    - 后句不缺字 → 缝全部归前句（前句句尾不截断，后句句首不带杂音）；
    - 前句不缺字 → 缝全部归后句；
    - 两句都缺 → 按缺字比例分；都不缺 → 缝是 whisper 填充音，两不沾。
    相邻两句（置信度均 ≥mid）匹配块间隔 0–12 字时生效。
    """
    for i in range(len(results) - 1):
        cur = results[i]
        nxt = results[i + 1]
        b1 = cur.get("match_b1")
        b0 = nxt.get("match_b0")
        if b1 is None or b0 is None or b1 < 0 or b0 < 0:
            continue
        if cur.get("score", 0.0) < TIER_MID_MIN_SCORE:
            continue
        if nxt.get("score", 0.0) < TIER_MID_MIN_SCORE:
            continue
        gap = b0 - b1 - 1
        if not 0 <= gap <= 12:
            continue
        cur_len = len(norm_hanzi(cur.get("text", "")))
        nxt_len = len(norm_hanzi(nxt.get("text", "")))
        cur_b0 = cur.get("match_b0", b1)
        nxt_b1 = nxt.get("match_b1", b0)
        cur_missing = max(0, cur_len - (b1 - cur_b0 + 1))
        nxt_missing = max(0, nxt_len - (nxt_b1 - b0 + 1))
        give_cur = min(cur_missing, gap)
        give_next = min(nxt_missing, gap - give_cur)
        # 剩余缝是填充音：两不沾（留给 0.15s 缓冲）
        end = char_ends[b1 + give_cur] if give_cur > 0 else char_ends[b1]
        start = (
            char_starts[b0 - give_next] if give_next > 0 else char_starts[b0]
        )
        if end is None or start is None:
            continue
        cur["end"] = round(end, 3)
        cur["duration"] = round(max(0.0, end - cur["start"]), 3)
        nxt["start"] = round(start, 3)
        nxt["duration"] = round(max(0.0, nxt["end"] - start), 3)
        cur["seam_coupled"] = True
        nxt["seam_coupled"] = True


def _refine_window(
    sent_chars: str,
    sent_pys_str: str,
    window_chars: str,
    g0: int,
    char_starts: Sequence[float],
    char_ends: Sequence[float],
    char_weight: float = 0.35,
) -> dict[str, Any]:
    """把字符级窗口细化到匹配块包络（返回 match_b0/match_b1 供句间缝合）。

    时间边界取「匹配块边缘与相邻未匹配字」的中点：
    - 起点：首匹配字与其前 1 字的起始边中点（首字已匹配则取首字起始边）；
    - 终点：末匹配字与其后 1 字的结束边中点（末字已匹配则取末字结束边）。
    中点制兼顾两头：既不让邻句音节整字混入，也不因句首/句尾同音字
    误差把本句音节整字切掉（残差再交给句间缝合与 0.15s 缓冲吸收）。
    """
    if not window_chars:
        return {
            "matched_text": "", "start": 0.0, "end": 0.0, "duration": 0.0,
            "score": 0.0, "char_sim": 0.0, "pinyin_sim": 0.0,
            "len_ratio": 0.0, "tier": "low", "reason": "empty_window",
        }
    sm = difflib.SequenceMatcher(None, sent_chars, window_chars, autojunk=False)
    positions = [
        pos
        for (_, start, size) in sm.get_matching_blocks()
        if size > 0
        for pos in range(start, start + size)
    ]
    if positions:
        first, last = min(positions), max(positions)
        m0 = max(0, first - 1)  # 文本含 1 字余量（仅用于相似度/长度比）
        m1 = min(len(window_chars), last + 2)
        # 时间边界：边缘中点
        if first > 0:
            start = (
                char_starts[g0 + first - 1] + char_starts[g0 + first]
            ) / 2
        else:
            start = char_starts[g0]
        if last + 1 < len(window_chars):
            end = (char_ends[g0 + last] + char_ends[g0 + last + 1]) / 2
        else:
            end = char_ends[g0 + last]
        match_b0 = g0 + first
        match_b1 = g0 + last
    else:
        m0, m1 = 0, len(window_chars)
        start = char_starts[g0] if g0 < len(char_starts) else 0.0
        end = (
            char_ends[g0 + len(window_chars) - 1]
            if g0 + len(window_chars) - 1 < len(char_ends)
            else start
        )
        match_b0 = match_b1 = -1
    trimmed = window_chars[m0:m1]
    trimmed_pys = " ".join(hanzi_pinyin(trimmed))
    char_sim = difflib.SequenceMatcher(
        None, sent_chars, trimmed, autojunk=False
    ).ratio()
    pinyin_sim = difflib.SequenceMatcher(
        None, sent_pys_str, trimmed_pys, autojunk=False
    ).ratio()
    len_ratio = len(trimmed) / max(1, len(sent_chars))
    combined = (
        char_weight * char_sim + (1 - char_weight) * pinyin_sim
    ) * _len_penalty(len_ratio)
    return {
        "matched_text": trimmed,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(max(0.0, end - start), 3),
        "score": round(combined, 4),
        "char_sim": round(char_sim, 4),
        "pinyin_sim": round(pinyin_sim, 4),
        "len_ratio": round(len_ratio, 4),
        "match_b0": match_b0,
        "match_b1": match_b1,
        "tier": _score_tier(combined, len_ratio),
    }


def _score_tier(score: float, len_ratio: float) -> str:
    if score >= TIER_HIGH_MIN_SCORE and (
        TIER_LEN_RATIO_OK[0] <= len_ratio <= TIER_LEN_RATIO_OK[1]
    ):
        return "high"
    if score >= TIER_MID_MIN_SCORE:
        return "mid"
    return "low"


def _align_miss(sent: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "sentence_id": sent["sentence_id"],
        "text": sent["text"],
        "matched_text": "",
        "start": 0.0,
        "end": 0.0,
        "duration": 0.0,
        "score": 0.0,
        "char_sim": 0.0,
        "pinyin_sim": 0.0,
        "len_ratio": 0.0,
        "segments": [],
        "tier": "low",
        "reason": reason,
    }


def run_align(
    *,
    out_dir: str | Path = DEFAULT_OUT,
    transcripts_dir: str | Path | None = None,
    articles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """读 transcripts/{article}.jsonl → 对齐全部句子 → aligned.jsonl + review CSV。"""
    out = Path(out_dir)
    trans_dir = Path(transcripts_dir) if transcripts_dir else out / "transcripts"
    sentences = _read_jsonl(out / "sentences.jsonl")
    if not sentences:
        raise SentenceReadingError("缺少 sentences.jsonl，请先运行 extract")
    article_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    target_ids = set(articles) if articles else None
    for article_id in sorted({s["article_id"] for s in sentences}):
        if target_ids is not None and article_id not in target_ids:
            continue
        trans_path = trans_dir / f"{article_id}.jsonl"
        if not trans_path.is_file():
            skipped.append(article_id)
            continue
        segs = _read_jsonl(trans_path)
        sents = [s for s in sentences if s["article_id"] == article_id]
        article_rows.extend(align_article(sents, segs))

    aligned_path = out / "alignment" / "aligned.jsonl"
    aligned_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(aligned_path, article_rows)

    review_rows = [
        r for r in article_rows
        if r.get("tier", "low") in {"mid", "low"}
        and r.get("duration", 0.0) > 0.0
    ]
    articles_map = {a["article_id"]: a for a in _read_jsonl(out / "articles.jsonl")}
    review_path = out / "alignment" / "alignment_review.csv"
    with open(review_path, "w", encoding="utf-8", newline="") as fh:
        fields = [
            "sentence_id", "article_id", "title", "source_file", "text",
            "matched_text", "score", "char_sim", "pinyin_sim", "len_ratio",
            "start", "end", "tier",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in review_rows:
            row = dict(row)
            article_id = row["sentence_id"].rsplit("-", 1)[0]
            row["article_id"] = article_id
            article = articles_map.get(article_id, {})
            row["title"] = article.get("title", "")
            row["source_file"] = article.get("audio_file", "")
            writer.writerow(row)

    tiers: dict[str, int] = {}
    for r in article_rows:
        tiers[r.get("tier", "low")] = tiers.get(r.get("tier", "low"), 0) + 1
    summary = {
        "command": "sentence",
        "operation": "align",
        "status": "succeeded",
        "aligned": len(article_rows),
        "skipped_no_transcript": skipped,
        "tiers": tiers,
        "review_queue": len(review_rows),
        "aligned_path": str(aligned_path),
        "review_csv": str(review_path),
    }
    summary_path = out / "alignment" / "align_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return summary


# ---------------------------------------------------------------------------
# P3：切分 + 机器 QA
# ---------------------------------------------------------------------------

def ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return True
    except FileNotFoundError:  # pragma: no cover
        return False


def cut_clip(
    source_path: str | Path,
    start: float,
    end: float,
    out_path: str | Path,
    pad: float = CLIP_PAD_SEC,
) -> dict[str, Any]:
    """ffmpeg 切 WAV（16k 单声道，前后 pad 秒缓冲）。"""
    source = Path(source_path)
    if not source.is_file():
        raise SentenceReadingError(f"音频不存在: {source}")
    if not ffmpeg_available():
        raise SentenceReadingError("需要 ffmpeg（/opt/homebrew/bin/ffmpeg）")
    s = max(0.0, start - pad)
    e = max(s + 0.2, end + pad)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{s:.3f}", "-i", str(source),
        "-t", f"{e - s:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not out_path.is_file():
        raise SentenceReadingError(
            f"ffmpeg 切分失败: {out_path.name}: "
            f"{proc.stderr.decode(errors='replace')[:200]}"
        )
    duration = ffprobe_duration(out_path)
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return {
        "source": source.name,
        "src_start": round(s, 3),
        "src_end": round(e, 3),
        "clip_duration": round(duration, 3),
        "sha256": digest,
    }


def ffprobe_duration(path: str | Path) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=nw=1:nk=1", str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return float(proc.stdout.decode().strip())
    except (subprocess.SubprocessError, ValueError) as exc:
        raise SentenceReadingError(f"ffprobe 失败: {path}") from exc


def silence_ratio(path: str | Path) -> float:
    """静音占比（silencedetect，-40dB，最短 0.3s；尾段未闭合静音计到片尾）。"""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(path), "-af",
            "silencedetect=noise=-40dB:d=0.3", "-f", "null", "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    text = proc.stderr.decode(errors="replace")
    starts = [
        float(m.group(1))
        for m in re.finditer(r"silence_start:\s*([0-9.]+)", text)
    ]
    ends = [
        float(m.group(1))
        for m in re.finditer(r"silence_end:\s*([0-9.]+)", text)
    ]
    duration = ffprobe_duration(path)
    total = 0.0
    for s, e in zip(starts, ends):
        total += max(0.0, e - s)
    if len(starts) > len(ends):  # 片尾未闭合的静音
        total += max(0.0, duration - starts[-1])
    return round(total / duration, 4) if duration > 0 else 1.0


def _cut_bounds(
    row: dict[str, Any],
    article_aligned: Sequence[dict[str, Any]],
    sent_id: str,
) -> tuple[float, float]:
    """邻句钳制的切分边界。

    0.15s 缓冲（≈半个音节），且不越过邻句边界（只信 mid 以上置信度的
    邻句，缝隙里留 0.05s 安全量）——人耳反馈「开头带进上一句音节 /
    结尾带进下一句音节」就由此钳制吸收；缝合后的相邻句边界相等，
    缓冲自动落在句内。短句保底 1.5s：过短时向两侧各扩最多 0.35s
    （优先能听清整句，超短句无法避免的微小邻句混入以保底为先）。
    """
    start = float(row["start"])
    end = float(row["end"])
    idx = next(
        (
            i
            for i, r in enumerate(article_aligned)
            if r["sentence_id"] == sent_id
        ),
        -1,
    )
    prev_end: float | None = None
    next_start: float | None = None
    if idx > 0:
        prev = article_aligned[idx - 1]
        if (
            prev.get("score", 0.0) >= TIER_MID_MIN_SCORE
            and prev.get("duration", 0.0) > 0
        ):
            prev_end = float(prev["end"])
    if 0 <= idx < len(article_aligned) - 1:
        nxt = article_aligned[idx + 1]
        if (
            nxt.get("score", 0.0) >= TIER_MID_MIN_SCORE
            and nxt.get("duration", 0.0) > 0
        ):
            next_start = float(nxt["start"])
    s = start - CUT_PAD_SEC
    e = end + CUT_PAD_SEC
    # 缓冲最多占「到邻句边界的缝隙」的一半：缝隙大→缓冲全量；
    # 缝隙小→缓冲相应收窄；缝合后边界相邻（缝隙=0）→只留 0.02s 起势，
    # 绝不越过邻句边界（人耳反馈的邻句音节混入由此根治）
    if prev_end is not None and prev_end <= start:
        gap_s = max(0.0, start - prev_end)
        s = start - min(CUT_PAD_SEC, max(0.02, gap_s / 2))
    if next_start is not None and next_start >= end:
        gap_e = max(0.0, next_start - end)
        e = end + min(CUT_PAD_SEC, max(0.02, gap_e / 2))
    if e - s < CUT_MIN_SEC:
        deficit = CUT_MIN_SEC - (e - s)
        s = max(start - CUT_MAX_EXTEND_SEC, s - deficit / 2)
        e = min(end + CUT_MAX_EXTEND_SEC, e + deficit / 2)
    return round(max(0.0, s), 3), round(max(s + 0.1, e), 3)


def run_cut(
    *,
    out_dir: str | Path = DEFAULT_OUT,
    audio_dir: str | Path = DEFAULT_AUDIO_DIR,
    min_tier: str = "high",
    articles: Sequence[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """切分高置信入选句 → clips/ + clip_manifest.json + QA 报告。"""
    out = Path(out_dir)
    if not ffmpeg_available():
        raise SentenceReadingError("需要 ffmpeg（/opt/homebrew/bin/ffmpeg）")
    articles_rows = _read_jsonl(out / "articles.jsonl")
    article_map = {a["article_id"]: a for a in articles_rows}
    scored = _read_csv_rows(out / "sentences_scored.csv")
    selected_ids = {r["sentence_id"] for r in scored if r["selected"] == "True"}
    aligned = {
        r["sentence_id"]: r for r in _read_jsonl(out / "alignment" / "aligned.jsonl")
    }
    # 每篇按句序排列的对齐行（句间边界钳制用）
    aligned_by_article: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(aligned.values(), key=lambda r: r["sentence_id"]):
        aligned_by_article.setdefault(
            row["sentence_id"].rsplit("-", 1)[0], []
        ).append(row)
    target_ids = set(articles) if articles else None

    tier_ok = {"high"} if min_tier == "high" else {"high", "mid"}
    manifest: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for sent_id in sorted(selected_ids):
        art_id = sent_id.rsplit("-", 1)[0]
        if target_ids is not None and art_id not in target_ids:
            continue
        align_row = aligned.get(sent_id)
        article = article_map.get(art_id)
        if align_row is None or article is None:
            failures.append({"sentence_id": sent_id, "reason": "no_alignment"})
            continue
        if align_row.get("tier") not in tier_ok:
            continue
        if not article.get("has_audio"):
            failures.append({"sentence_id": sent_id, "reason": "no_audio"})
            continue
        source = Path(audio_dir) / article["audio_file"]
        wav_rel = f"clips/{art_id}/{sent_id}.wav"
        wav_path = out / wav_rel
        if dry_run:
            continue
        start, end = _cut_bounds(
            align_row, aligned_by_article.get(art_id, []), sent_id
        )
        try:
            info = cut_clip(source, start, end, wav_path, pad=0.0)
        except SentenceReadingError as exc:
            failures.append({"sentence_id": sent_id, "reason": str(exc)})
            continue
        manifest.append(
            {
                "sentence_id": sent_id,
                "article_id": art_id,
                "wav_rel": wav_rel,
                "source_file": info["source"],
                "src_start": info["src_start"],
                "src_end": info["src_end"],
                "clip_duration": info["clip_duration"],
                "sha256": info["sha256"],
                "confidence": align_row.get("score"),
                "tier": align_row.get("tier"),
                "whisper_text": align_row.get("matched_text", ""),
            }
        )

    if not dry_run:
        manifest_path = out / "clip_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    qa = machine_qa(manifest, out) if manifest else _empty_qa()
    qa["failures"] = failures
    qa_path = out / "qa_report.json"
    with open(qa_path, "w", encoding="utf-8") as fh:
        json.dump(qa, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    sample_path = out / "qa_sample_30.csv"
    if manifest:
        rng = random.Random(QA_SAMPLE_SEED)
        sample = rng.sample(manifest, min(QA_SAMPLE_SIZE, len(manifest)))
        with open(sample_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=[
                    "sentence_id", "article_id", "wav_rel", "clip_duration",
                    "confidence", "text",
                ]
            )
            writer.writeheader()
            for row in sorted(sample, key=lambda r: r["sentence_id"]):
                writer.writerow(
                    {
                        "sentence_id": row["sentence_id"],
                        "article_id": row["article_id"],
                        "wav_rel": row["wav_rel"],
                        "clip_duration": row["clip_duration"],
                        "confidence": row["confidence"],
                        "text": (
                            scored_by_id(scored, row["sentence_id"]) or ""
                        ),
                    }
                )

    summary = {
        "command": "sentence",
        "operation": "cut",
        "status": "succeeded",
        "clips": len(manifest),
        "dry_run": dry_run,
        "qa": qa,
    }
    return summary


def scored_by_id(scored: Sequence[dict[str, str]], sent_id: str) -> str | None:
    for row in scored:
        if row.get("sentence_id") == sent_id:
            return row.get("text")
    return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _empty_qa() -> dict[str, Any]:
    return {
        "status": "passed",
        "clips_checked": 0,
        "duration_out_of_range": [],
        "high_silence": [],
        "non_monotonic": [],
        "missing_files": [],
        "duplicate_hashes": 0,
        "tier_counts": {},
        "failures": [],
    }


def machine_qa(
    manifest: Sequence[dict[str, Any]], wav_root: Path
) -> dict[str, Any]:
    """机器 QA：时长 1–15s、静音比、哈希重复、区间单调性。"""
    bad_duration = [
        r["sentence_id"] for r in manifest
        if not (CLIP_MIN_SEC <= r["clip_duration"] <= CLIP_MAX_SEC)
    ]
    high_silence: list[str] = []
    for r in manifest:
        wav = wav_root / r["wav_rel"]
        if not wav.is_file():
            continue
        ratio = silence_ratio(wav)
        if ratio > 0.6:
            high_silence.append(f"{r['sentence_id']}:{ratio:.2f}")
    by_article: dict[str, list[dict[str, Any]]] = {}
    for r in manifest:
        by_article.setdefault(r["article_id"], []).append(r)
    non_monotonic: list[str] = []
    for article, rows in by_article.items():
        ordered = sorted(rows, key=lambda r: r["src_start"])
        prev = -1.0
        for r in ordered:
            if r["src_start"] < prev - 0.25:
                non_monotonic.append(
                    f"{article}:{r['sentence_id']}@{r['src_start']:.2f}"
                )
            prev = max(prev, r["src_start"])
    hashes = [r["sha256"] for r in manifest]
    dup_count = len(hashes) - len(set(hashes))
    tiers: dict[str, int] = {}
    for r in manifest:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    missing = [
        r["sentence_id"] for r in manifest
        if not (wav_root / r["wav_rel"]).is_file()
    ]
    return {
        # 硬门：时长越界 / 区间非单调 / 文件缺失；静音比只作提示
        # （文学朗读语速慢、停顿多，静音比偏高属正常）
        "status": (
            "passed"
            if not (bad_duration or non_monotonic or missing)
            else "failed"
        ),
        "clips_checked": len(manifest),
        "duration_out_of_range": bad_duration,
        "high_silence": high_silence,
        "non_monotonic": non_monotonic,
        "missing_files": missing,
        "duplicate_hashes": dup_count,
        "tier_counts": tiers,
    }


# ---------------------------------------------------------------------------
# 后端句子池（与 training-generator 解耦）
# ---------------------------------------------------------------------------

def load_sentence_pool(
    data_root: str | Path = "data",
    out_subdir: str | Path = DEFAULT_OUT,
) -> list[dict[str, Any]]:
    """组装训练用句子池：入选 + 已切片 + 对齐信息 + 文章出处。"""
    out = Path(data_root) / out_subdir
    articles = {a["article_id"]: a for a in _read_jsonl(out / "articles.jsonl")}
    scored = _read_csv_rows(out / "sentences_scored.csv")
    aligned = {
        r["sentence_id"]: r
        for r in _read_jsonl(out / "alignment" / "aligned.jsonl")
    }
    manifest = {}
    manifest_path = out / "clip_manifest.json"
    if manifest_path.is_file():
        with open(manifest_path, encoding="utf-8") as fh:
            for row in json.load(fh):
                manifest[row["sentence_id"]] = row
    pool: list[dict[str, Any]] = []
    for row in scored:
        if row.get("selected") != "True":
            continue
        clip = manifest.get(row["sentence_id"])
        if clip is None:
            continue
        article = articles.get(row["article_id"], {})
        align_row = aligned.get(row["sentence_id"], {})
        pool.append(
            {
                "sentence_id": row["sentence_id"],
                "article_id": row["article_id"],
                "article_title": article.get("title", ""),
                "page": int(row["page"]),
                "seq": int(row["seq"]),
                "text": row["text"],
                "char_count": int(row["char_count"]),
                "pinyin_seq": row["pinyin_seq"],
                "final_seq": row["final_seq"],
                "label_seq": row["label_seq"],
                "front_count": int(row["front_count"]),
                "back_count": int(row["back_count"]),
                "nasal_count": int(row["nasal_count"]),
                "nasal_density": float(row["nasal_density"]),
                "select_reason": row["select_reason"],
                "clip_rel": clip["wav_rel"],
                "clip_duration": clip["clip_duration"],
                "clip_sha256": clip["sha256"],
                "confidence": clip.get("confidence") or align_row.get("score"),
                "tier": clip.get("tier") or align_row.get("tier"),
            }
        )
    pool.sort(key=lambda r: (r["article_id"], r["seq"]))
    return pool


def sentence_weight(
    row: dict[str, Any], boost_finals: Sequence[str] = ()
) -> float:
    """加权随机抽句的权重：鼻音密度越高权重越大；给定目标音时，
    句中目标音越多权重越高（用户调优：前鼻为主提 en/in、后鼻为主提 eng/ing）。"""
    weight = 1.0 + 8.0 * float(row["nasal_density"])
    if boost_finals:
        hits = _target_hits(row, boost_finals)
        weight *= 1.0 + 2.0 * min(hits, 4)
    return weight


FILTER_MODES = ("all", "front", "back", "mixed", "custom")
ALL_NASAL_FINALS = tuple(FRONT_NASAL_FINALS + BACK_NASAL_FINALS)
# 各预设模式的目标音（用户调优：前鼻为主侧重 en/in、后鼻为主侧重 eng/ing，
# 前后都有侧重四个难点音；an/ang 等 a 族音不排除、随句带上）
FILTER_TARGET_FINALS: dict[str, tuple[str, ...]] = {
    "all": (),
    "front": ("en", "in"),
    "back": ("eng", "ing"),
    "mixed": ("en", "in", "eng", "ing"),
    "custom": (),
}


def _target_hits(row: dict[str, Any], targets: Sequence[str]) -> int:
    if not targets:
        return 0
    selected = set(targets)
    return sum(
        1
        for f, label in zip(row["final_seq"].split(), row["label_seq"])
        if label in (FRONT_LABEL, BACK_LABEL) and f in selected
    )


def apply_filter(pool: Sequence[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "all":
        return list(pool)
    if mode == "front":
        base = [r for r in pool if r["front_count"] > r["back_count"]]
    elif mode == "back":
        base = [r for r in pool if r["back_count"] > r["front_count"]]
    elif mode == "mixed":
        base = [
            r for r in pool
            if r["front_count"] > 0 and r["back_count"] > 0
        ]
    else:
        raise ValueError(f"unknown filter mode: {mode}")
    targets = FILTER_TARGET_FINALS.get(mode, ())
    if targets:
        base = [r for r in base if _target_hits(r, targets) >= 1]
    return base


def apply_final_filter(
    pool: Sequence[dict[str, Any]],
    finals: Sequence[str],
    min_share: float = 0.25,
) -> list[dict[str, Any]]:
    """自选音筛选：句中「所选音 ≥2 个音节」或「所选音占鼻音 ≥1/4」。

    用户反馈「带 a 的音太多、想专练 en/in/ing/ong/ün 这类难的」：
    常用音靠 ≥1/4 覆盖保住浓度（避免选中一个音却被满句 an/ian 稀释）；
    稀缺音（ün/iong/ueng 全库只有几十个音节）靠 ≥2 命中捞出仅有的
    集中句，否则任何覆盖率都凑不出句子。
    """
    selected = set(finals)
    out: list[dict[str, Any]] = []
    for row in pool:
        nasal = [
            f for f, label in zip(row["final_seq"].split(), row["label_seq"])
            if label in (FRONT_LABEL, BACK_LABEL)
        ]
        if not nasal:
            continue
        hits = sum(1 for f in nasal if f in selected)
        if hits >= 2 or (hits >= 1 and hits / len(nasal) >= min_share):
            out.append(row)
    return out


def final_distribution(
    pool: Sequence[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """每个鼻音韵母在池中的出现句数与音节数（供前端选音计数）。"""
    stats = {f: {"sentences": 0, "syllables": 0} for f in ALL_NASAL_FINALS}
    for row in pool:
        finals = row["final_seq"].split()
        labels = row["label_seq"]
        seen: set[str] = set()
        for f, label in zip(finals, labels):
            if label not in (FRONT_LABEL, BACK_LABEL):
                continue
            if f not in stats:
                continue
            stats[f]["syllables"] += 1
            seen.add(f)
        for f in seen:
            stats[f]["sentences"] += 1
    return stats


def build_session(
    pool: Sequence[dict[str, Any]],
    *,
    count: int = 10,
    filter_mode: str = "all",
    seed: int | None = None,
    include_finals: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """全库加权随机抽句（无放回）。

    include_finals 给定时按「自选音覆盖比例 ≥50%」过滤（优先于预设
    filter_mode）；否则按预设（all/front/back/mixed）过滤。
    """
    if include_finals:
        candidates = apply_final_filter(pool, include_finals)
        boost: tuple[str, ...] = tuple(include_finals)
    else:
        if filter_mode == "custom":
            raise ValueError("filter=custom 需要同时提供 include_finals")
        candidates = apply_filter(pool, filter_mode)
        boost = FILTER_TARGET_FINALS.get(filter_mode, ())
    count = min(count, len(candidates))
    rng = random.Random(seed)
    picked: list[dict[str, Any]] = []
    bag = list(candidates)
    weights = [sentence_weight(r, boost) for r in bag]
    for _ in range(count):
        total = sum(weights)
        if total <= 0:
            break
        x = rng.random() * total
        idx = 0
        acc = weights[0]
        while acc < x and idx + 1 < len(bag):
            idx += 1
            acc += weights[idx]
        picked.append(bag.pop(idx))
        weights.pop(idx)
    return picked


# ---------------------------------------------------------------------------
# 管线状态
# ---------------------------------------------------------------------------

def run_status(
    *,
    out_dir: str | Path = DEFAULT_OUT,
    audio_dir: str | Path = DEFAULT_AUDIO_DIR,
) -> dict[str, Any]:
    out = Path(out_dir)
    articles = _read_jsonl(out / "articles.jsonl")
    sentences = _read_jsonl(out / "sentences.jsonl")
    scored = _read_csv_rows(out / "sentences_scored.csv")
    aligned = _read_jsonl(out / "alignment" / "aligned.jsonl")
    trans_dir = out / "transcripts"
    transcripts = (
        sorted(p.name for p in trans_dir.glob("*.jsonl"))
        if trans_dir.is_dir() else []
    )
    manifest_path = out / "clip_manifest.json"
    manifest: list[dict[str, Any]] = []
    if manifest_path.is_file():
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    audio_map = _audio_file_map(Path(audio_dir))
    tiers: dict[str, int] = {}
    for r in aligned:
        tiers[r.get("tier", "low")] = tiers.get(r.get("tier", "low"), 0) + 1
    return {
        "command": "sentence",
        "operation": "status",
        "status": "succeeded",
        "articles": len(articles),
        "articles_with_audio": sum(1 for a in articles if a["has_audio"]),
        "audio_files_found": len(audio_map),
        "sentences": len(sentences),
        "scored": len(scored),
        "selected": sum(1 for r in scored if r.get("selected") == "True"),
        "transcripts": len(transcripts),
        "aligned": len(aligned),
        "alignment_tiers": tiers,
        "clips": len(manifest),
    }


# ---------------------------------------------------------------------------
# CLI（cli.py 的 sentence 子命令 + 模块直跑入口）
# ---------------------------------------------------------------------------

def add_sentence_parser(subparsers: Any) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "sentence",
        help="句子练习语料管线（提取/打分/对齐/切分/状态）",
        description=(
            "朗读作品句子练习管线：PDF 提取断句、前后鼻音打分筛选、"
            "whisper 对齐、ffmpeg 切分。产物在 data/derived/sentence-practice-v1/。"
        ),
    )
    sub = parser.add_subparsers(dest="sentence_command", required=True)
    _add_sentence_ops(sub)
    parser.set_defaults(_command="sentence")
    return parser


def _add_sentence_ops(sub: Any) -> None:
    p = sub.add_parser("extract", help="PDF → articles.jsonl + sentences.jsonl")
    p.add_argument("--pdf", default=None, help="朗读作品 PDF 路径（需 pymupdf）")
    p.add_argument(
        "--pages", default=None,
        help="预提取的页面 JSONL（每行 {page, text}），无 PDF 依赖",
    )
    p.add_argument("--audio-dir", default=DEFAULT_AUDIO_DIR)
    p.add_argument("--out", default=DEFAULT_OUT)

    p = sub.add_parser("score", help="拼音/前后鼻音指标 + 筛选 → CSV")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--min-density", type=float, default=0.25)
    p.add_argument("--short-max-chars", type=int, default=25)
    p.add_argument("--short-min-nasal", type=int, default=4)
    p.add_argument("--min-chars", type=int, default=8,
                   help="入选句最少字数（人耳反馈：<8 字多为碎片，默认 8）")

    p = sub.add_parser("align", help="whisper 分段 → 逐句对齐（双通道+单调）")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--transcripts-dir", default=None)
    p.add_argument("--articles", default=None,
                   help="逗号分隔的 article_id 子集（调试用）")

    p = sub.add_parser("cut", help="ffmpeg 切分高置信入选句 + 机器 QA")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--audio-dir", default=DEFAULT_AUDIO_DIR)
    p.add_argument("--min-tier", choices=("high", "mid"), default="high")
    p.add_argument("--articles", default=None)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="管线阶段状态总览")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--audio-dir", default=DEFAULT_AUDIO_DIR)


def dispatch_sentence(args: argparse.Namespace) -> int:
    op = getattr(args, "sentence_command", None) or getattr(args, "command", None)
    if op == "extract":
        summary = run_extract(
            pdf_path=args.pdf,
            pages_file=args.pages,
            audio_dir=args.audio_dir,
            out_dir=args.out,
        )
    elif op == "score":
        summary = run_score(
            out_dir=args.out,
            min_density=args.min_density,
            short_max_chars=args.short_max_chars,
            short_min_nasal=args.short_min_nasal,
            min_chars=args.min_chars,
        )
    elif op == "align":
        summary = run_align(
            out_dir=args.out,
            transcripts_dir=args.transcripts_dir,
            articles=_split_ids(args.articles),
        )
    elif op == "cut":
        summary = run_cut(
            out_dir=args.out,
            audio_dir=args.audio_dir,
            min_tier=args.min_tier,
            articles=_split_ids(args.articles),
            dry_run=args.dry_run,
        )
    elif op == "status":
        summary = run_status(out_dir=args.out, audio_dir=args.audio_dir)
    else:
        raise SentenceReadingError(f"unknown sentence command: {op}")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("status") == "succeeded" else 1


def _split_ids(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


def build_sentence_standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pth_corpus.sentence_reading",
        description="句子练习语料管线（可直接以本模块运行，不经过 cli.py）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_sentence_ops(subparsers)
    return parser


if __name__ == "__main__":  # pragma: no cover
    import sys

    args = build_sentence_standalone_parser().parse_args()
    try:
        raise SystemExit(dispatch_sentence(args))
    except (SentenceReadingError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"command": "sentence", "status": "failed", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1)
