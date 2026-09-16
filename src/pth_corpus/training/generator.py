"""Balanced random training-session generator."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys
from typing import Any

from .candidates import (
    _evaluate_rule,
    build_profile_index,
    compute_all_pool_stats,
    compute_pool_stats,
    filter_candidates,
    load_items,
    matched_positions,
    matched_values,
    position_category,
)
from .constraints import RELAX_ORDER, constraint_violations
from .models import (
    DEFAULT_SEED,
    GENERATOR_VERSION,
    CANDIDATE_REPORT_FILENAME,
    CANDIDATE_STATS_FILENAME,
    CONFIG_FILENAME,
    GENERATOR_REPORT_FILENAME,
    GENERATOR_STATS_FILENAME,
    Item,
    PROFILES_FILENAME,
    SOURCE_DATA_VERSION,
    TrainingProfile,
    load_config,
    load_profiles,
)
from .report import build_candidate_pool_report, build_generator_report
from .scoring import CoverageState, score_candidates
from .timing import item_duration_sec


def _target_features(item: Item, profile: TrainingProfile) -> dict[str, Any]:
    dims: dict[str, list[str]] = {}
    primary: list[str] = []
    groups: list[str] = []
    for dim in profile.balance_dimensions:
        vals = matched_values(item, dim)
        dims[dim.id] = vals
        if dim.primary:
            primary.extend(vals)
        for gid, gvals in dim.groups.items():
            if any(v in gvals for v in vals):
                groups.append(gid)
    if not primary and profile.balance_dimensions:
        primary = dims.get(profile.balance_dimensions[0].id, [])
    positions = (
        matched_positions(item, profile.position_dimension)
        if profile.position_dimension
        else set()
    )
    return {
        "dimensions": dims,
        "target_subfeatures": sorted(set(primary)),
        "target_groups": sorted(set(groups)),
        "target_positions": sorted(positions),
        "target_occurrence_count": len(positions),
    }


def _coverage_summary(profile: TrainingProfile,
                      state: CoverageState) -> dict[str, Any]:
    return {
        "dimensions": {
            dim_id: dict(counter)
            for dim_id, counter in state.dim_counts.items()
        },
        "groups": {
            dim_id: dict(counter)
            for dim_id, counter in state.group_counts.items()
        },
        "positions": dict(state.position_counts),
        "occurrences": dict(state.occurrence_counts),
        "purity": dict(state.purity_counts),
        "word_lengths": dict(state.length_counts),
        "tone_patterns": dict(state.tone_pattern_counts),
    }


def _select_next(candidates: list[Item], state: CoverageState,
                 pool_stats: dict[str, Any], profile: TrainingProfile,
                 config: Any, rng: random.Random, remaining_sec: float,
                 tolerance_abs: float,
                 practice_repetitions: int,
                 index: dict[str, dict[str, Any]] | None = None
                 ) -> tuple[tuple[Item, float, list[str]] | None, int | None]:
    """Weighted top-K pick that respects sequence constraints and time fit."""
    scored = score_candidates(
        candidates, state, pool_stats, profile, config, rng, index
    )
    scored.sort(key=lambda r: r[1], reverse=True)
    top = scored[: config.top_k]
    if not top:
        return None, None

    fits = [
        r for r in top
        if item_duration_sec(r[0], config, practice_repetitions)
        <= remaining_sec + tolerance_abs
    ]
    pick_pool = fits if fits else top
    broadened = bool(fits)
    excluded: set[str] = set()

    for relax in range(5):
        for _attempt in range(config.max_attempts):
            pool = [r for r in pick_pool if r[0].item_id not in excluded]
            if not pool and broadened:
                # All fitting candidates were exhausted; broaden to the top-K pool.
                pick_pool = top
                broadened = False
                pool = [r for r in top if r[0].item_id not in excluded]
            if not pool:
                break
            weights = [max(r[1], 1e-9) for r in pool]
            chosen = rng.choices(pool, weights=weights, k=1)[0]
            violations = constraint_violations(
                chosen[0], state, profile, config, relax, index
            )
            if not violations:
                return chosen, relax
            excluded.add(chosen[0].item_id)

    remaining_pool = [r for r in top if r[0].item_id not in state.selected_item_ids]
    if not remaining_pool:
        return None, None
    # Nothing fits inside the remaining budget: take the shortest item to keep
    # the final overshoot as small as possible (constraint fallback).
    chosen = min(
        remaining_pool,
        key=lambda r: item_duration_sec(r[0], config, practice_repetitions),
    )
    return chosen, None


def generate_session(profile: TrainingProfile, config: Any, items: list[Item],
                     duration_minutes: int = 10,
                     practice_repetitions: int = 1,
                     auto_advance: bool = True,
                     seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Generate one balanced-random training session (pure, no file writes)."""
    if duration_minutes not in config.allowed_duration_minutes:
        raise ValueError(
            f"duration_minutes must be one of {config.allowed_duration_minutes}, "
            f"got {duration_minutes}"
        )
    if practice_repetitions not in config.allowed_practice_repetitions:
        raise ValueError(
            f"practice_repetitions must be one of "
            f"{config.allowed_practice_repetitions}, got {practice_repetitions}"
        )

    rng = random.Random(seed)
    candidates = filter_candidates(items, profile)
    pool_stats = compute_pool_stats(candidates, profile, config)
    index = build_profile_index(candidates, profile)
    state = CoverageState(profile, index)
    target_sec = duration_minutes * 60
    tolerance_abs = target_sec * config.duration_tolerance_ratio
    estimated_sec = 0.0
    relaxed_records: list[dict[str, Any]] = []
    selected_entries: list[dict[str, Any]] = []

    while True:
        remaining = target_sec - estimated_sec
        if remaining <= 0:
            break
        available = [
            i for i in candidates if i.item_id not in state.selected_item_ids
        ]
        if not available:
            break
        chosen, relax_used = _select_next(
            available,
            state,
            pool_stats,
            profile,
            config,
            rng,
            remaining,
            tolerance_abs,
            practice_repetitions,
            index,
        )
        if chosen is None:
            break
        item, score, reasons = chosen
        duration_sec = item_duration_sec(item, config, practice_repetitions)
        is_final_overshoot = duration_sec > remaining + tolerance_abs

        state.add(item)
        estimated_sec += duration_sec
        step = state.n_selected
        if relax_used is None:
            relaxed_records.append({"rule": "fallback_all", "step": step})
        else:
            for rule in RELAX_ORDER[:relax_used]:
                relaxed_records.append({"rule": rule, "step": step})
        if is_final_overshoot:
            relaxed_records.append(
                {"rule": "duration_final_overshoot", "step": step}
            )

        reason_summary = "; ".join(reasons[:5]) if reasons else "随机"
        selected_entries.append(
            item.to_session_entry(
                order=step,
                target_features=_target_features(item, profile),
                duration_sec=duration_sec,
                score=score,
                reason_summary=reason_summary,
            )
        )
        if is_final_overshoot:
            break

    return {
        "session_id": (
            f"{profile.id}-{duration_minutes}m-seed{seed}-rep{practice_repetitions}"
        ),
        "generator_version": GENERATOR_VERSION,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "seed": seed,
        "requested_duration_sec": target_sec,
        "estimated_duration_sec": round(estimated_sec, 3),
        "duration_abs_error_sec": round(estimated_sec - target_sec, 3),
        "duration_rel_error": round(
            (estimated_sec - target_sec) / target_sec, 6
        ),
        "practice_repetitions": practice_repetitions,
        "auto_advance": auto_advance,
        "item_count": len(selected_entries),
        "candidate_count": len(candidates),
        "relaxed_constraints": relaxed_records,
        "items": selected_entries,
        "coverage_summary": _coverage_summary(profile, state),
    }


