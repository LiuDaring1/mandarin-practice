"""Unit tests for the main-library coverage + spaced review state (v3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pth_corpus.discrimination import DiscrimPoint
from pth_corpus.discrim_progress import (
    DiscrimPracticeConfig,
    DiscrimProgress,
    _add_days,
    _today,
)


def _pool_map(ids: list[str]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for index, item_id in enumerate(ids):
        front = index % 2 == 0
        final = "en" if front else "ing"
        point = DiscrimPoint(
            char_index=0,
            char_span=item_id,
            final=final,
            pinyin="x",
            pair="en_eng" if front else "in_ing",
            front=front,
        )
        entries[item_id] = {
            "item_id": item_id,
            "word": item_id,
            "final_sequence": [final],
            "points": [point],
        }
    return entries


def _config(**overrides: Any) -> DiscrimPracticeConfig:
    data = {
        "practice_sizes": [50, 100, 150],
        "default_practice_size": 50,
        "review_intervals_days": [1, 3, 7],
    }
    data.update(overrides)
    return DiscrimPracticeConfig.from_dict(data)


def _progress(
    tmp_path: Path, config: DiscrimPracticeConfig | None = None
) -> DiscrimProgress:
    progress = DiscrimProgress(tmp_path / "discrim_progress.json", config or _config())
    progress.load()
    return progress


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


def test_config_defaults_and_validation() -> None:
    assert _config().practice_sizes == (50, 100, 150)
    assert _config().review_intervals_days == (1, 3, 7)
    for bad in (
        {"review_intervals_days": []},
        {"review_intervals_days": [1, -1, 7]},
        {"practice_sizes": [50], "default_practice_size": 100},
    ):
        try:
            DiscrimPracticeConfig.from_dict(bad)
        except ValueError:
            continue
        raise AssertionError(f"config must reject {bad}")


# --------------------------------------------------------------------------
# 主词库：固定乱序 + 游标 + 整轮覆盖 + 换轮
# --------------------------------------------------------------------------


def test_library_round_covers_every_word_exactly_once(tmp_path: Path) -> None:
    pool = _pool_map([f"t1-{i:05d}" for i in range(1, 31)])
    progress = _progress(tmp_path)
    seen: list[str] = []
    while True:
        quiz, _, meta = progress.take_library_chunk(pool, count=8, seed=7)
        if meta["round"] > 1:
            break
        for item in quiz:
            progress.record_library_result(item["item_id"], correct=True)
            seen.append(item["item_id"])
    assert len(seen) == 30
    assert set(seen) == set(pool)
    assert progress.library_meta()["round"] == 2
    assert progress.library_meta()["cursor"] == 0


def test_library_cursor_advances_only_for_answered_head(tmp_path: Path) -> None:
    pool = _pool_map([f"t1-{i:05d}" for i in range(1, 11)])
    progress = _progress(tmp_path)
    quiz, _, _ = progress.take_library_chunk(pool, count=5, seed=1)
    ids = [item["item_id"] for item in quiz]
    progress.record_library_result(ids[1], correct=True)
    assert progress.library_meta()["cursor"] == 0
    for item_id in ids:
        progress.record_library_result(item_id, correct=True)
    assert progress.library_meta()["cursor"] == 5
    progress.record_library_result(ids[0], correct=True)
    assert progress.library_meta()["cursor"] == 5


def test_library_reconcile_adds_to_pending_and_removes_deleted(
    tmp_path: Path,
) -> None:
    ids = [f"t1-{i:05d}" for i in range(1, 11)]
    pool = _pool_map(ids)
    progress = _progress(tmp_path)
    quiz, _, _ = progress.take_library_chunk(pool, count=4, seed=3)
    for item in quiz:
        progress.record_library_result(item["item_id"], correct=True)
    practiced = {item["item_id"] for item in quiz}
    removed_practiced = quiz[0]["item_id"]
    removed_pending = next(i for i in ids if i not in practiced)
    new_ids = [
        i for i in ids if i not in {removed_practiced, removed_pending}
    ] + ["t1-00011", "t1-00012"]
    new_pool = _pool_map(new_ids)
    progress.reconcile(list(new_pool.values()))
    meta = progress.library_meta()
    assert meta["total"] == 10
    assert meta["cursor"] == 3
    order = progress._library()["order"]
    assert set(order) == set(new_ids)
    kept_prefix = practiced - {removed_practiced}
    assert set(order[: meta["cursor"]]) == kept_prefix
    assert set(order[meta["cursor"] :]) == set(new_ids) - kept_prefix


# --------------------------------------------------------------------------
# 长期错题复习：排期 1 → 3 → 7 → 掌握
# --------------------------------------------------------------------------


def test_wrong_schedules_review_tomorrow(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    today = _today()
    tomorrow = _add_days(today, 1)
    result = progress.record_library_result("t1-00001", correct=False)
    assert result["cursor"] == 0  # 无词序时不影响
    entry = progress._mistakes()["t1-00001"]
    assert entry["reviewStage"] == 0
    assert entry["nextReviewAt"] == tomorrow
    assert entry["wrongCount"] == 1
    # 今天不出现，明天到期
    assert "t1-00001" not in progress.due_ids(today)
    assert "t1-00001" in progress.due_ids(tomorrow)


def test_review_advances_1_3_7_then_mastered(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    progress.record_library_result("t1-00001", correct=False)
    # 明天复习：一次就对 → 3 天后
    result = progress.record_review_result(
        "t1-00001", correct=True, today="2026-09-02"
    )
    assert result["scheduled_in_days"] == 3
    assert result["mastered"] is False
    entry = progress._mistakes()["t1-00001"]
    assert entry["reviewStage"] == 1
    assert entry["nextReviewAt"] == "2026-09-05"
    # 3 天后：一次就对 → 7 天后
    progress.record_review_result("t1-00001", correct=True, today="2026-09-05")
    assert progress._mistakes()["t1-00001"]["nextReviewAt"] == "2026-09-12"
    # 7 天后：一次就对 → 掌握退出
    result = progress.record_review_result(
        "t1-00001", correct=True, today="2026-09-12"
    )
    assert result["mastered"] is True
    entry = progress._mistakes()["t1-00001"]
    assert entry["nextReviewAt"] is None
    assert entry["masteredAt"]
    assert "t1-00001" not in progress.due_ids("2026-09-20")


def test_review_wrong_then_correct_resets_to_tomorrow(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    progress.record_library_result("t1-00001", correct=False)
    today = _today()
    tomorrow = _add_days(today, 1)
    # 复习中答错：排期不动、错次 +1（词仍在今日待复习，等复现）
    result = progress.record_review_result(
        "t1-00001", correct=False, today=tomorrow
    )
    assert result["correct"] is False
    assert result["scheduled_in_days"] is None
    entry = progress._mistakes()["t1-00001"]
    assert entry["wrongCount"] == 2
    assert entry["nextReviewAt"] == tomorrow  # 仍是到期日
    assert "t1-00001" in progress.due_ids(tomorrow)
    # 复现答对：重置回明天，重走 1→3→7
    result = progress.record_review_result(
        "t1-00001", correct=True, had_wrong_this_round=True, today=tomorrow
    )
    assert result["scheduled_in_days"] == 1
    entry = progress._mistakes()["t1-00001"]
    assert entry["reviewStage"] == 0
    assert entry["nextReviewAt"] == _add_days(tomorrow, 1)


def test_due_accumulates_overdue_days(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    for item_id in ("t1-00001", "t1-00002"):
        progress.record_library_result(item_id, correct=False)
    # 今天不出现；过期未复习：多天后仍在待复习队列（滚动累积）
    assert progress.due_ids(_today()) == []
    due = progress.due_ids(_add_days(_today(), 30))
    assert set(due) == {"t1-00001", "t1-00002"}


def test_review_pass_fixed_order(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    pool = _pool_map([f"t1-{i:05d}" for i in range(1, 8)])
    for i in range(1, 6):
        progress.record_library_result(f"t1-{i:05d}", correct=False)
    # 全部改为已到期
    for entry in progress._mistakes().values():
        entry["nextReviewAt"] = "2000-01-01"
    quiz, _, meta = progress.take_review_pass(pool, seed=3)
    first_order = [item["item_id"] for item in quiz]
    assert len(first_order) == 5
    assert len(set(first_order)) == 5
    assert meta["due_remaining"] == 5
    # 重进：顺序保持一致（固定顺序）
    quiz2, _, _ = progress.take_review_pass(pool, seed=99)
    assert [item["item_id"] for item in quiz2] == first_order


def test_persistence_roundtrip(tmp_path: Path) -> None:
    pool = _pool_map([f"t1-{i:05d}" for i in range(1, 6)])
    path = tmp_path / "discrim_progress.json"
    progress = DiscrimProgress(path, _config())
    progress.load()
    progress.record_library_result("t1-00001", correct=False)
    progress.save()
    reloaded = DiscrimProgress(path, _config())
    reloaded.load()
    assert reloaded.library_meta() == progress.library_meta()
    assert reloaded._mistakes()["t1-00001"]["reviewStage"] == 0
    assert reloaded.state()["review"]["pending"] == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mistakes"]["t1-00001"]["wrongCount"] == 1


def test_seed_mistakes_schedules_tomorrow(tmp_path: Path) -> None:
    progress = _progress(tmp_path)
    progress.seed_mistakes(["t1-00001", "t1-00001", "t1-00002"])
    assert progress._mistakes()["t1-00001"]["wrongCount"] == 2
    assert progress._mistakes()["t1-00001"]["reviewStage"] == 0
    assert progress.state()["review"]["pending"] == 2
    assert progress.state()["review"]["due_today"] == 0  # 明天才到期


def test_migration_from_old_active_pool(tmp_path: Path) -> None:
    path = tmp_path / "discrim_progress.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "library": {"round": 1, "cursor": 100, "total": 3796, "order": []},
                "mistakes": {
                    "t1-00001": {"active": True, "wrongCount": 2, "lastWrongAt": "x"},
                    "t1-00002": {
                        "active": False,
                        "wrongCount": 3,
                        "lastCorrectAt": "x",
                        "correctedCount": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    progress = DiscrimProgress(path, _config())
    progress.load()
    entry_a = progress._mistakes()["t1-00001"]
    assert entry_a["reviewStage"] == 0
    assert entry_a["nextReviewAt"]  # 明天
    assert "active" not in entry_a
    entry_b = progress._mistakes()["t1-00002"]
    assert entry_b["reviewStage"] == 3  # 已纠正 → 视为掌握
    assert entry_b["nextReviewAt"] is None
    assert progress.library_meta()["cursor"] == 100
