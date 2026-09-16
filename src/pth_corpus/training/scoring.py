"""Coverage state and dynamic weighting for the generator."""

from __future__ import annotations

from collections import Counter
import random
from typing import Any

from .candidates import (
    build_profile_index,
    matched_positions,
    matched_values,
    occurrence_bucket,
    position_category,
    purity_bucket,
)
from .models import Item, TrainingProfile


class CoverageState:
    """Tracks what a session has covered so far, plus trailing-item history."""

    def __init__(self, profile: TrainingProfile,
                 index: dict[str, dict[str, Any]] | None = None) -> None:
        self.profile = profile
        self.index = index or {}
        self.n_selected = 0
        self.selected_item_ids: set[str] = set()
        self.dim_counts: dict[str, Counter[str]] = {
            d.id: Counter() for d in profile.balance_dimensions
        }
        self.group_counts: dict[str, Counter[str]] = {
            d.id: Counter() for d in profile.balance_dimensions
        }
        self.position_counts: Counter[str] = Counter()
        self.occurrence_counts: Counter[str] = Counter()
        self.purity_counts: Counter[str] = Counter()
        self.length_counts: Counter[str] = Counter()
        self.tone_pattern_counts: Counter[str] = Counter()
        # One entry per selected item for run checks.
        self.history: list[dict[str, Any]] = []

    def _entry(self, item: Item) -> dict[str, Any]:
        cached = self.index.get(item.item_id)
        if cached is not None:
            return {
                "dims": {k: set(v) for k, v in cached["dims"].items()},
                "groups": {k: set(v) for k, v in cached["groups"].items()},
                "position": cached["position"],
                "occurrence": cached["occurrence"],
                "purity": cached["purity"],
                "length": cached["length"],
                "tone_pattern": cached["tone_pattern"],
            }
        dims: dict[str, set[str]] = {}
        groups: dict[str, set[str]] = {}
        for dim in self.profile.balance_dimensions:
            vals = matched_values(item, dim)
            dims[dim.id] = set(vals)
            gs = set()
            for gid, gvals in dim.groups.items():
                if any(v in gvals for v in vals):
                    gs.add(gid)
            groups[dim.id] = gs
        positions = (
            matched_positions(item, self.profile.position_dimension)
            if self.profile.position_dimension
            else set()
        )
        return {
            "dims": dims,
            "groups": groups,
            "position": position_category(positions),
            "occurrence": occurrence_bucket(len(positions)),
            "purity": purity_bucket(len(positions), item.syllable_count),
            "length": item.length_bucket,
            "tone_pattern": item.tone_pattern_lexical,
        }

    def add(self, item: Item) -> None:
        self.selected_item_ids.add(item.item_id)
        self.n_selected += 1
        entry = self._entry(item)
        for dim_id, vals in entry["dims"].items():
            for v in vals:
                self.dim_counts[dim_id][v] += 1
        for dim_id, gs in entry["groups"].items():
            for g in gs:
                self.group_counts[dim_id][g] += 1
        if entry["position"]:
            self.position_counts[entry["position"]] += 1
        self.occurrence_counts[entry["occurrence"]] += 1
        self.purity_counts[entry["purity"]] += 1
        self.length_counts[entry["length"]] += 1
        self.tone_pattern_counts[entry["tone_pattern"]] += 1
        self.history.append(entry)

    def current_dim_run(self, dim_id: str, value: str) -> int:
        run = 0
        for entry in reversed(self.history):
            if value in entry["dims"].get(dim_id, set()):
                run += 1
            else:
                break
        return run

    def current_group_run(self, dim_id: str, gid: str) -> int:
        run = 0
        for entry in reversed(self.history):
            if gid in entry["groups"].get(dim_id, set()):
                run += 1
            else:
                break
        return run

    def current_position_run(self, cat: str) -> int:
        run = 0
        for entry in reversed(self.history):
            if entry["position"] == cat:
                run += 1
            else:
                break
        return run

    def current_length_run(self, bucket: str) -> int:
        run = 0
        for entry in reversed(self.history):
            if entry["length"] == bucket:
                run += 1
            else:
                break
        return run

    def current_tone_run(self, pattern: str) -> int:
        run = 0
        for entry in reversed(self.history):
            if entry["tone_pattern"] == pattern:
                run += 1
            else:
                break
        return run


def _share(counts: Counter[str], key: str, n_selected: int) -> float:
    return counts.get(key, 0) / n_selected if n_selected else 0.0