def write_session_file(session: dict[str, Any], out_dir: Path) -> Path:
    profile_dir = out_dir / "sessions" / session["profile_id"]
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / f"{session['session_id']}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(session, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def _max_runs(entries: list[dict[str, Any]], profile: TrainingProfile,
              items_by_id: dict[str, Item]) -> dict[str, int]:
    selected_items = [items_by_id[e["item_id"]] for e in entries]
    state = CoverageState(
        profile, build_profile_index(selected_items, profile)
    )
    max_target = 0
    max_position = 0
    max_length = 0
    max_tone = 0
    for entry in entries:
        item = items_by_id[entry["item_id"]]
        for dim in profile.balance_dimensions:
            if dim.kind not in {"initials", "finals"}:
                continue
            for v in matched_values(item, dim):
                max_target = max(
                    max_target, state.current_dim_run(dim.id, v) + 1
                )
            for gid, gvals in dim.groups.items():
                if any(v in gvals for v in matched_values(item, dim)):
                    max_target = max(
                        max_target, state.current_group_run(dim.id, gid) + 1
                    )
        if profile.position_dimension:
            cat = position_category(
                matched_positions(item, profile.position_dimension)
            )
            if cat:
                max_position = max(
                    max_position, state.current_position_run(cat) + 1
                )
        max_length = max(
            max_length, state.current_length_run(item.length_bucket) + 1
        )
        if profile.track_tone_pattern:
            max_tone = max(
                max_tone, state.current_tone_run(item.tone_pattern_lexical) + 1
            )
        state.add(item)
    return {
        "max_same_target_run": max_target,
        "max_same_position_run": max_position,
        "max_same_length_run": max_length,
        "max_same_tone_pattern_run": max_tone,
    }


