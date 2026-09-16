"""Duration estimation and time-budget helpers."""

from __future__ import annotations

from typing import Any

from .models import Item


def follow_window_sec(item: Item, config: Any) -> float:
    return max(
        item.clip_duration_sec + config.extra_follow_sec,
        config.min_follow_sec,
    )


def item_duration_sec(item: Item, config: Any, practice_repetitions: int) -> float:
    clip = item.clip_duration_sec
    follow = max(clip + config.extra_follow_sec, config.min_follow_sec)
    if practice_repetitions == 1:
        return clip + follow + config.transition_sec
    return (clip + follow) * 2 + config.transition_sec
