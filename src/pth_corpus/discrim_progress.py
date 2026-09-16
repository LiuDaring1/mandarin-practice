"""听辨模块 · 主词库持续覆盖 + 长期错题复习（间隔重复）。

对应《听辨模块 v3 方案》：

- 主词库：``round + order + cursor + total``。每轮开始只洗牌一次，
  之后靠游标持续向后推进，保证整轮完整覆盖。
- 趁热巩固：词库批末由客户端对「本轮错词」重测一轮（答对出队、
  答错排队尾），服务端只负责按 item_ids 建判题会话，不写进度。
- 长期错题复习：主词库答错即进入复习系统，每词独立排期
  ``review_intervals_days``（默认 1 天 → 3 天 → 7 天）：
    - 答错当天：stage=0，明天到期；
    - 复习一次就对：stage+1，按 intervals[stage] 从当天起算下一次；
    - 复习中答错（本轮内最终答对）：重置 stage=0，明天重新开始；
    - 连续三次复习成功（stage=3）：掌握退出（历史保留）。
  - 「今日待复习」= 所有 nextReviewAt <= 今天 且未掌握的词，错过日期
    自然滚动累积，不清零。

状态落盘到 ``<prototype_dir>/discrim_progress.json``（单用户本地原型，
进程内懒加载 + 每次变更原子写回）。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _add_days(day_key: str, days: int) -> str:
    base = datetime.strptime(day_key, "%Y-%m-%d")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class DiscrimPracticeConfig:
    """可配置参数（默认值即方案共识参数，可被 JSON 覆盖）。"""

    practice_sizes: tuple[int, ...] = (50, 100, 150)
    default_practice_size: int = 50
    review_intervals_days: tuple[int, ...] = (1, 3, 7)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DiscrimPracticeConfig":
        data = data or {}
        config = cls(
            practice_sizes=tuple(
                int(value) for value in data.get("practice_sizes", (50, 100, 150))
            ),
            default_practice_size=int(data.get("default_practice_size", 50)),
            review_intervals_days=tuple(
                int(value)
                for value in data.get("review_intervals_days", (1, 3, 7))
            ),
        )
        if not config.practice_sizes:
            raise ValueError("practice_sizes must not be empty")
        if config.default_practice_size not in config.practice_sizes:
            raise ValueError("default_practice_size must be one of practice_sizes")
        if not config.review_intervals_days:
            raise ValueError("review_intervals_days must not be empty")
        if any(days < 0 for days in config.review_intervals_days):
            raise ValueError("review intervals must be non-negative")
        return config

    def to_dict(self) -> dict[str, Any]:
        return {
            "practice_sizes": list(self.practice_sizes),
            "default_practice_size": self.default_practice_size,
            "review_intervals_days": list(self.review_intervals_days),
        }


class DiscrimProgress:
    """主词库 / 复习排期 / 单词统计的状态存储。"""

    def __init__(self, path: Path, config: DiscrimPracticeConfig) -> None:
        self.path = path
        self.config = config
        self._data: dict[str, Any] = {}

    # ---- 落盘 ------------------------------------------------------------

    def load(self) -> None:
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
                    if self._migrate():
                        self.save()
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._data = {"version": 3}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, sort_keys=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        self._data = {"version": 3}

    def _migrate(self) -> bool:
        """把旧版（冲刺/活跃错题池）条目迁移为复习条目。返回是否有变更。"""
        mistakes = self._data.get("mistakes")
        if not isinstance(mistakes, dict):
            return False
        tomorrow = _add_days(_today(), 1)
        changed = False
        for entry in mistakes.values():
            if not isinstance(entry, dict):
                continue
            if "reviewStage" in entry:
                continue
            if entry.get("active"):
                entry["reviewStage"] = 0
                entry["nextReviewAt"] = tomorrow
            else:
                entry["reviewStage"] = 3
                entry["nextReviewAt"] = None
                entry["masteredAt"] = entry.get("lastCorrectAt")
            entry.pop("active", None)
            entry.pop("consecutiveCorrect", None)
            changed = True
        if changed:
            self._data["version"] = 3
        return changed

    # ---- 内部访问器 ------------------------------------------------------

    def _library(self) -> dict[str, Any]:
        library = self._data.get("library")
        if not isinstance(library, dict):
            library = {}
            self._data["library"] = library
        return library

    def _word_stats(self) -> dict[str, Any]:
        stats = self._data.get("word_stats")
        if not isinstance(stats, dict):
            stats = {}
            self._data["word_stats"] = stats
        return stats

    def _mistakes(self) -> dict[str, Any]:
        mistakes = self._data.get("mistakes")
        if not isinstance(mistakes, dict):
            mistakes = {}
            self._data["mistakes"] = mistakes
        return mistakes

    def _review_meta(self) -> dict[str, Any]:
        meta = self._data.get("review")
        if not isinstance(meta, dict):
            meta = {"order": []}
            self._data["review"] = meta
        if not isinstance(meta.get("order"), list):
            meta["order"] = []
        return meta

    # ---- 主词库（持续覆盖，逻辑不变） ------------------------------------

    def reconcile(self, pool_entries: list[dict[str, Any]]) -> None:
        library = self._library()
        order = library.get("order")
        if not isinstance(order, list):
            order = []
        pool_ids = [entry["item_id"] for entry in pool_entries]
        pool_set = set(pool_ids)
        cursor = int(library.get("cursor", 0) or 0)
        prefix = order[:cursor]
        pending = order[cursor:]
        keep_prefix = [item_id for item_id in prefix if item_id in pool_set]
        keep_pending = [item_id for item_id in pending if item_id in pool_set]
        known = set(order)
        new_ids = [item_id for item_id in pool_ids if item_id not in known]
        rng = random.Random()
        rng.shuffle(new_ids)
        library["order"] = keep_prefix + keep_pending + new_ids
        library["cursor"] = len(keep_prefix)
        library["total"] = len(pool_ids)
        library.setdefault("round", 1)

    def library_meta(self) -> dict[str, Any]:
        library = self._library()
        return {
            "round": int(library.get("round", 1)),
            "cursor": int(library.get("cursor", 0) or 0),
            "total": int(library.get("total", 0) or 0),
        }

    def take_library_chunk(
        self,
        pool_map: dict[str, dict[str, Any]],
        count: int,
        seed: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        self.reconcile(list(pool_map.values()))
        library = self._library()
        order = library["order"]
        total = len(order)
        if total == 0:
            raise ValueError("听辨题库为空，没有可练的词")
        cursor = int(library.get("cursor", 0) or 0)
        if cursor >= total:
            # 整轮覆盖完成 → 下一轮重新洗牌
            rng = random.Random(seed)
            rng.shuffle(order)
            library["order"] = order
            library["round"] = int(library.get("round", 1)) + 1
            library["cursor"] = 0
            cursor = 0
        take = min(count, total - cursor)
        ids = order[cursor : cursor + take]
        quiz: list[dict[str, Any]] = []
        full_items: list[dict[str, Any]] = []
        for item_id in ids:
            entry = pool_map[item_id]
            quiz.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": [point.question_payload() for point in entry["points"]],
                }
            )
            full_items.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": entry["points"],
                }
            )
        meta = {
            "round": int(library.get("round", 1)),
            "cursor_before": cursor,
            "count": len(ids),
            "total": total,
        }
        return quiz, full_items, meta

    # ---- 单词语统计 ------------------------------------------------------

    def _touch_stats(self, item_id: str, correct: bool) -> None:
        stats = self._word_stats()
        entry = stats.get(item_id)
        if not isinstance(entry, dict):
            entry = {"total": 0, "correct": 0, "wrong": 0}
            stats[item_id] = entry
        entry["total"] = int(entry.get("total", 0) or 0) + 1
        key = "correct" if correct else "wrong"
        entry[key] = int(entry.get(key, 0) or 0) + 1
        entry["lastAnsweredAt"] = _now()
        if not correct:
            entry["lastWrongAt"] = _now()

    # ---- 长期错题复习 ----------------------------------------------------

    def _ensure_mistake(self, item_id: str) -> dict[str, Any]:
        mistakes = self._mistakes()
        entry = mistakes.get(item_id)
        if not isinstance(entry, dict):
            entry = {
                "wrongCount": 0,
                "lastWrongAt": None,
                "reviewStage": 3,  # 默认视为已掌握（seed 场景下会被重写）
                "nextReviewAt": None,
                "lastReviewedAt": None,
                "masteredAt": None,
            }
            mistakes[item_id] = entry
        return entry

    def record_library_result(self, item_id: str, correct: bool) -> dict[str, Any]:
        """主词库一个词的结果：统计、游标前进；答错即排进复习（明天）。"""
        self._touch_stats(item_id, correct)
        if not correct:
            entry = self._ensure_mistake(item_id)
            entry["wrongCount"] = int(entry.get("wrongCount", 0) or 0) + 1
            entry["lastWrongAt"] = _now()
            entry["reviewStage"] = 0
            entry["nextReviewAt"] = _add_days(_today(), self.config.review_intervals_days[0])
        library = self._library()
        order = library.get("order")
        cursor = int(library.get("cursor", 0) or 0)
        if (
            isinstance(order, list)
            and cursor < len(order)
            and order[cursor] == item_id
        ):
            library["cursor"] = cursor + 1
        return {
            "cursor": int(library.get("cursor", 0) or 0),
            "round": int(library.get("round", 1)),
            "total": int(library.get("total", 0) or 0),
        }

    def due_ids(self, today: str | None = None) -> list[str]:
        """今日待复习：nextReviewAt <= 今天 且未掌握。错过日期自然累积。"""
        today = today or _today()
        return [
            item_id
            for item_id, entry in self._mistakes().items()
            if isinstance(entry, dict)
            and entry.get("nextReviewAt")
            and int(entry.get("reviewStage", 0) or 0) < len(self.config.review_intervals_days)
            and entry["nextReviewAt"] <= today
        ]

    def pending_review_count(self) -> int:
        """仍在复习系统内（未掌握）的词数。"""
        return sum(
            1
            for entry in self._mistakes().values()
            if isinstance(entry, dict)
            and entry.get("nextReviewAt")
            and int(entry.get("reviewStage", 0) or 0) < len(self.config.review_intervals_days)
        )

    def record_review_result(
        self,
        item_id: str,
        correct: bool,
        *,
        had_wrong_this_round: bool = False,
        today: str | None = None,
    ) -> dict[str, Any]:
        """复习中一个词的一次作答。

        - 答错：wrongCount+1，排期不动（词仍在今日待复习，等待本轮复现）。
        - 答对且本轮答错过：重置 stage=0，明天重新开始 1→3→7。
        - 答对且本轮一次就对：stage+1；满 3 次掌握退出；否则按
          intervals[stage] 从实际完成日起算下一次。
        """
        self._touch_stats(item_id, correct)
        entry = self._ensure_mistake(item_id)
        today = today or _today()
        if not correct:
            entry["wrongCount"] = int(entry.get("wrongCount", 0) or 0) + 1
            entry["lastWrongAt"] = _now()
            return {
                "correct": False,
                "scheduled_in_days": None,
                "mastered": False,
                "due_remaining": len(self.due_ids(today)),
            }
        mastered = False
        scheduled = None
        if had_wrong_this_round:
            entry["reviewStage"] = 0
            scheduled = self.config.review_intervals_days[0]
            entry["nextReviewAt"] = _add_days(today, scheduled)
        else:
            stage = int(entry.get("reviewStage", 0) or 0) + 1
            entry["reviewStage"] = stage
            if stage >= len(self.config.review_intervals_days):
                mastered = True
                entry["nextReviewAt"] = None
                entry["masteredAt"] = _now()
            else:
                scheduled = self.config.review_intervals_days[stage]
                entry["nextReviewAt"] = _add_days(today, scheduled)
        entry["lastReviewedAt"] = _now()
        return {
            "correct": True,
            "scheduled_in_days": scheduled,
            "mastered": mastered,
            "due_remaining": len(self.due_ids(today)),
        }

    def take_review_pass(
        self,
        pool_map: dict[str, dict[str, Any]],
        seed: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """今日待复习词建一场复习会话：一次洗牌固定顺序，重进不换序。"""
        due = self.due_ids()
        if not due:
            raise ValueError("今日没有待复习的错词")
        meta = self._review_meta()
        order = [item_id for item_id in meta["order"] if item_id in due]
        known = set(order)
        fresh = [item_id for item_id in due if item_id not in known]
        if fresh:
            rng = random.Random(seed)
            rng.shuffle(fresh)
        # 老顺序保持在前面，新到期词追加到末尾（重进不换序）
        order = order + fresh
        meta["order"] = order
        quiz: list[dict[str, Any]] = []
        full_items: list[dict[str, Any]] = []
        for item_id in order:
            entry = pool_map[item_id]
            quiz.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": [point.question_payload() for point in entry["points"]],
                }
            )
            full_items.append(
                {
                    "item_id": entry["item_id"],
                    "word": entry["word"],
                    "points": entry["points"],
                }
            )
        return quiz, full_items, {"count": len(order), "due_remaining": len(order)}

    # ---- 状态汇总 / 迁移 --------------------------------------------------

    def state(self) -> dict[str, Any]:
        return {
            "library": self.library_meta(),
            "review": {
                "due_today": len(self.due_ids()),
                "pending": self.pending_review_count(),
                "intervals": list(self.config.review_intervals_days),
            },
            "practice_sizes": list(self.config.practice_sizes),
            "default_practice_size": self.config.default_practice_size,
        }

    def seed_mistakes(self, item_ids: list[str]) -> int:
        """迁移入口：把旧错题 id 列表并入复习系统（明天到期）。"""
        tomorrow = _add_days(_today(), self.config.review_intervals_days[0])
        count = 0
        for item_id in item_ids:
            if not item_id:
                continue
            entry = self._ensure_mistake(item_id)
            entry["wrongCount"] = int(entry.get("wrongCount", 0) or 0) + 1
            entry["lastWrongAt"] = _now()
            entry["reviewStage"] = 0
            entry["nextReviewAt"] = tomorrow
            count += 1
        return count
