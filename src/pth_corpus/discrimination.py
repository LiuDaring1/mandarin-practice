"""前后鼻音听辨练习（逐字判断）的池子、出题与判定。

产品口径（与用户确认过）：

- 判断点 = 词内每个 ``en/eng/in/ing`` 音节各算一次；其他韵母（an/ang/ong…）
  随词展示、不参与判断；交叉词（同词同时出现 en_eng 与 in_ing 两对）允许。
- 没有示范音：用户看字，点「前鼻 / 后鼻」按钮判断；整词所有判断点答完后
  统一给反馈（全对绿闪 / 有错红闪 + 逐字正确韵母）。
- 连续整词答错 ≥2 触发警报条，且从第 2 个连错词起每词扣 1 分（初版规则，
  见 :func:`consecutive_penalty`）。
- 服务端 judge 防答案随题下发：出题载荷只含 ``char_index / char_span / pair``，
  正确韵母与拼音只存在于服务端会话与判定结果里。

数据底座：``phonology.sqlite3`` 的 ``item_features_available`` /
``syllable_features_available`` 视图（自动过滤 ``excluded_items``）。
本模块不碰任何音频。
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import sqlite3
from pathlib import Path
from typing import Any

#: 参与判断的目标韵母。判断点 = 词内每个目标音节各一次。
TARGET_FINALS: tuple[str, ...] = ("en", "eng", "in", "ing")

#: 前鼻韵母（答案侧为 "front"）。
FRONT_FINALS: frozenset[str] = frozenset({"en", "in"})

#: 韵母 → 所属对比对。
FINAL_PAIRS: dict[str, str] = {
    "en": "en_eng",
    "eng": "en_eng",
    "in": "in_ing",
    "ing": "in_ing",
}

#: 对比对 → 前鼻 / 后鼻的韵母标签。
PAIR_FINALS: dict[str, dict[str, str]] = {
    "en_eng": {"front": "en", "back": "eng"},
    "in_ing": {"front": "in", "back": "ing"},
}

VALID_ANSWERS: frozenset[str] = frozenset({"front", "back"})


@dataclass(frozen=True)
class DiscrimPoint:
    """一个判断点：词内一个目标音节，考「前鼻 / 后鼻」。

    ``char_index`` 是音节首字在词内的 0-based 位置；``char_span`` 是该音节
    覆盖的字串（几乎都是单字，儿化词如「婶儿」为两字）。
    """

    char_index: int
    char_span: str
    final: str
    pinyin: str
    pair: str
    front: bool

    def question_payload(self) -> dict[str, Any]:
        """随题下发的载荷：不含答案（无 final / pinyin / front）。"""
        return {
            "char_index": self.char_index,
            "char_span": self.char_span,
            "pair": self.pair,
        }


def load_discrim_syllables(phonology_db: Path) -> dict[str, list[dict[str, str]]]:
    """逐音节读取（字、拼音、韵母），供池子与判定使用。

    ``phonology_db`` 缺失或不可读时返回空 dict（测试注入 items 时无拼音，
    判定结果里 pinyin 为空串，不影响正确性判定）。
    """
    result: dict[str, list[dict[str, str]]] = {}
    try:
        connection = sqlite3.connect(f"file:{phonology_db}?mode=ro", uri=True)
    except sqlite3.Error:
        return result
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT item_id, syllable_index, hanzi, pinyin_original, final_canonical "
            "FROM syllable_features_available ORDER BY item_id, syllable_index"
        ).fetchall()
        for row in rows:
            result.setdefault(row["item_id"], []).append(
                {
                    "char": row["hanzi"],
                    "pinyin": row["pinyin_original"],
                    "final": row["final_canonical"],
                }
            )
    finally:
        connection.close()
    return result


def _span_of(syllables: list[dict[str, str]]) -> dict[int, tuple[int, str]]:
    """音节下标 → (词内 0-based 起始位置, 字串)。

    逐音节字串按顺序拼接恒等于词（语料勘察验证过，含儿化词），
    故用累计长度定位；拼接不一致时退化为单字起点兜底。
    """
    spans: dict[int, tuple[int, str]] = {}
    offset = 0
    for index, row in enumerate(syllables):
        char = row.get("char") or ""
        spans[index] = (offset, char)
        offset += len(char) if char else 1
    return spans


def build_discrim_pool(
    items: list[Any],
    syllables_by_item: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    """从正式字词表提取含 en/eng/in/ing 音节的候选词。

    条目结构::

        {"item_id", "word", "final_sequence": [逐音节韵母],
         "points": [DiscrimPoint, ...]}

    ``items`` 来自 ``training.candidates.load_items``（已是
    ``item_features_available`` 视图，自动过滤已排除条目）。
    """
    syllables_by_item = syllables_by_item or {}
    pool: list[dict[str, Any]] = []
    for item in items:
        finals = [syllable.final_canonical for syllable in item.syllables]
        hit_indexes = [
            index for index, final in enumerate(finals) if final in TARGET_FINALS
        ]
        if not hit_indexes:
            continue
        syllable_rows = syllables_by_item.get(item.item_id) or []
        spans = _span_of(syllable_rows)
        points: list[DiscrimPoint] = []
        for index in hit_indexes:
            final = finals[index]
            char_index, char_span = spans.get(index, (index, ""))
            pinyin = ""
            if index < len(syllable_rows):
                char_span = syllable_rows[index].get("char") or char_span
                pinyin = syllable_rows[index].get("pinyin") or ""
            if not char_span and index < len(item.word_raw):
                char_span = item.word_raw[index]
            points.append(
                DiscrimPoint(
                    char_index=char_index,
                    char_span=char_span,
                    final=final,
                    pinyin=pinyin,
                    pair=FINAL_PAIRS[final],
                    front=final in FRONT_FINALS,
                )
            )
        pool.append(
            {
                "item_id": item.item_id,
                "word": item.word_raw,
                "final_sequence": finals,
                "points": points,
            }
        )
    return pool


def build_quiz(
    pool: list[dict[str, Any]],
    count: int = 10,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """从池子抽 ``count`` 个词出题；载荷不含答案。

    返回::

        [{"item_id", "word", "points": [{"char_index", "char_span", "pair"}]}]
    """
    rng = random.Random(seed)
    picked = rng.sample(pool, min(count, len(pool))) if pool else []
    return [
        {
            "item_id": entry["item_id"],
            "word": entry["word"],
            "points": [point.question_payload() for point in entry["points"]],
        }
        for entry in picked
    ]


def judge_answer(
    points: list[DiscrimPoint],
    answers: list[str],
) -> list[dict[str, Any]]:
    """逐点判定。``answers`` 与 ``points`` 一一对应，取值 "front" | "back"。

    返回每点：char_index / char_span / pair / answer / correct / final /
    pinyin / front。长度不等时抛 ``ValueError``。
    """
    if len(answers) != len(points):
        raise ValueError(
            f"expected {len(points)} answers for this item, got {len(answers)}"
        )
    unknown = [answer for answer in answers if answer not in VALID_ANSWERS]
    if unknown:
        raise ValueError(
            f"answers must be one of {sorted(VALID_ANSWERS)}, got {unknown}"
        )
    results: list[dict[str, Any]] = []
    for point, answer in zip(points, answers):
        correct = (answer == "front") == point.front
        results.append(
            {
                "char_index": point.char_index,
                "char_span": point.char_span,
                "pair": point.pair,
                "answer": answer,
                "correct": correct,
                "final": point.final,
                "pinyin": point.pinyin,
                "front": point.front,
            }
        )
    return results


def consecutive_penalty(consecutive_peak: int) -> int:
    """连错罚分（初版规则）：连续整词答错 ≥2 触发警报，从第 2 个连错词起
    每词扣 1 分。``consecutive_peak`` 为整轮最大连续整词错次数。"""
    return max(0, int(consecutive_peak) - 1)


def summarize_round(results_by_word: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """轮末汇总：按音节计分 + 全对词数 + 连错峰值 + 罚分。

    ``results_by_word`` 为每词的 :func:`judge_answer` 结果列表。
    """
    correct_points = 0
    total_points = 0
    perfect_words = 0
    run = 0
    peak = 0
    for word_results in results_by_word:
        total_points += len(word_results)
        word_correct = sum(1 for result in word_results if result["correct"])
        correct_points += word_correct
        if word_correct == len(word_results):
            perfect_words += 1
            run = 0
        else:
            run += 1
            peak = max(peak, run)
    penalty = consecutive_penalty(peak)
    return {
        "word_count": len(results_by_word),
        "correct_points": correct_points,
        "total_points": total_points,
        "perfect_words": perfect_words,
        "consecutive_peak": peak,
        "penalty": penalty,
        "score": correct_points - penalty,
    }