def _session_qa(session: dict[str, Any], profile: TrainingProfile,
                items_by_id: dict[str, Item], pool_ids: set[str]) -> list[str]:
    errors: list[str] = []
    item_ids = [e["item_id"] for e in session["items"]]
    if len(item_ids) != len(set(item_ids)):
        errors.append("duplicate_item")
    for item_id in item_ids:
        if item_id not in pool_ids:
            errors.append(f"candidate_mismatch:{item_id}")
        else:
            item = items_by_id[item_id]
            if not _evaluate_rule(item, profile.candidate_rule):
                errors.append(f"profile_mismatch:{item_id}")
    return errors


def _session_stats(session: dict[str, Any], profile: TrainingProfile,
                   items_by_id: dict[str, Item], pool_ids: set[str],
                   config: Any) -> dict[str, Any]:
    entries = session["items"]
    runs = _max_runs(entries, profile, items_by_id)
    errors = _session_qa(session, profile, items_by_id, pool_ids)
    dims: dict[str, dict[str, int]] = {}
    groups: dict[str, dict[str, int]] = {}
    positions: Counter[str] = Counter()
    lengths: Counter[str] = Counter()
    tones: Counter[str] = Counter()
    for entry in entries:
        for dim_id, vals in entry["target_features"]["dimensions"].items():
            dims.setdefault(dim_id, Counter())
            for v in vals:
                dims[dim_id][v] += 1
        for dim_id, gvals in _group_membership(profile, items_by_id[entry["item_id"]]).items():
            groups.setdefault(dim_id, Counter())
            for g in gvals:
                groups[dim_id][g] += 1
        pos = entry["target_features"]["target_positions"]
        if pos:
            positions[_position_category_from_set(pos)] += 1
        lengths[entry["syllable_count"]] += 1
        tones[entry["tone_pattern"]] += 1

    return {
        "session_id": session["session_id"],
        "profile_id": profile.id,
        "seed": session["seed"],
        "duration_minutes": session["requested_duration_sec"] // 60,
        "requested_duration_sec": session["requested_duration_sec"],
        "estimated_duration_sec": session["estimated_duration_sec"],
        "duration_abs_error_sec": session["duration_abs_error_sec"],
        "duration_rel_error": session["duration_rel_error"],
        "item_count": len(entries),
        "candidate_count": session["candidate_count"],
        "target_subfeatures": {k: dict(v) for k, v in dims.items()},
        "target_groups": {k: dict(v) for k, v in groups.items()},
        "positions": dict(positions),
        "purity": session["coverage_summary"].get("purity", {}),
        "word_lengths": {str(k): v for k, v in sorted(lengths.items())},
        "tone_patterns": dict(tones),
        "max_runs": runs,
        "relaxed_constraints": session["relaxed_constraints"],
        "qa_errors": errors,
    }


def _group_membership(profile: TrainingProfile,
                      item: Item) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for dim in profile.balance_dimensions:
        vals = matched_values(item, dim)
        result[dim.id] = [
            gid for gid, gvals in dim.groups.items()
            if any(v in gvals for v in vals)
        ]
    return result


def _position_category_from_set(positions: list[int]) -> str:
    pos_set = set(positions)
    return position_category(pos_set) or "none"


