"""Signature builder, bucket classifier and availability matrix for v2."""

from __future__ import annotations

from collections import Counter
from itertools import product
from typing import Any

from ..models import Item
from .schema import V2Profile


def signature_of(item: Item, dimension: str) -> list[str]:
    if dimension == "initial":
        return [s.initial for s in item.syllables]
    if dimension == "final":
        return [s.final_canonical for s in item.syllables]
    if dimension == "tone":
        return [str(s.tone) for s in item.syllables]
    raise ValueError(f"unknown v2 dimension: {dimension}")


def _set_union(profile: V2Profile, names: list[str]) -> set[str]:
    union: set[str] = set()
    for name in names:
        union.update(profile.target_sets.get(name, []))
    return union


def _eval_rule(values: list[str], rule: dict[str, Any],
               profile: V2Profile) -> bool:
    op = rule.get("op")
    if op == "always":
        return bool(values)
    if op == "all":
        return all(_eval_rule(values, r, profile) for r in rule.get("rules", []))
    if op == "any":
        return any(_eval_rule(values, r, profile) for r in rule.get("rules", []))
    if op == "not":
        return not _eval_rule(values, rule.get("rule", {}), profile)
    if op == "all_in":
        allowed = _set_union(profile, rule.get("sets", []))
        return bool(values) and set(values) <= allowed
    if op == "any_in":
        allowed = _set_union(profile, rule.get("sets", []))
        return bool(set(values) & allowed)
    if op == "groups_present":
        min_groups = int(rule.get("min", 2))
        present = 0
        for name in rule.get("sets", []):
            if set(values) & _set_union(profile, [name]):
                present += 1
        return present >= min_groups
    if op == "adjacent_window":
        window = [str(v) for v in rule.get("values", [])]
        width = len(window)
        return any(
            values[i : i + width] == window
            for i in range(len(values) - width + 1)
        )
    raise ValueError(f"unknown v2 rule op: {op}")


def candidate_matches(item: Item, profile: V2Profile) -> bool:
    values = signature_of(item, profile.dimension)
    if not values:
        return False
    if profile.candidate_rule:
        matched = _eval_rule(values, profile.candidate_rule, profile)
    else:
        matched = _eval_rule(
            values,
            {"op": "any_in", "sets": profile.target_set_names},
            profile,
        )
    if not matched:
        return False
    if profile.flag_rule is not None:
        return _eval_flag_rule(item, profile.flag_rule)
    return True


def _eval_flag_rule(item: Item, rule: dict[str, Any]) -> bool:
    """Evaluate a rule against boolean item flags (e.g. has_erhua)."""

    op = rule.get("op")
    if op == "all":
        return all(_eval_flag_rule(item, r) for r in rule.get("rules", []))
    if op == "any":
        return any(_eval_flag_rule(item, r) for r in rule.get("rules", []))
    if op == "not":
        return not _eval_flag_rule(item, rule.get("rule", {}))
    field = rule.get("field")
    if field is None:
        raise ValueError(f"flag rule without field: {rule}")
    expected = bool(int(rule.get("eq", 1)))
    return bool(getattr(item, field, 0)) == expected


def classify_item(item: Item, profile: V2Profile) -> str | None:
    """Return the first matching bucket id, or None if not a candidate."""
    if not candidate_matches(item, profile):
        return None
    values = signature_of(item, profile.dimension)
    for bucket in profile.buckets:
        if _eval_rule(values, bucket.rule, profile):
            return bucket.id
    return None


def value_group(value: str, profile: V2Profile) -> str | None:
    for name, values in profile.target_sets.items():
        if value in values:
            return name
    return "O"


def matched_patterns(item: Item, profile: V2Profile) -> list[str]:
    """Concrete ordered patterns: single value or adjacent pairs."""
    values = signature_of(item, profile.dimension)
    if len(values) == 1:
        return [f"{values[0]}"]
    return [f"{values[i]}+{values[i + 1]}" for i in range(len(values) - 1)]


def matched_group_patterns(item: Item, profile: V2Profile) -> list[str]:
    values = signature_of(item, profile.dimension)
    groups = [value_group(v, profile) or "O" for v in values]
    if len(groups) == 1:
        return [groups[0]]
    return [f"{groups[i]}+{groups[i + 1]}" for i in range(len(groups) - 1)]