def score_candidates(candidates: list[Item], state: CoverageState,
                     pool_stats: dict[str, Any], profile: TrainingProfile,
                     config: Any, rng: random.Random,
                     index: dict[str, dict[str, Any]] | None = None
                     ) -> list[tuple[Item, float, list[str]]]:
    """Return (item, score, reason-list) tuples, higher score = better."""
    n = state.n_selected
    results: list[tuple[Item, float, list[str]]] = []
    index = index or {}
    for item in candidates:
        score = 1.0
        reasons: list[str] = []
        cached = index.get(item.item_id)

        for dim in profile.balance_dimensions:
            vals = (
                list(cached["dims"][dim.id])
                if cached is not None
                else matched_values(item, dim)
            )
            if not vals:
                continue
            dim_stats = pool_stats["dimensions"][dim.id]
            counts = state.dim_counts[dim.id]
            cov = 0.0
            for v in vals:
                target = dim_stats.get("target_shares", dim_stats["shares"]).get(
                    v, 0.0
                )
                current = _share(counts, v, n)
                deficit = max(0.0, target - current)
                overshoot = max(0.0, current - target)
                cov += deficit - config.weight_overshoot_penalty * overshoot
                if deficit > 0.02:
                    reasons.append(f"+ {dim.label}:{v} 覆盖不足")
                if overshoot > 0.02:
                    reasons.append(f"- {dim.label}:{v} 偏多")
            score += config.weight_coverage * (cov / len(vals))

            if dim.groups:
                g_matched = (
                    list(cached["groups"][dim.id])
                    if cached is not None
                    else [
                        gid for gid, gvals in dim.groups.items()
                        if any(v in gvals for v in vals)
                    ]
                )
                if g_matched:
                    g_cov = 0.0
                    for gid in g_matched:
                        gtarget = dim_stats.get("group_target_shares", {}).get(
                            gid,
                            dim_stats["group_shares"].get(gid, 0.0),
                        )
                        gcurrent = _share(state.group_counts[dim.id], gid, n)
                        deficit = max(0.0, gtarget - gcurrent)
                        overshoot = max(0.0, gcurrent - gtarget)
                        g_cov += deficit - config.weight_overshoot_penalty * overshoot
                        if deficit > 0.02:
                            reasons.append(f"+ 组 {gid} 覆盖不足")
                    score += config.weight_group * (g_cov / len(g_matched))

        if profile.position_dimension:
            cat = (
                cached["position"]
                if cached is not None
                else position_category(
                    matched_positions(item, profile.position_dimension)
                )
            )
            if cat:
                target = pool_stats["position"]["shares"].get(cat, 0.0)
                current = _share(state.position_counts, cat, n)
                deficit = max(0.0, target - current)
                overshoot = max(0.0, current - target)
                score += config.weight_position * (
                    deficit - config.weight_overshoot_penalty * overshoot
                )
                if deficit > 0.02:
                    reasons.append(f"+ 位置 {cat} 覆盖不足")
                if overshoot > 0.02:
                    reasons.append(f"- 位置 {cat} 偏多")

        if profile.track_word_length:
            bucket = cached["length"] if cached is not None else item.length_bucket
            target = pool_stats["word_lengths"]["shares"].get(
                bucket, 0.0
            )
            current = _share(state.length_counts, bucket, n)
            deficit = max(0.0, target - current)
            score += config.weight_length * deficit
            if deficit > 0.02:
                reasons.append(f"+ 词长 {bucket} 覆盖不足")

        if profile.track_tone_pattern:
            pattern = (
                cached["tone_pattern"]
                if cached is not None
                else item.tone_pattern_lexical
            )
            target = pool_stats["tone_patterns"]["shares"].get(
                pattern, 0.0
            )
            current = _share(state.tone_pattern_counts, pattern, n)
            deficit = max(0.0, target - current)
            score += config.weight_tone_pattern * deficit
            if deficit > 0.02:
                reasons.append(f"+ 调型 {pattern} 覆盖不足")

        if profile.purity and profile.position_dimension:
            occ = (
                cached["position_count"]
                if cached is not None
                else len(matched_positions(item, profile.position_dimension))
            )
            purity_w = (
                profile.purity_weight
                if profile.purity_weight is not None
                else config.weight_purity
            )
            if profile.purity_target_shares:
                # Bucket balancing: mostly full-target items with a controlled
                # share of single/partial-target items (e.g. 70% full / 30% partial).
                bucket = purity_bucket(occ, item.syllable_count)
                if bucket in profile.purity_target_shares:
                    target = profile.purity_target_shares[bucket]
                    current = _share(state.purity_counts, bucket, n)
                    deficit = max(0.0, target - current)
                    overshoot = max(0.0, current - target)
                    score += purity_w * (
                        deficit - config.weight_overshoot_penalty * overshoot
                    )
                    if deficit > 0.02:
                        reasons.append(f"+ 纯度 {bucket} 覆盖不足")
                    if overshoot > 0.02:
                        reasons.append(f"- 纯度 {bucket} 偏多")
            else:
                score += purity_w * (occ / max(1, item.syllable_count))

        score += rng.uniform(0.0, config.random_jitter)
        results.append((item, score, reasons))
    return results