def _overlap_stats(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            a = [e["item_id"] for e in sessions[i]["items"]]
            b = [e["item_id"] for e in sessions[j]["items"]]
            set_a, set_b = set(a), set(b)
            item_overlap = len(set_a & set_b) / max(1, len(set_a | set_b))
            seq_overlap = sum(
                1 for x, y in zip(a, b) if x == y
            ) / max(1, min(len(a), len(b)))
            pairs.append(
                {
                    "pair": (sessions[i]["session_id"], sessions[j]["session_id"]),
                    "item_overlap_ratio": round(item_overlap, 6),
                    "sequence_overlap_ratio": round(seq_overlap, 6),
                }
            )
    if not pairs:
        return {"pairs": [], "mean_item_overlap": None, "mean_sequence_overlap": None}
    return {
        "pairs": pairs,
        "mean_item_overlap": round(
            sum(p["item_overlap_ratio"] for p in pairs) / len(pairs), 6
        ),
        "mean_sequence_overlap": round(
            sum(p["sequence_overlap_ratio"] for p in pairs) / len(pairs), 6
        ),
    }


def _benchmark_matrix(config: Any) -> dict[str, Any]:
    matrix = getattr(config, "benchmark_matrix", {})
    return {
        "main_profiles": matrix.get(
            "main_profiles",
            [
                "initial_flat_retroflex",
                "initial_n_l",
                "final_front_nasal",
                "final_back_nasal",
                "final_front_back_nasal",
                "general",
            ],
        ),
        "extra_profiles": matrix.get(
            "extra_profiles",
            [
                "final_compound",
                "tone_all",
                "tone_1",
                "tone_2",
                "tone_third_tone",
                "tone_4",
            ],
        ),
        "duration_minutes": matrix.get("duration_minutes", [5, 10, 20]),
        "practice_repetitions": matrix.get("practice_repetitions", 1),
    }


def run_candidate_stats(data_root: Path, out_dir: Path,
                        profiles: list[TrainingProfile],
                        config: Any) -> dict[str, Any]:
    """Compute real candidate-pool statistics and write the v1 report."""
    phonology_db = data_root / "derived/phonology-v1/phonology.sqlite3"
    corpus_db = data_root / "corpus.sqlite3"
    items = load_items(phonology_db, corpus_db)
    stats_all = compute_all_pool_stats(items, profiles, config)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = out_dir / CANDIDATE_STATS_FILENAME
    report_path = out_dir / CANDIDATE_REPORT_FILENAME
    payload = {
        "generator_version": GENERATOR_VERSION,
        "profiles_version": PROFILES_FILENAME,
        "config_version": config.version,
        "data_version": SOURCE_DATA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **stats_all,
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    report_path.write_text(
        build_candidate_pool_report(payload, profiles, config),
        encoding="utf-8",
    )
    return {
        "command": "candidate-stats",
        "status": "succeeded",
        "available_item_count": len(items),
        "profile_count": len(profiles),
        "report": str(report_path),
        "stats": str(stats_path),
    }


def run_benchmark(data_root: Path, out_dir: Path,
                  profiles: list[TrainingProfile], config: Any,
                  main_profile_ids: list[str] | None = None,
                  extra_profile_ids: list[str] | None = None
                  ) -> dict[str, Any]:
    """Run the real-data trial matrix, write sessions and the v1 report."""
    phonology_db = data_root / "derived/phonology-v1/phonology.sqlite3"
    corpus_db = data_root / "corpus.sqlite3"
    items = load_items(phonology_db, corpus_db)
    items_by_id = {i.item_id: i for i in items}
    by_id = {p.id: p for p in profiles}

    matrix = _benchmark_matrix(config)
    main_ids = main_profile_ids or matrix["main_profiles"]
    extra_ids = extra_profile_ids or matrix["extra_profiles"]
    missing = [pid for pid in main_ids + extra_ids if pid not in by_id]
    if missing:
        raise ValueError(f"unknown benchmark profiles: {missing}")

    seeds_by_duration = {
        5: config.benchmark_seeds_5m,
        10: config.benchmark_seeds_10m,
        20: config.benchmark_seeds_20m,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sessions").mkdir(parents=True, exist_ok=True)

    run_specs: list[tuple[TrainingProfile, int, int, bool, int]] = []
    for pid in main_ids:
        profile = by_id[pid]
        for duration in matrix["duration_minutes"]:
            for seed in seeds_by_duration.get(duration, ()):
                run_specs.append(
                    (profile, duration, matrix["practice_repetitions"], True, seed)
                )
    for pid in extra_ids:
        profile = by_id[pid]
        for seed in config.benchmark_seeds_10m:
            run_specs.append(
                (profile, 10, matrix["practice_repetitions"], True, seed)
            )

    session_stats: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    sessions_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    all_sessions: list[dict[str, Any]] = []

    for profile, duration, reps, auto_advance, seed in run_specs:
        key = (profile.id, duration)
        try:
            session = generate_session(
                profile,
                config,
                items,
                duration_minutes=duration,
                practice_repetitions=reps,
                auto_advance=auto_advance,
                seed=seed,
            )
            path = write_session_file(session, out_dir)
            pool_ids = {
                i.item_id for i in filter_candidates(items, profile)
            }
            stats = _session_stats(session, profile, items_by_id, pool_ids, config)
            stats["session_path"] = str(path)
            print(
                f"benchmark: {profile.id} {duration}m seed{seed} "
                f"-> {stats['item_count']} items",
                file=sys.stderr,
                flush=True,
            )

            # Reproducibility: same inputs + same seed must regenerate the same
            # item sequence.
            regenerated = generate_session(
                profile,
                config,
                items,
                duration_minutes=duration,
                practice_repetitions=reps,
                auto_advance=auto_advance,
                seed=seed,
            )
            same_items = (
                [e["item_id"] for e in session["items"]]
                == [e["item_id"] for e in regenerated["items"]]
            )
            if not same_items:
                stats["qa_errors"].append("reproducibility_mismatch")

            sessions_by_key.setdefault(key, []).append(session)
            all_sessions.append(session)
            session_stats.append(stats)
        except Exception as exc:  # noqa: BLE001 - record and continue
            failures.append(
                {
                    "profile_id": profile.id,
                    "duration_minutes": duration,
                    "seed": seed,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    overlap_summary: dict[str, Any] = {}
    for key, sessions in sorted(sessions_by_key.items()):
        overlap_summary[f"{key[0]}-{key[1]}m"] = _overlap_stats(sessions)

    qa_errors = [e for s in session_stats for e in s["qa_errors"]]
    duration_errors = [
        abs(s["duration_rel_error"]) for s in session_stats
    ]
    relaxation_counts: Counter[str] = Counter()
    for s in session_stats:
        for record in s["relaxed_constraints"]:
            relaxation_counts[record["rule"]] += 1

    summary = {
        "generator_version": GENERATOR_VERSION,
        "profiles_version": PROFILES_FILENAME,
        "config_version": config.version,
        "data_version": SOURCE_DATA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_total": len(session_stats),
        "profiles_run": sorted({s["profile_id"] for s in session_stats}),
        "session_stats": session_stats,
        "overlap_summary": overlap_summary,
        "qa_summary": {
            "sessions": len(session_stats),
            "profile_errors": sum(
                1 for e in qa_errors if e.startswith("profile_mismatch")
            ),
            "candidate_mismatch_errors": sum(
                1 for e in qa_errors if e.startswith("candidate_mismatch")
            ),
            "duplicate_errors": sum(1 for e in qa_errors if e == "duplicate_item"),
            "reproducibility_errors": sum(
                1 for e in qa_errors if e == "reproducibility_mismatch"
            ),
            "generation_failures": len(failures),
            "max_duration_abs_error_sec": round(
                max((abs(s["duration_abs_error_sec"]) for s in session_stats), default=0.0),
                3,
            ),
            "max_duration_rel_error": round(
                max(duration_errors, default=0.0), 6
            ),
            "relaxation_counts": dict(relaxation_counts),
        },
        "failures": failures,
        "config": config.to_dict(),
    }
    stats_path = out_dir / GENERATOR_STATS_FILENAME
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    report_path = out_dir / GENERATOR_REPORT_FILENAME
    report_path.write_text(
        build_generator_report(summary, profiles, config, all_sessions),
        encoding="utf-8",
    )
    return {
        "command": "benchmark",
        "status": "succeeded" if not failures else "partial",
        "sessions_total": len(session_stats),
        "generation_failures": len(failures),
        "report": str(report_path),
        "stats": str(stats_path),
    }
