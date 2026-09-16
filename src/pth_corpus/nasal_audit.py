"""Front/back-nasal focused audio-vs-text mismatch audit (read-only).

The user testing the prototype found residual "audio reads a different word"
errors concentrated in the front/back-nasal training entries.  This module
prepares the machine-side re-clean pass for those entries:

1.  Build the nasal item universe from ``phonology-v1`` (any syllable whose
    canonical final is front/back nasal).
2.  Merge every historical cleaning signal that is still around:
    the old Qwen3 ASR audit candidates, the LLM-curated word-mismatch list,
    CC-CEDICT checks and sourcecheck tone/pinyin flags.
3.  Merge a fresh whisper-base re-transcription of the suspect subset
    (see ``tools/`` note in the report) and classify each suspect:
    wrong word / shifted neighbour / tone-or-homophone issue / unverifiable.
4.  Emit a ranked report directory for the human cleaning pass.

Everything here is read-only with respect to the corpus database, the clips
and the phonology data; it only writes the report under ``out_dir``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

FRONT_FINALS = {"an", "en", "ian", "in", "uan", "uen", "üan", "ün"}
BACK_FINALS = {
    "ang",
    "eng",
    "iang",
    "ing",
    "iong",
    "ong",
    "uang",
    "ueng",
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _pinyin_syllables(text: str) -> list[str] | None:
    """Tone-agnostic pinyin syllable list, or ``None`` if not all hanzi."""
    from pypinyin import Style, lazy_pinyin  # local import: offline env

    if not text:
        return []
    syllables = lazy_pinyin(text, style=Style.NORMAL, errors="default")
    return [str(s) for s in syllables]


def clean_asr_text(text: str) -> str:
    cleaned = CJK_RE.sub("", "").join(CJK_RE.findall(text or ""))
    return cleaned


def char_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def same_sound_ignoring_tone(a: str, b: str) -> bool:
    pa = _pinyin_syllables(a)
    pb = _pinyin_syllables(b)
    if not pa or not pb or len(pa) != len(pb):
        return False
    return pa == pb


@dataclass
class NasalItem:
    item_id: str
    table_kind: str
    word: str
    pinyin: str
    syllable_count: int
    finals: tuple[str, ...]
    global_seq: int

    @property
    def has_front(self) -> bool:
        return bool(set(self.finals) & FRONT_FINALS)

    @property
    def has_back(self) -> bool:
        return bool(set(self.finals) & BACK_FINALS)

    @property
    def is_contrast(self) -> bool:
        return self.has_front and self.has_back


def load_nasal_universe(
    phonology_db: Path, corpus_db: Path
) -> dict[str, NasalItem]:
    connection = sqlite3.connect(f"file:{phonology_db}?mode=ro", uri=True)
    try:
        finals_map: dict[str, set[str]] = defaultdict(set)
        for item_id, final in connection.execute(
            "SELECT item_id, final_canonical FROM syllable_features "
            "WHERE status='RESOLVED'"
        ):
            finals_map[item_id].add(final)
        syllable_counts: dict[str, int] = {}
        for item_id, syllable_count in connection.execute(
            "SELECT item_id, syllable_count FROM item_features"
        ):
            syllable_counts[item_id] = int(syllable_count or 1)
    finally:
        connection.close()

    connection = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        rows = {
            item_id: (word, pinyin, table_kind, global_seq)
            for item_id, word, pinyin, table_kind, global_seq in (
                connection.execute(
                    """
                    SELECT e.item_id, e.word_raw, e.pinyin_nfc,
                           e.table_kind, e.global_seq
                    FROM entries AS e
                    LEFT JOIN excluded_items AS x ON x.item_id = e.item_id
                    WHERE x.item_id IS NULL
                    """
                )
            )
        }
    finally:
        connection.close()

    universe: dict[str, NasalItem] = {}
    for item_id, finals in finals_map.items():
        if not (finals & FRONT_FINALS) and not (finals & BACK_FINALS):
            continue
        row = rows.get(item_id)
        if row is None:
            continue
        word, pinyin, table_kind, global_seq = row
        universe[item_id] = NasalItem(
            item_id=item_id,
            table_kind=str(table_kind or ""),
            word=str(word or ""),
            pinyin=str(pinyin or ""),
            syllable_count=syllable_counts.get(item_id, 1),
            finals=tuple(sorted(finals)),
            global_seq=int(global_seq or 0),
        )
    return universe


def load_historical_evidence(data_root: Path) -> dict[str, dict[str, Any]]:
    derived = data_root / "derived"
    evidence: dict[str, dict[str, Any]] = defaultdict(dict)

    def add_rows(path: Path, source: str, item_key: str = "item_id") -> None:
        if not path.is_file():
            return
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                item_id = row.get(item_key)
                if not item_id:
                    continue
                evidence[item_id][source] = row

    add_rows(derived / "audio_audit_candidates.csv", "qwen3_audit")
    add_rows(derived / "qwen3_word_mismatch_candidates.csv", "qwen3_mismatch")
    add_rows(derived / "qwen3_chain_excluded.csv", "qwen3_chain")
    add_rows(derived / "qwen3_full_align_excluded.csv", "qwen3_align")
    add_rows(derived / "cedict_check.csv", "cedict")

    report_path = derived / "source_quality_report_full.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for flag in report.get("flags", []):
            evidence[flag["item_id"]]["sourcecheck_flag"] = flag
        for suspicion in report.get("suspicions", []):
            evidence[suspicion["item_id"]]["sourcecheck_suspicion"] = suspicion
    return evidence


def load_asr_results(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    if not path.is_file():
        return results
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            results[row["item_id"]] = row.get("text", "")
    return results


def neighbour_words(
    universe: dict[str, NasalItem], item: NasalItem
) -> tuple[str, str]:
    """(previous, next) words in source order within the same table."""
    siblings = sorted(
        (
            other
            for other in universe.values()
            if other.table_kind == item.table_kind
        ),
        key=lambda other: other.global_seq,
    )
    position = next(
        (
            index
            for index, other in enumerate(siblings)
            if other.item_id == item.item_id
        ),
        -1,
    )
    if position < 0:
        return "", ""
    previous = siblings[position - 1].word if position > 0 else ""
    following = (
        siblings[position + 1].word if position + 1 < len(siblings) else ""
    )
    return previous, following


def classify(
    item: NasalItem,
    whisper_text: str,
    evidence: dict[str, Any],
    previous: str,
    following: str,
    *,
    whisper_freq: int = 1,
) -> tuple[str, str]:
    """Return ``(tier, reason)`` for one suspect item."""
    whisper = clean_asr_text(whisper_text)
    qwen3_mismatch = evidence.get("qwen3_mismatch")
    qwen3_audit = evidence.get("qwen3_audit")
    old_asr = clean_asr_text(
        qwen3_audit.get("asr", "") if qwen3_audit else ""
    )
    sourcecheck_flag = evidence.get("sourcecheck_flag")
    both_asr_agree = bool(
        whisper and old_asr and whisper == old_asr and whisper != item.word
    )

    reasons: list[str] = []
    if qwen3_mismatch:
        reasons.append("qwen3_mismatch")
    if sourcecheck_flag and sourcecheck_flag.get("kind") == "audio_tone_mismatch":
        reasons.append("tone_flag")

    if item.syllable_count >= 2 and len(whisper) >= 2:
        if whisper == item.word:
            return "OK", "whisper与词完全一致"
        homophone = same_sound_ignoring_tone(whisper, item.word)
        if homophone:
            return "T4_homophone", "whisper近音/同音（可能仅声调或听写差异）"
        sim_word = char_sim(whisper, item.word)
        sim_prev = char_sim(whisper, previous)
        sim_next = char_sim(whisper, following)
        best_neighbour = max(sim_prev, sim_next)
        if best_neighbour >= 0.5 and best_neighbour > sim_word:
            neighbour = previous if sim_prev >= sim_next else following
            return (
                "T3_shift",
                f"whisper更像相邻词「{neighbour}」"
                f"({best_neighbour:.2f} vs 本词{sim_word:.2f})",
            )
        # Strong dual-ASR agreement outranks the near-match catch-all below:
        # a half-identical text (e.g. 成人→行人) is exactly the "audio reads
        # a different word" class this audit hunts, so only a truly exact
        # match may land in OK.
        if both_asr_agree and whisper_freq <= 2:
            return "T1_strong", "双 ASR 一致读成别的文本：" + whisper
        if whisper_freq >= 3:
            return (
                "T2_repeat",
                f"whisper高频重复文本「{whisper}」（{whisper_freq}条同文本，"
                "疑似短切片/噪声，查时长与切分置信度）",
            )
        if qwen3_mismatch:
            return "T1_strong", "双证据不一致：" + "；".join(reasons)
        if sim_word >= 0.5:
            return (
                "T2_mismatch",
                f"whisper与本词高度相似但不完全一致"
                f"({sim_word:.2f}，可能近音误听或读错)："
                f"{whisper} vs {item.word}",
            )
        return "T2_mismatch", "whisper与本词不一致：" + "；".join(reasons)

    if item.syllable_count == 1:
        if sourcecheck_flag and sourcecheck_flag.get("kind") == "audio_tone_mismatch":
            return "T4_tone", "单音节声调轮廓不符：" + "；".join(reasons)
        if qwen3_mismatch:
            return "T2_mismatch", "qwen3_mismatch（单音节，待耳听）"
        if whisper and len(whisper) >= 1:
            return "T5_single", "单音节，whisper仅作参考：" + (old_asr or whisper)
        return "T5_unverifiable", "ASR无有效输出：" + (old_asr or "")

    if qwen3_mismatch:
        return "T2_mismatch", "qwen3_mismatch：" + "；".join(reasons)
    if not whisper:
        return "T5_unverifiable", "whisper无有效输出：" + (old_asr or "")
    return "T5_unverifiable", "whisper输出过短：" + whisper


TIER_ORDER = [
    "T1_strong",
    "T2_mismatch",
    "T2_repeat",
    "T3_shift",
    "T4_tone",
    "T4_homophone",
    "T5_single",
    "T5_unverifiable",
    "OK",
]


def build_report(
    data_root: Path,
    asr_jsonl: Path,
    out_dir: Path,
) -> Path:
    phonology_db = data_root / "derived" / "phonology-v1" / "phonology.sqlite3"
    corpus_db = data_root / "corpus.sqlite3"
    universe = load_nasal_universe(phonology_db, corpus_db)
    evidence = load_historical_evidence(data_root)
    whisper = load_asr_results(asr_jsonl)

    suspect_ids: set[str] = set()
    for item_id, item in universe.items():
        row_evidence = evidence.get(item_id, {})
        audit = row_evidence.get("qwen3_audit")
        if audit is not None and float(audit.get("score") or 0) < 0.5:
            suspect_ids.add(item_id)
        if any(
            key in row_evidence
            for key in ("qwen3_mismatch", "qwen3_chain", "qwen3_align")
        ):
            suspect_ids.add(item_id)

    out_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: dict[str, str] = {}
    clip_meta: dict[str, tuple[int, float]] = {}
    if suspect_ids:
        connection = sqlite3.connect(
            f"file:{corpus_db}?mode=ro", uri=True
        )
        try:
            placeholders = ",".join("?" for _ in suspect_ids)
            for item_id, clip_path, start_ms, end_ms, confidence in (
                connection.execute(
                    f"SELECT item_id, clip_path, start_ms, end_ms, confidence "
                    f"FROM segments WHERE item_id IN ({placeholders})",
                    tuple(sorted(suspect_ids)),
                )
            ):
                clip_paths[item_id] = str(clip_path or "")
                duration_ms = int(end_ms or 0) - int(start_ms or 0)
                clip_meta[item_id] = (
                    max(0, duration_ms),
                    float(confidence or 0.0),
                )
        finally:
            connection.close()

    whisper_freqs: Counter[str] = Counter(
        clean_asr_text(text)
        for text in whisper.values()
        if len(clean_asr_text(text)) >= 2
    )

    rows: list[dict[str, Any]] = []
    tier_counts: Counter[str] = Counter()
    for item_id in sorted(suspect_ids):
        item = universe[item_id]
        previous, following = neighbour_words(universe, item)
        whisper_text = clean_asr_text(whisper.get(item_id, ""))
        tier, reason = classify(
            item,
            whisper_text,
            evidence.get(item_id, {}),
            previous,
            following,
            whisper_freq=whisper_freqs.get(whisper_text, 1),
        )
        tier_counts[tier] += 1
        row_evidence = evidence.get(item_id, {})
        audit = row_evidence.get("qwen3_audit") or {}
        duration_ms, confidence = clip_meta.get(item_id, (0, 0.0))
        old_asr = clean_asr_text(audit.get("asr", ""))
        rows.append(
            {
                "item_id": item.item_id,
                "table_kind": item.table_kind,
                "word": item.word,
                "pinyin": item.pinyin,
                "syllable_count": item.syllable_count,
                "finals": " ".join(item.finals),
                "clip_path": clip_paths.get(item.item_id, ""),
                "clip_duration_ms": duration_ms,
                "segment_confidence": round(confidence, 3),
                "has_front": 1 if item.has_front else 0,
                "has_back": 1 if item.has_back else 0,
                "whisper_text": whisper_text,
                "whisper_text_freq": whisper_freqs.get(whisper_text, 1),
                "old_qwen3_asr": old_asr,
                "old_score": audit.get("score", ""),
                "both_asr_agree": (
                    1 if whisper_text and old_asr and whisper_text == old_asr else 0
                ),
                "prev_word": previous,
                "next_word": following,
                "tier": tier,
                "reason": reason,
                "qwen3_mismatch": 1 if "qwen3_mismatch" in row_evidence else 0,
            }
        )
    rank = {tier: index for index, tier in enumerate(TIER_ORDER)}
    rows.sort(
        key=lambda row: (
            rank.get(row["tier"], 99),
            -int(row["both_asr_agree"]),
            row["word"],
            row["item_id"],
        )
    )

    ranked_path = out_dir / "nasal_suspects_ranked.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(ranked_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    universe_path = out_dir / "nasal_universe.csv"
    with open(universe_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "item_id",
                "table_kind",
                "word",
                "pinyin",
                "syllable_count",
                "finals",
                "has_front",
                "has_back",
                "is_contrast",
                "in_suspects",
            ]
        )
        for item in sorted(universe.values(), key=lambda i: (i.table_kind, i.global_seq)):
            writer.writerow(
                [
                    item.item_id,
                    item.table_kind,
                    item.word,
                    item.pinyin,
                    item.syllable_count,
                    " ".join(item.finals),
                    int(item.has_front),
                    int(item.has_back),
                    int(item.is_contrast),
                    int(item.item_id in suspect_ids),
                ]
            )

    # Human listening batches: all actionable tiers first, ≤200 per batch.
    actionable = [row for row in rows if row["tier"] in {
        "T1_strong", "T2_mismatch", "T2_repeat", "T3_shift",
        "T4_tone", "T4_homophone",
    }]
    batch_index = 0
    for start in range(0, len(actionable), 200):
        batch_index += 1
        batch_path = out_dir / f"review_batch_{batch_index:02d}.csv"
        with open(batch_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(actionable[start : start + 200])

    stats = {
        "nasal_items": len(universe),
        "front_only": sum(1 for i in universe.values() if i.has_front and not i.has_back),
        "back_only": sum(1 for i in universe.values() if i.has_back and not i.has_front),
        "contrast": sum(1 for i in universe.values() if i.is_contrast),
        "suspects": len(suspect_ids),
        "tier_counts": dict(sorted(tier_counts.items())),
        "actionable": len(actionable),
        "review_batches": batch_index,
        "asr_results": len(whisper),
    }
    (out_dir / "nasal_audit_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(out_dir, stats)
    return out_dir


def write_report(out_dir: Path, stats: dict[str, Any]) -> None:
    lines = [
        "# 前后鼻音专项 · 音频-文本错漏盘点报告",
        "",
        "生成方式：`python -m pth_corpus.nasal_audit`（只读母库/音频，仅写本目录）。",
        "",
        "## 一、口径",
        "",
        "- 前后鼻音盘子：phonology-v1 中任一音节韵母为前鼻音",
        "  （an en ian in uan uen üan ün）或后鼻音",
        "  （ang eng iang ing iong ong uang ueng）的正式条目（未被 excluded_items 排除）。",
        f"- 盘子规模：{stats['nasal_items']} 条",
        f"（仅前鼻 {stats['front_only']} / 仅后鼻 {stats['back_only']} / 前后均有 {stats['contrast']}）。",
        f"- 嫌疑集：{stats['suspects']} 条 = 旧 Qwen3 ASR 低分（<0.5）∪ Qwen3 错配清单，",
        "  全部用本地 whisper base（CPU，中文）重新听写。",
        f"- 有效听写条数：{stats['asr_results']}。",
        "",
        "## 二、分级（按人工听检优先级）",
        "",
        "| 级别 | 含义 | 数量 |",
        "|---|---|---:|",
    ]
    tier_labels = {
        "T1_strong": "强证据：双 ASR 一致读成别的文本，或 Qwen3 错配清单 + 新 whisper 不一致",
        "T2_mismatch": "新 whisper 与本词不一致（多音节，疑似音频读错词）",
        "T2_repeat": "whisper 高频重复文本（疑似短切片/噪声，查时长与切分置信度）",
        "T3_shift": "新 whisper 更像相邻词（疑似切分串位）",
        "T4_tone": "声调轮廓不符（sourcecheck）",
        "T4_homophone": "whisper 近音/同音（可能仅听写差异，需耳听）",
        "T5_single": "单音节，whisper 仅参考（旧 Qwen3 附注）",
        "T5_unverifiable": "whisper 无有效输出，无法机器判断",
        "OK": "whisper 与本词完全一致，疑似误报（不再包含近匹配）",
    }
    for tier, label in tier_labels.items():
        lines.append(f"| {tier} | {label} | {stats['tier_counts'].get(tier, 0)} |")
    lines += [
        "",
        f"可直接进入人工听检的条目（T1–T4）：**{stats['actionable']} 条**，"
        f"已按每批 ≤200 条切成 {stats['review_batches']} 个批次（`review_batch_*.csv`）。",
        "",
        "## 三、产物",
        "",
        "- `nasal_universe.csv`：全部前后鼻音条目（含是否在嫌疑集）。",
        "- `nasal_suspects_ranked.csv`：嫌疑集全表。关键列：whisper 文本、旧 Qwen3 文本、",
        "  `both_asr_agree`（两个 ASR 完全一致读成别的文本）、`whisper_text_freq`（同文本在嫌疑集中出现次数，",
        "  高频多为模型幻觉/短切片噪声）、`clip_duration_ms`、`segment_confidence`、前后邻词、级别、理由。",
        "- `review_batch_*.csv`：人工听检批次（T1–T4 按级别排序）。",
        "- `nasal_audit_stats.json`：统计快照。",
        "",
        "## 四、给清洗窗口的建议",
        "",
        "1. 听检顺序：T1（双 ASR 一致）→ T2_mismatch → T2_repeat → T3 → T4，每批用 `data/review/` 的既有流程记录结论；",
        "   确认「音频读的不是这个词」的条目走 excluded_items 排除（与历史清洗口径一致）。",
        "2. T2_repeat 多为短切片 / 低置信切分（看 `clip_duration_ms` / `segment_confidence` 列）：",
        "   优先检查切分质量，能重切的重切，不能的排除；不要当「读错词」盲排。",
        "3. T3（串位）优先检查切分边界，可尝试用 review --apply-adjustments 重切，",
        "   而不是直接排除。",
        "4. T4_homophone 多数是 whisper 的听写差异，不要直接排除，以人耳为准。",
        "5. 单音节（T5_single）机器不可靠，若人力有限可只抽查高频出现的。",
        "6. 排除动作完成后，重跑本命令并重新生成 Session 验证：",
        "   清洗结果会通过生成器候选池直接影响训练内容。",
        "",
        "## 五、已知限制",
        "",
        "- whisper base 对单音节、近音词、轻声/儿化不可靠；本报告只做排序，不做最终判定。",
        "- 旧 Qwen3 ASR 原始文本噪音很大（部分为英文/数字），仅作附注。",
        "- 「双 ASR 一致」里仍混有少量两个模型共同听错的样本（如短音近音词），以人耳为准。",
        "- 仅覆盖前后鼻音盘子；其他音的错误不在本次范围。",
        "",
    ]
    (out_dir / "NASAL_AUDIT_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Front/back-nasal audio-vs-text mismatch audit"
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument(
        "--asr", required=True, help="whisper re-transcription JSONL"
    )
    parser.add_argument(
        "--out",
        default="derived/nasal-audit",
        help="report directory (default: derived/nasal-audit)",
    )
    args = parser.parse_args(argv)
    data_root = Path(args.data_root).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = data_root / out_dir
    out_dir = out_dir.resolve()
    result = build_report(data_root, Path(args.asr), out_dir)
    stats = json.loads(
        (result / "nasal_audit_stats.json").read_text(encoding="utf-8")
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