def compute_availability(items: list[Item], profiles: list[V2Profile],
                         universe: dict[str, list[str]],
                         avg_item_duration_sec: float = 3.2) -> dict[str, Any]:
    """Build the v2 availability matrix for every profile."""
    result_profiles: list[dict[str, Any]] = []

    for profile in profiles:
        candidates = [i for i in items if candidate_matches(i, profile)]
        bucket_items: dict[str, list[Item]] = {
            b.id: [] for b in profile.buckets
        }
        for item in candidates:
            bucket_id = classify_item(item, profile)
            if bucket_id is not None:
                bucket_items[bucket_id].append(item)

        buckets_out: dict[str, Any] = {}
        for bucket in profile.buckets:
            pool = bucket_items[bucket.id]
            pattern_counts: Counter[str] = Counter()
            group_counts: Counter[str] = Counter()
            length_counts: Counter[str] = Counter()
            for item in pool:
                for pat in matched_patterns(item, profile):
                    pattern_counts[pat] += 1
                for gpat in matched_group_patterns(item, profile):
                    group_counts[gpat] += 1
                length_counts[item.length_bucket] += 1
            missing: list[str] = []
            scarce: list[tuple[str, int]] = []
            for a, b in expand_pair_specs_for_bucket(profile, bucket, universe):
                key = f"{a}+{b}"
                count = pattern_counts.get(key, 0)
                if count == 0:
                    missing.append(key)
                elif count < 10:
                    scarce.append((key, count))
            buckets_out[bucket.id] = {
                "label": bucket.label,
                "target_ratio": bucket.target_ratio,
                "role": bucket.role,
                "item_count": len(pool),
                "single_count": length_counts.get("1", 0),
                "two_count": length_counts.get("2", 0),
                "three_plus_count": sum(
                    v for k, v in length_counts.items() if k not in {"1", "2"}
                ),
                "patterns": dict(sorted(pattern_counts.items())),
                "group_patterns": dict(sorted(group_counts.items())),
                "missing_patterns": missing,
                "scarce_patterns": [list(x) for x in scarce],
            }

        core_roles = {"core", "cross", "same", "all", "adjacent"}
        core_pool_size = sum(
            len(bucket_items.get(b.id, []))
            for b in profile.buckets
            if b.role in core_roles
        )
        if profile.mode == "contrast" or len(profile.buckets) == 1:
            core_ratio = 1.0
        else:
            core_ratio = next(
                (
                    b.target_ratio
                    for b in profile.buckets
                    if b.role in core_roles
                ),
                1.0,
            )
        durations: dict[str, Any] = {}
        for minutes in (5, 10, 15, 20):
            planned = int(minutes * 60 / avg_item_duration_sec)
            needed = int(round(planned * core_ratio))
            if core_pool_size >= needed:
                status = "OK"
                note = ""
            elif core_pool_size * 2 >= needed:
                status = "need_repeat"
                note = f"核心唯一池 {core_pool_size}，缺 {needed - core_pool_size}，需间隔重复"
            else:
                status = "insufficient"
                note = f"核心唯一池 {core_pool_size}，即使间隔重复也无法满足 {needed}"
            durations[str(minutes)] = {
                "planned_items": planned,
                "core_needed": needed,
                "core_unique_pool": core_pool_size,
                "status": status,
                "note": note,
            }

        result_profiles.append(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "dimension": profile.dimension,
                "mode": profile.mode,
                "candidate_count": len(candidates),
                "target_sets": profile.target_sets,
                "allow_other": profile.allow_other,
                "buckets": buckets_out,
                "core_pool_size": core_pool_size,
                "duration_sufficiency": durations,
                "notes": profile.notes,
            }
        )

    return {
        "profiles": result_profiles,
        "available_item_count": len(items),
        "avg_item_duration_sec": avg_item_duration_sec,
    }


def expand_pair_specs_for_bucket(
    profile: V2Profile, bucket: Any,
    universe: dict[str, list[str]],
) -> list[tuple[str, str]]:
    all_target = set(profile.target_value_union)
    others = [v for v in universe.get(profile.dimension, []) if v not in all_target]

    def values_of(name: str) -> list[str]:
        if name == "O":
            return others
        return profile.target_sets.get(name, [])

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for spec in bucket.pair_specs:
        for a, b in product(
            values_of(spec.get("left", "")),
            values_of(spec.get("right", "")),
        ):
            if (a, b) not in seen:
                seen.add((a, b))
                pairs.append((a, b))
    return pairs
