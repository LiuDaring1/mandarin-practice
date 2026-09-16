"""Achievement / perler-bead reward system for the local prototype.

This module is deliberately decoupled from the training session generator:

* ``training.v2`` decides **what to practice** (items, order, duration).
* this module decides **what a finished session earns** and **how artworks
  fill up**.

Reward baseline (2026-08-26, 100×100 正式资产版):

* 三个正式训练项目（字词 / 句子 / 辨音）平权；标准档统一 600 拼点。
* 各档满额：字词 5min=600 / 10min=1200；句子 10 句=600 / 15 句=900；
  辨音 50 词=300 / 100 词=600 / 150 词=900。
* 完成不足 20%：不发拼点、不算有效训练；≥20% 按真实完成比例结算（浮点）。
* 正确率不影响拼点、答错不扣拼点；无辨音轮次递减、无全对彩蛋。
* 今日三练（三类各完整完成一次）= +100 / 天；今日错题复习清空 = +100 / 天。
* Streak 不发拼点；不设常规每日硬上限。
* 标准完整训练日 = 600 + 600 + 600 + 100 = 1900。

Every reward number comes from ``achievement_config_v2.json`` and every
artwork comes from ``artwork_catalog_v2.json``.  Nothing here is called by the
generator, and the generator knows nothing about beads.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any

HEX_CELL_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class AchievementConfig:
    """Reward rules (mirrors ``achievement_config_v2.json``).

    ``tiers`` maps an activity to its tier table::

        {
            "word":     {5: 600, 10: 1200},
            "sentence": {10: 600, 15: 900},
            "discrim":  {50: 300, 100: 600, 150: 900},
        }

    Tier values are the **full** reward for 100% completion; partial
    settlements scale them by the real completion ratio (and may be
    fractional — the prototype accumulates the remainder internally).
    """

    version: str
    reward_unit: str
    minimum_completion_ratio: float
    tiers: dict[str, dict[int, float]]
    trio_bonus: int
    review_reward: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AchievementConfig":
        tier_data = data.get("tiers")
        if not isinstance(tier_data, dict) or not tier_data:
            raise ValueError("tiers must be a non-empty object")
        tiers: dict[str, dict[int, float]] = {}
        for activity, table in tier_data.items():
            if not isinstance(table, dict) or not table:
                raise ValueError(f"tiers[{activity!r}] must be a non-empty object")
            normalized: dict[int, float] = {}
            for key, value in table.items():
                try:
                    tier_key = int(key)
                except (TypeError, ValueError):
                    raise ValueError(f"tiers[{activity!r}] key {key!r} is not an int")
                if tier_key <= 0:
                    raise ValueError(
                        f"tiers[{activity!r}] key {tier_key} must be positive"
                    )
                amount = float(value)
                if amount <= 0:
                    raise ValueError(
                        f"tiers[{activity!r}][{tier_key}] must be positive"
                    )
                normalized[tier_key] = amount
            tiers[str(activity)] = normalized
        minimum_ratio = float(data.get("minimum_completion_ratio", 0.2))
        if not 0.0 <= minimum_ratio <= 1.0:
            raise ValueError("minimum_completion_ratio must be between 0 and 1")
        trio = int(data.get("trio_bonus", 0))
        if trio < 0:
            raise ValueError("trio_bonus must be non-negative")
        review_reward = int(data.get("review_reward", 0))
        if review_reward < 0:
            raise ValueError("review_reward must be non-negative")
        return cls(
            version=str(data["version"]),
            reward_unit=str(data.get("reward_unit", "拼点")),
            minimum_completion_ratio=minimum_ratio,
            tiers=tiers,
            trio_bonus=trio,
            review_reward=review_reward,
        )

    def tier_value(self, activity: str, tier_key: int) -> float | None:
        table = self.tiers.get(activity)
        if table is None:
            return None
        return table.get(int(tier_key))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "reward_unit": self.reward_unit,
            "minimum_completion_ratio": self.minimum_completion_ratio,
            "tiers": {
                activity: {str(key): value for key, value in table.items()}
                for activity, table in self.tiers.items()
            },
            "trio_bonus": self.trio_bonus,
            "review_reward": self.review_reward,
        }


@dataclass(frozen=True)
class Reward:
    """Result of settling one finished (or abandoned) training session.

    ``total_beads`` may be fractional (accumulated remainder is allowed
    internally); only whole beads advance an artwork.
    """

    activity: str
    eligible: bool
    tier_key: int | None
    completion_ratio: float
    base_beads: float
    total_beads: float
    reward_unit: str
    streak_days: int = 0
    streak_bonus: int = 0
    trio_bonus: int = 0
    completed_today: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity": self.activity,
            "eligible": self.eligible,
            "tier_key": self.tier_key,
            "completion_ratio": self.completion_ratio,
            "base_beads": self.base_beads,
            "total_beads": self.total_beads,
            "reward_unit": self.reward_unit,
            "streak_days": self.streak_days,
            "streak_bonus": self.streak_bonus,
            "trio_bonus": self.trio_bonus,
            "completed_today": self.completed_today,
        }


def compute_activity_reward(
    config: AchievementConfig,
    activity: str,
    tier_key: int,
    ratio: float,
    *,
    streak_days: int = 0,
    trio_eligible: bool = False,
    trio_awarded_today: bool = False,
) -> Reward:
    """统一结算三类正式训练（字词 / 句子 / 辨音）。

    * 100% 完成：获得该档完整拼点 + 今日三练（若达成且当日未发）；标记
      该项目「今日已完成」。
    * 达到 20% 但未完成：按真实完成比例结算基础拼点（浮点），无任何加成。
    * 不足 20%：不发拼点、无效训练、不续 streak、不计今日三练。
    * 正确率/答对答错不影响拼点；无 streak 拼点、无每日上限。
    """
    tier_value = config.tier_value(activity, tier_key)
    if tier_value is None:
        raise ValueError(
            f"no reward configured for activity {activity!r} tier {tier_key!r}"
        )
    clamped = max(0.0, min(1.0, float(ratio)))
    streak_days = max(0, int(streak_days))
    trio = (
        config.trio_bonus
        if (trio_eligible and not trio_awarded_today)
        else 0
    )
    if clamped >= 1.0:
        return Reward(
            activity=activity,
            eligible=True,
            tier_key=int(tier_key),
            completion_ratio=1.0,
            base_beads=tier_value,
            total_beads=tier_value + trio,
            reward_unit=config.reward_unit,
            streak_days=streak_days,
            streak_bonus=0,
            trio_bonus=trio,
            completed_today=True,
        )
    if clamped >= config.minimum_completion_ratio:
        total = tier_value * clamped
        return Reward(
            activity=activity,
            eligible=total > 0,
            tier_key=int(tier_key),
            completion_ratio=clamped,
            base_beads=tier_value,
            total_beads=total,
            reward_unit=config.reward_unit,
            streak_days=streak_days,
            streak_bonus=0,
            trio_bonus=0,
            completed_today=False,
        )
    return Reward(
        activity=activity,
        eligible=False,
        tier_key=int(tier_key),
        completion_ratio=clamped,
        base_beads=tier_value,
        total_beads=0.0,
        reward_unit=config.reward_unit,
        streak_days=streak_days,
        streak_bonus=0,
        trio_bonus=0,
        completed_today=False,
    )


def compute_review_reward(config: AchievementConfig) -> Reward:
    """当天完成全部「今日待复习」的一次性固定奖励（不做逐题奖励）。

    奖励的是「清空今日复习任务」，不是错题数量：错得更多不会线性多赚钱，
    拖延积压不会获得更高复习收益。复习不作为今日三练第四项、不发 streak。
    """
    base = max(0, int(config.review_reward))
    return Reward(
        activity="review",
        eligible=base > 0,
        tier_key=None,
        completion_ratio=1.0,
        base_beads=float(base),
        total_beads=float(base),
        reward_unit=config.reward_unit,
    )


@dataclass(frozen=True)
class Artwork:
    """One perler-bead artwork from ``artwork_catalog_v2.json``.

    Grid layout: one list per row; each cell is ``None`` (empty background)
    or a ``#RRGGBB`` color string.  ``active_bead_count`` is always
    recomputed from the grid and must match the declared value.
    ``fill_order`` is a deterministic *placeholder* order decoupled from the
    grid (replaceable later by a designed reveal order).
    """

    artwork_id: str
    name: str
    tagline: str
    series_id: str | None
    kind: str
    width: int
    height: int
    grid: tuple[tuple[str | None, ...], ...]
    palette: dict[str, int]
    active_bead_count: int
    fill_order: tuple[tuple[int, int], ...]
    completed: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artwork":
        artwork_id = str(data.get("id") or data["artwork_id"])
        raw_grid = data.get("grid")
        if not isinstance(raw_grid, list) or not raw_grid:
            raise ValueError(f"artwork {artwork_id!r} has an invalid grid")
        grid_rows: list[tuple[str | None, ...]] = []
        width = len(raw_grid[0]) if isinstance(raw_grid[0], list) else 0
        for row in raw_grid:
            if not isinstance(row, list):
                raise ValueError(f"artwork {artwork_id!r} grid rows must be lists")
            if len(row) != width:
                raise ValueError(
                    f"artwork {artwork_id!r} grid rows have different widths"
                )
            cells: list[str | None] = []
            for cell in row:
                if cell is None:
                    cells.append(None)
                elif isinstance(cell, str) and HEX_CELL_RE.fullmatch(cell):
                    cells.append(cell.upper())
                else:
                    raise ValueError(
                        f"artwork {artwork_id!r} has invalid cell {cell!r}"
                    )
            grid_rows.append(tuple(cells))
        height = len(grid_rows)
        declared_width = int(data.get("width", width))
        declared_height = int(data.get("height", height))
        if width != declared_width or height != declared_height:
            raise ValueError(
                f"artwork {artwork_id!r} width/height {declared_width}x"
                f"{declared_height} do not match grid {width}x{height}"
            )
        bead_count = sum(
            1 for row in grid_rows for cell in row if cell is not None
        )
        declared = int(data["active_bead_count"])
        if bead_count != declared:
            raise ValueError(
                f"artwork {artwork_id!r} active_bead_count is {declared} "
                f"but the grid contains {bead_count} beads"
            )
        raw_order = data.get("fill_order")
        if not isinstance(raw_order, list):
            raise ValueError(
                f"artwork {artwork_id!r} fill_order must be a list"
            )
        order: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for position in raw_order:
            if not isinstance(position, list) or len(position) != 2:
                raise ValueError(
                    f"artwork {artwork_id!r} fill_order entries must be [row, col]"
                )
            row, col = int(position[0]), int(position[1])
            if not (0 <= row < height and 0 <= col < width):
                raise ValueError(
                    f"artwork {artwork_id!r} fill_order position "
                    f"({row}, {col}) out of range"
                )
            if grid_rows[row][col] is None:
                raise ValueError(
                    f"artwork {artwork_id!r} fill_order points at an empty cell "
                    f"({row}, {col})"
                )
            if (row, col) in seen:
                raise ValueError(
                    f"artwork {artwork_id!r} fill_order has duplicate "
                    f"({row}, {col})"
                )
            seen.add((row, col))
            order.append((row, col))
        if len(order) != bead_count:
            raise ValueError(
                f"artwork {artwork_id!r} fill_order has {len(order)} entries "
                f"but {bead_count} beads"
            )
        palette_raw = data.get("palette", {})
        for color in palette_raw:
            if not (isinstance(color, str) and HEX_CELL_RE.fullmatch(color)):
                raise ValueError(
                    f"artwork {artwork_id!r} has invalid palette color "
                    f"{color!r}"
                )
        return cls(
            artwork_id=artwork_id,
            name=str(data.get("name", artwork_id)),
            tagline=str(data.get("tagline", "")),
            series_id=(
                str(data["series_id"]) if data.get("series_id") is not None else None
            ),
            kind=str(data.get("kind", "series")),
            width=width,
            height=height,
            grid=tuple(grid_rows),
            palette={str(k): int(v) for k, v in palette_raw.items()},
            active_bead_count=bead_count,
            fill_order=tuple(order),
            completed=bool(data.get("completed", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.artwork_id,
            "artwork_id": self.artwork_id,
            "name": self.name,
            "tagline": self.tagline,
            "series_id": self.series_id,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "grid": [list(row) for row in self.grid],
            "palette": self.palette,
            "active_bead_count": self.active_bead_count,
            "fill_order": [list(pos) for pos in self.fill_order],
            "completed": self.completed,
        }


def load_artwork_catalog(path: Path) -> list[Artwork]:
    data = _read_json(path)
    artworks = [Artwork.from_dict(item) for item in data["artworks"]]
    ids = [artwork.artwork_id for artwork in artworks]
    if len(ids) != len(set(ids)):
        raise ValueError("artwork_catalog contains duplicate artwork_id values")
    return artworks
