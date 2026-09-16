"""v2 quota-aware session generator and benchmark runner."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time
from typing import Any

from ..candidates import (
    load_items,
    matched_positions,
    position_category,
)
from ..models import (
    GENERATOR_VERSION,
    BalanceDimension,
    GeneratorConfig,
    Item,
    PositionDimension,
    TrainingProfile,
)
from ..scoring import CoverageState
from ..timing import item_duration_sec
from .engine import (
    candidate_matches,
    classify_item,
    compute_availability,
    matched_group_patterns,
    matched_patterns,
    signature_of,
)
from .history import HistoryStore
from .schema import V2Profile

V2_VERSION = "v2.0"


def _synthetic_profile(profile: V2Profile) -> TrainingProfile:
    kind = {
        "initial": "initials",
        "final": "finals",
        "tone": "tones",
    }[profile.dimension]
    pos = PositionDimension(
        id="target_position",
        label="目标音位置",
        kind=kind,
        values=profile.target_value_union,
    )
    return TrainingProfile(
        id=profile.id,
        name=profile.name,
        aliases=[],
        candidate_rule={"field": "item_id", "is_not_null": True},
        balance_dimensions=[
            BalanceDimension(
                id="target_value",
                label="目标音",
                kind=kind,
                values=profile.target_value_union,
            )
        ],
        position_dimension=pos,
        purity=False,
        track_tone_pattern=True,
        track_word_length=True,
    )


class V2State:
    def __init__(self, profile: V2Profile, config: GeneratorConfig,
                 seq_profile: TrainingProfile) -> None:
        self.profile = profile
        self.config = config
        self.n_selected = 0
        self.selected_item_ids: set[str] = set()
        self.repeat_counts: Counter[str] = Counter()
        self.last_order: dict[str, int] = {}
        self.bucket_counts: Counter[str] = Counter()
        self.pattern_counts: Counter[str] = Counter()
        self.group_pattern_counts: Counter[str] = Counter()
        self.target_value_counts: Counter[str] = Counter()
        self.seq_state = CoverageState(seq_profile)
        self.target_history: list[set[str]] = []
        self.credited: list[tuple[str, str]] = []  # (item_id, pattern)

    def can_use(self, item: Item, bucket_id: str) -> bool:
        scarcity = self.profile.scarcity
        max_repeat = int(scarcity.get("max_repeat", 1))
        min_gap = int(scarcity.get("min_gap", 0))
        count = self.repeat_counts.get(item.item_id, 0)
        if count >= max_repeat:
            return False
        if count > 0 and min_gap > 0:
            last = self.last_order.get(item.item_id, -10**9)
            if self.n_selected - last < min_gap:
                return False
        return True

    def add(self, item: Item, bucket_id: str,
            credited_pattern: str, pattern_position: int) -> None:
        self.n_selected += 1
        self.selected_item_ids.add(item.item_id)
        self.repeat_counts[item.item_id] += 1
        self.last_order[item.item_id] = self.n_selected
        self.bucket_counts[bucket_id] += 1
        self.pattern_counts[credited_pattern] += 1
        self.credited.append((item.item_id, credited_pattern))
        for gpat in matched_group_patterns(item, self.profile):
            self.group_pattern_counts[gpat] += 1
        self.seq_state.add(item)
        values = set(signature_of(item, self.profile.dimension))
        self.target_history.append(values & set(self.profile.target_value_union))
        for v in self.target_history[-1]:
            self.target_value_counts[v] += 1

    def current_target_run(self, value: str) -> int:
        run = 0
        for values in reversed(self.target_history):
            if value in values:
                run += 1
            else:
                break
        return run

    def current_position_run(self, cat: str) -> int:
        return self.seq_state.current_position_run(cat)

    def current_length_run(self, bucket: str) -> int:
        return self.seq_state.current_length_run(bucket)

    def current_tone_run(self, pattern: str) -> int:
        return self.seq_state.current_tone_run(pattern)


def _target_positions(item: Item, profile: V2Profile) -> set[int]:
    kind = {
        "initial": "initials",
        "final": "finals",
        "tone": "tones",
    }[profile.dimension]
    pos = PositionDimension(
        id="p",
        label="p",
        kind=kind,
        values=profile.target_value_union,
    )
    return matched_positions(item, pos)


def v2_constraint_violations(item: Item, state: V2State, config: GeneratorConfig,
                             relax_level: int) -> list[str]:
    violations: list[str] = []
    values = set(signature_of(item, state.profile.dimension))
    target_values = values & set(state.profile.target_value_union)
    if relax_level < 4 and state.profile.dimension != "tone":
        for v in target_values:
            if state.current_target_run(v) + 1 > config.max_same_target_consecutive:
                violations.append(f"same_target:{v}")
                break
    if relax_level < 3:
        cat = position_category(_target_positions(item, state.profile))
        if cat and state.current_position_run(cat) + 1 > config.max_same_position_consecutive:
            violations.append(f"same_position:{cat}")
    if relax_level < 2:
        if state.current_length_run(item.length_bucket) + 1 > config.max_same_length_consecutive:
            violations.append(f"same_length:{item.length_bucket}")
    if relax_level < 1:
        if state.current_tone_run(item.tone_pattern_lexical) + 1 > config.max_same_tone_pattern_consecutive:
            violations.append(f"same_tone_pattern:{item.tone_pattern_lexical}")
    return violations


def _pick_bucket(state: V2State, planned_total: int,
                 rng: random.Random) -> str:
    profile = state.profile
    if len(profile.buckets) == 1:
        return profile.buckets[0].id
    target_counts = {
        b.id: int(round(b.target_ratio * planned_total))
        for b in profile.buckets
    }
    debts = {
        b.id: max(0, target_counts[b.id] - state.bucket_counts.get(b.id, 0))
        for b in profile.buckets
    }
    if sum(debts.values()) > 0:
        pool = [b.id for b in profile.buckets if debts[b.id] > 0]
        weights = [debts[b] for b in pool]
        return rng.choices(pool, weights=weights, k=1)[0]
    # All buckets at target: pick the one farthest below its ratio.
    n = max(1, state.n_selected)
    best = min(
        profile.buckets,
        key=lambda b: (
            state.bucket_counts.get(b.id, 0) / n
            - b.target_ratio
        ),
    )
    return best.id


def _score_candidates(
    items: list[Item], bucket_id: str, state: V2State,
    profile: V2Profile, availability: dict[str, Any], config: GeneratorConfig,
    rng: random.Random, pool_stats: dict[str, Any],
    recent_ids: set[str],
) -> list[tuple[Item, float, list[str]]]:
    n = state.n_selected
    bucket_stats = availability["buckets"].get(bucket_id, {})
    pat_counts = bucket_stats.get("patterns", {})
    pat_total = max(1, sum(pat_counts.values()))
    results: list[tuple[Item, float, list[str]]] = []
    for item in items:
        score = 1.0
        reasons: list[str] = []
        patterns = matched_patterns(item, profile)
        if patterns:
            deficit_sum = 0.0
            for pat in patterns:
                target = pat_counts.get(pat, 0) / pat_total
                current = (
                    state.pattern_counts.get(pat, 0)
                    / max(1, state.bucket_counts.get(bucket_id, 0))
                )
                deficit = max(0.0, target - current)
                deficit_sum += deficit
                if deficit > 0.02:
                    reasons.append(f"+ pattern {pat} 覆盖不足")
            score += config.weight_pattern * (deficit_sum / len(patterns))

        cat = position_category(_target_positions(item, profile))
        if cat:
            pos_stats = pool_stats.get("position", {})
            target = pos_stats.get("shares", {}).get(cat, 0.0)
            current = (
                state.seq_state.position_counts.get(cat, 0)
                / max(1, state.n_selected)
            )
            score += config.weight_position * max(0.0, target - current)

        len_stats = pool_stats.get("word_lengths", {})
        target_len = len_stats.get("shares", {}).get(item.length_bucket, 0.0)
        current_len = (
            state.seq_state.length_counts.get(item.length_bucket, 0)
            / max(1, state.n_selected)
        )
        score += config.weight_length * max(0.0, target_len - current_len)

        tone_stats = pool_stats.get("tone_patterns", {})
        target_tone = tone_stats.get("shares", {}).get(
            item.tone_pattern_lexical, 0.0
        )
        current_tone = (
            state.seq_state.tone_pattern_counts.get(item.tone_pattern_lexical, 0)
            / max(1, state.n_selected)
        )
        score += config.weight_tone_pattern * max(0.0, target_tone - current_tone)

        if item.item_id in recent_ids:
            score -= config.history_penalty
            reasons.append(f"- 近 {config.history_window_days} 天/近 {config.history_window_sessions} 次练过")

        score += rng.uniform(0.0, config.random_jitter)
        results.append((item, score, reasons))
    return results


def _bucket_pool_stats(items: list[Item], profile: V2Profile,
                       config: GeneratorConfig) -> dict[str, Any]:
    pos_counts: Counter[str] = Counter()
    len_counts: Counter[str] = Counter()
    tone_counts: Counter[str] = Counter()
    n = len(items)
    for item in items:
        cat = position_category(_target_positions(item, profile))
        if cat:
            pos_counts[cat] += 1
        len_counts[item.length_bucket] += 1
        tone_counts[item.tone_pattern_lexical] += 1
    return {
        "position": {
            "shares": {
                k: v / max(1, n) for k, v in pos_counts.items()
            }
        },
        "word_lengths": {
            "shares": {
                k: v / max(1, n) for k, v in len_counts.items()
            }
        },
        "tone_patterns": {
            "shares": {
                k: v / max(1, n) for k, v in tone_counts.items()
            }
        },
    }


def _choose_pattern(item: Item, state: V2State, profile: V2Profile,
                    bucket_id: str, availability: dict[str, Any],
                    rng: random.Random) -> tuple[str, int]:
    patterns = matched_patterns(item, profile)
    if not patterns:
        return "single", 1
    pat_counts = availability["buckets"].get(bucket_id, {}).get("patterns", {})
    pat_total = max(1, sum(pat_counts.values()))
    best_def = -1.0
    best: list[str] = []
    for i, pat in enumerate(patterns, start=1):
        target = pat_counts.get(pat, 0) / pat_total
        current = (
            state.pattern_counts.get(pat, 0)
            / max(1, state.bucket_counts.get(bucket_id, 0))
        )
        deficit = max(0.0, target - current)
        if deficit > best_def + 1e-9:
            best_def = deficit
            best = [(pat, i)]
        elif abs(deficit - best_def) <= 1e-9:
            best.append((pat, i))
    chosen = rng.choice(best) if best else (patterns[0], 1)
    return chosen


def _item_target_finals(item: Item, profile: V2Profile) -> set[str]:
    """Target values this item carries (final dimension only)."""
    return {
        s.final_canonical for s in item.syllables
    } & set(profile.target_value_union)


def _matches_final_filter(
    item: Item, profile: V2Profile, allowed: set[str]
) -> bool:
    """Keep an item when every target final it carries is whitelisted.

    Non-target finals (e.g. the ``a`` in ``安全 ānquán``-style supplement
    words) do not constrain the check; an item must carry at least one
    target final to survive.
    """
    target_finals = _item_target_finals(item, profile)
    return bool(target_finals) and target_finals <= allowed


def generate_session_v2(
    profile: V2Profile,
    config: GeneratorConfig,
    items: list[Item],
    availability: dict[str, Any],
    duration_minutes: int = 10,
    practice_repetitions: int = 1,
    auto_advance: bool = True,
    seed: int | None = None,
    history: HistoryStore | None = None,
    include_finals: list[str] | None = None,
) -> dict[str, Any]:
    if duration_minutes not in config.allowed_duration_minutes:
        raise ValueError(
            f"duration_minutes must be one of {config.allowed_duration_minutes}"
        )
    if include_finals is not None:
        allowed = set(include_finals)
        unknown = allowed - set(profile.target_value_union)
        if unknown:
            raise ValueError(
                f"include_finals not in profile target set: {sorted(unknown)}"
            )
    if seed is None:
        seed = int(time.time_ns() % 2**31)
    rng = random.Random(seed)
    recent_ids = history.recent_item_ids() if history is not None else set()
    seq_profile = _synthetic_profile(profile)
    state = V2State(profile, config, seq_profile)
    candidates = [i for i in items if candidate_matches(i, profile)]
    if include_finals is not None:
        allowed = set(include_finals)
        candidates = [
            i for i in candidates
            if _matches_final_filter(i, profile, allowed)
        ]
    if not candidates:
        raise ValueError(
            "include_finals leaves no usable candidates for this profile"
        )
    bucket_items: dict[str, list[Item]] = {b.id: [] for b in profile.buckets}
    for item in candidates:
        bucket_id = classify_item(item, profile)
        if bucket_id is not None:
            bucket_items[bucket_id].append(item)
    bucket_pool_stats = {
        b.id: _bucket_pool_stats(bucket_items[b.id], profile, config)
        for b in profile.buckets
    }
    avg_duration = (
        sum(item_duration_sec(i, config, practice_repetitions) for i in candidates)
        / max(1, len(candidates))
    )
    planned_total = int(duration_minutes * 60 / avg_duration)
    target_sec = duration_minutes * 60
    tolerance_abs = target_sec * config.duration_tolerance_ratio
    estimated_sec = 0.0
    relaxed_records: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    recent_selected = 0

    while True:
        remaining = target_sec - estimated_sec
        if remaining <= 0:
            break
        bucket_id = _pick_bucket(state, planned_total, rng)
        pool = bucket_items.get(bucket_id, [])
        fresh = [
            i for i in pool
            if state.repeat_counts.get(i.item_id, 0) == 0
        ]
        available = fresh or [
            i for i in pool if state.can_use(i, bucket_id)
        ]
        if not available:
            # Bucket exhausted: fall back to any bucket with remaining room.
            fallback = [
                b.id for b in profile.buckets
                if b.id != bucket_id
                and any(
                    state.repeat_counts.get(i.item_id, 0) == 0
                    for i in bucket_items[b.id]
                )
            ]
            if not fallback:
                break
            bucket_id = rng.choice(fallback)
            fb_pool = bucket_items[bucket_id]
            fb_fresh = [
                i for i in fb_pool
                if state.repeat_counts.get(i.item_id, 0) == 0
            ]
            available = fb_fresh or [
                i for i in fb_pool if state.can_use(i, bucket_id)
            ]
        scored = _score_candidates(
            available,
            bucket_id,
            state,
            profile,
            availability,
            config,
            rng,
            bucket_pool_stats[bucket_id],
            recent_ids,
        )
        scored.sort(key=lambda r: r[1], reverse=True)
        top = scored[: config.top_k]
        if not top:
            break
        fits = [
            r for r in top
            if item_duration_sec(r[0], config, practice_repetitions)
            <= remaining + tolerance_abs
        ]
        pick_pool = fits if fits else top
        excluded: set[str] = set()
        chosen = None
        relax_used = None
        for relax in range(5):
            for _attempt in range(config.max_attempts):
                pool_now = [
                    r for r in pick_pool
                    if r[0].item_id not in excluded
                ]
                if not pool_now and pick_pool is not top:
                    pick_pool = top
                    pool_now = [
                        r for r in top if r[0].item_id not in excluded
                    ]
                if not pool_now:
                    break
                weights = [max(r[1], 1e-9) for r in pool_now]
                result = rng.choices(pool_now, weights=weights, k=1)[0]
                violations = v2_constraint_violations(
                    result[0], state, config, relax
                )
                if not violations:
                    chosen = result
                    relax_used = relax
                    break
                excluded.add(result[0].item_id)
            if chosen is not None:
                break
        if chosen is None:
            remaining_pool = [
                r for r in top if state.can_use(r[0], bucket_id)
            ]
            if not remaining_pool:
                break
            if fits:
                chosen = max(remaining_pool, key=lambda r: r[1])
            else:
                chosen = min(
                    remaining_pool,
                    key=lambda r: item_duration_sec(
                        r[0], config, practice_repetitions
                    ),
                )
            relax_used = None

        item, score, reasons = chosen
        duration_sec = item_duration_sec(item, config, practice_repetitions)
        is_final_overshoot = duration_sec > remaining + tolerance_abs
        credited_pattern, pattern_position = _choose_pattern(
            item, state, profile, bucket_id, availability, rng
        )
        state.add(item, bucket_id, credited_pattern, pattern_position)
        if item.item_id in recent_ids:
            recent_selected += 1
        estimated_sec += duration_sec
        step = state.n_selected
        if relax_used is None:
            relaxed_records.append({"rule": "fallback_all", "step": step})
        else:
            for rule in (
                "tone_pattern",
                "length",
                "position",
                "target",
            )[:relax_used]:
                relaxed_records.append({"rule": rule, "step": step})
        if is_final_overshoot:
            relaxed_records.append(
                {"rule": "duration_final_overshoot", "step": step}
            )

        tf_values = sorted(
            set(signature_of(item, profile.dimension))
            & set(profile.target_value_union)
        )
        tf_positions = sorted(_target_positions(item, profile))
        bucket = next(b for b in profile.buckets if b.id == bucket_id)
        entries.append(
            {
                "order": step,
                "item_id": item.item_id,
                "word": item.word_raw,
                "pinyin": item.pinyin_nfc,
                "clip_path": item.clip_path,
                "clip_duration_ms": item.clip_duration_ms,
                "estimated_item_duration_sec": round(duration_sec, 3),
                "bucket_id": bucket.id,
                "bucket_label": bucket.label,
                "profile_role": bucket.role,
                "credited_pattern": credited_pattern,
                "pattern_position": pattern_position,
                "all_matched_patterns": matched_patterns(item, profile),
                "target_values": tf_values,
                "target_positions": tf_positions,
                "syllable_count": item.syllable_count,
                "tone_pattern": item.tone_pattern_lexical,
                "selection_score": round(score, 6),
                "selection_weight": round(max(score, 1e-9), 6),
                "selection_reason_summary": (
                    "; ".join(reasons[:5]) if reasons else "随机"
                ),
            }
        )
        if is_final_overshoot:
            break

    bucket_counts = dict(state.bucket_counts)
    bucket_time = {
        b.id: sum(
            e["estimated_item_duration_sec"]
            for e in entries
            if e["bucket_id"] == b.id
        )
        for b in profile.buckets
    }
    return {
        "session_id": (
            f"{profile.id}-{duration_minutes}m-seed{seed}-rep{practice_repetitions}"
        ),
        "generator_version": V2_VERSION,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "mode": profile.mode,
        "seed": seed,
        "include_finals": (
            sorted(set(include_finals)) if include_finals is not None else None
        ),
        "requested_duration_sec": target_sec,
        "estimated_duration_sec": round(estimated_sec, 3),
        "duration_abs_error_sec": round(estimated_sec - target_sec, 3),
        "duration_rel_error": round(
            (estimated_sec - target_sec) / target_sec, 6
        ),
        "practice_repetitions": practice_repetitions,
        "auto_advance": auto_advance,
        "item_count": len(entries),
        "candidate_count": len(candidates),
        "planned_total_items": planned_total,
        "relaxed_constraints": relaxed_records,
        "items": entries,
        "summary": {
            "bucket_item_shares": {
                b.id: {
                    "count": bucket_counts.get(b.id, 0),
                    "share": (
                        bucket_counts.get(b.id, 0) / max(1, len(entries))
                    ),
                }
                for b in profile.buckets
            },
            "bucket_time_shares": {
                b.id: round(bucket_time.get(b.id, 0.0) / max(1.0, estimated_sec), 4)
                for b in profile.buckets
            },
            "pattern_counts": dict(state.pattern_counts),
            "group_pattern_counts": dict(state.group_pattern_counts),
            "target_counts": dict(state.target_value_counts),
            "target_positions": dict(state.seq_state.position_counts),
            "word_lengths": dict(state.seq_state.length_counts),
            "tone_patterns": dict(state.seq_state.tone_pattern_counts),
            "repeated_items": {
                "count": sum(
                    1 for v in state.repeat_counts.values() if v > 1
                ),
                "examples": [
                    [iid, c]
                    for iid, c in state.repeat_counts.items()
                    if c > 1
                ][:10],
            },
            "core_pool_insufficient": any(
                b.id not in bucket_counts
                or bucket_counts[b.id] < planned_total * b.target_ratio * 0.75
                for b in profile.buckets
                if b.role in {"core", "cross"}
            ),
            "missing_theoretical_patterns": [
                m
                for b in profile.buckets
                for m in availability["buckets"]
                .get(b.id, {})
                .get("missing_patterns", [])
            ],
            "scarce_patterns": [
                list(s)
                for b in profile.buckets
                for s in availability["buckets"]
                .get(b.id, {})
                .get("scarce_patterns", [])
            ],
            "history": {
                "window_days": config.history_window_days,
                "window_sessions": config.history_window_sessions,
                "recent_items_known": len(recent_ids),
                "recent_items_selected": recent_selected,
                "penalty": config.history_penalty,
            },
        },
    }


def _universe_from_items(items: list[Item]) -> dict[str, list[str]]:
    initials: set[str] = set()
    finals: set[str] = set()
    tones: set[str] = set()
    for item in items:
        for s in item.syllables:
            initials.add(s.initial)
            finals.add(s.final_canonical)
            tones.add(str(s.tone))
    return {
        "initial": sorted(initials),
        "final": sorted(finals),
        "tone": sorted(tones),
    }


def run_availability_v2(data_root: Path, out_dir: Path,
                        profiles: list[V2Profile],
                        config: GeneratorConfig) -> dict[str, Any]:
    items = load_items(
        data_root / "derived/phonology-v1/phonology.sqlite3",
        data_root / "corpus.sqlite3",
    )
    universe = _universe_from_items(items)
    matrix = compute_availability(items, profiles, universe)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = out_dir / "profile_availability_v2.json"
    payload = {
        "generator_version": V2_VERSION,
        "profiles_version": "training_profiles_v2.json",
        "data_version": "formal_corpus_2026-08-08_16156",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **matrix,
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    from .report import build_availability_report

    report_path = out_dir / "PROFILE_AVAILABILITY_REPORT_V2.md"
    report_path.write_text(
        build_availability_report(payload), encoding="utf-8"
    )
    return {
        "command": "availability-v2",
        "status": "succeeded",
        "profile_count": len(profiles),
        "report": str(report_path),
        "stats": str(stats_path),
    }


def run_benchmark_v2(data_root: Path, out_dir: Path,
                     profiles: list[V2Profile],
                     config: GeneratorConfig) -> dict[str, Any]:
    """Run the v2 first-batch session matrix and write stats/report."""
    items = load_items(
        data_root / "derived/phonology-v1/phonology.sqlite3",
        data_root / "corpus.sqlite3",
    )
    universe = _universe_from_items(items)
    availability_all = compute_availability(items, profiles, universe)
    availability_by_id = {
        p["profile_id"]: p for p in availability_all["profiles"]
    }
    by_id = {p.id: p for p in profiles}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sessions").mkdir(parents=True, exist_ok=True)

    main_ids = [
        "bilabial_focus",
        "flat_focus",
        "retroflex_focus",
        "flat_retroflex_contrast",
        "n_l_contrast",
        "jqx_special",
        "simple_final_focus",
        "compound_front",
        "front_nasal_basic",
        "back_nasal_basic",
        "front_back_nasal_contrast_1",
        "front_back_nasal_contrast_2",
        "tone_1",
        "tone_3",
        "tone_all",
    ]
    duration_sample_ids = [
        "flat_focus",
        "flat_retroflex_contrast",
        "simple_final_focus",
        "front_back_nasal_contrast_1",
    ]
    runs: list[tuple[V2Profile, int, int]] = []
    for pid in main_ids:
        runs.append((by_id[pid], 10, 20260804))
        runs.append((by_id[pid], 10, 20260805))
        runs.append((by_id[pid], 10, 20260806))
    for pid in duration_sample_ids:
        for seed in (20260801, 20260802, 20260803):
            runs.append((by_id[pid], 5, seed))
        for seed in (20260807, 20260808):
            runs.append((by_id[pid], 20, seed))

    session_stats: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for profile, duration, seed in runs:
        try:
            session = generate_session_v2(
                profile,
                config,
                items,
                availability_by_id[profile.id],
                duration_minutes=duration,
                seed=seed,
            )
            path = out_dir / "sessions" / profile.id / f"{session['session_id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(session, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            regenerated = generate_session_v2(
                profile,
                config,
                items,
                availability_by_id[profile.id],
                duration_minutes=duration,
                seed=seed,
            )
            errors: list[str] = []
            ids = [e["item_id"] for e in session["items"]]
            freq = Counter(ids)
            max_repeat = int(profile.scarcity.get("max_repeat", 1))
            min_gap = int(profile.scarcity.get("min_gap", 0))
            if any(v > max_repeat for v in freq.values()):
                errors.append("duplicate_item")
            positions: dict[str, list[int]] = {}
            for idx, eid in enumerate(ids, start=1):
                positions.setdefault(eid, []).append(idx)
            for eid, pos_list in positions.items():
                if len(pos_list) > 1:
                    for a, b in zip(pos_list, pos_list[1:]):
                        if b - a < min_gap:
                            errors.append(f"repeat_gap:{eid}")
            regen_ids = [e["item_id"] for e in regenerated["items"]]
            if ids != regen_ids:
                errors.append("reproducibility_mismatch")
            for entry in session["items"]:
                item = next(i for i in items if i.item_id == entry["item_id"])
                if not candidate_matches(item, profile):
                    errors.append(f"profile_mismatch:{entry['item_id']}")
                if classify_item(item, profile) != entry["bucket_id"]:
                    errors.append(f"bucket_mismatch:{entry['item_id']}")
            session_stats.append(
                {
                    "session_id": session["session_id"],
                    "profile_id": profile.id,
                    "seed": seed,
                    "duration_minutes": duration,
                    "item_count": session["item_count"],
                    "estimated_duration_sec": session["estimated_duration_sec"],
                    "duration_rel_error": session["duration_rel_error"],
                    "bucket_item_shares": session["summary"]["bucket_item_shares"],
                    "bucket_time_shares": session["summary"]["bucket_time_shares"],
                    "pattern_counts": session["summary"]["pattern_counts"],
                    "target_counts": session["summary"]["target_counts"],
                    "target_positions": session["summary"]["target_positions"],
                    "word_lengths": session["summary"]["word_lengths"],
                    "tone_patterns": session["summary"]["tone_patterns"],
                    "repeated_items": session["summary"]["repeated_items"],
                    "relaxed_constraints": session["relaxed_constraints"],
                    "qa_errors": errors,
                    "session_path": str(path),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {
                    "profile_id": profile.id,
                    "duration_minutes": duration,
                    "seed": seed,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    all_errors = [e for s in session_stats for e in s["qa_errors"]]
    summary = {
        "generator_version": V2_VERSION,
        "profiles_version": "training_profiles_v2.json",
        "data_version": "formal_corpus_2026-08-08_16156",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_total": len(session_stats),
        "session_stats": session_stats,
        "qa_summary": {
            "sessions": len(session_stats),
            "profile_errors": sum(
                1 for e in all_errors if e.startswith("profile_mismatch")
            ),
            "bucket_errors": sum(
                1 for e in all_errors if e.startswith("bucket_mismatch")
            ),
            "duplicate_errors": sum(1 for e in all_errors if e == "duplicate_item"),
            "reproducibility_errors": sum(
                1 for e in all_errors if e == "reproducibility_mismatch"
            ),
            "generation_failures": len(failures),
            "max_duration_rel_error": round(
                max(
                    (abs(s["duration_rel_error"]) for s in session_stats),
                    default=0.0,
                ),
                6,
            ),
        },
        "failures": failures,
        "config": config.to_dict(),
    }
    stats_path = out_dir / "generator_stats_v2.json"
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    from .report import build_generator_report_v2

    report_path = out_dir / "GENERATOR_REPORT_V2.md"
    report_path.write_text(
        build_generator_report_v2(summary, profiles, config),
        encoding="utf-8",
    )
    return {
        "command": "benchmark-v2",
        "status": "succeeded" if not failures else "partial",
        "sessions_total": len(session_stats),
        "generation_failures": len(failures),
        "report": str(report_path),
        "stats": str(stats_path),
    }
