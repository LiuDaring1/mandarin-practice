"""Candidate loading, filtering and pool statistics for training profiles."""

from __future__ import annotations

from collections import Counter
import sqlite3
from pathlib import Path
from typing import Any

from .models import BalanceDimension, Item, PositionDimension, SyllableInfo, TrainingProfile


# Item fields that are stored as frozensets and used by rules / matching.
SET_FIELDS = frozenset(
    {
        "initials",
        "finals",
        "front_nasal_finals",
        "back_nasal_finals",
        "compound_finals",
        "final_structures",
        "nasal_types",
        "compound_resonances",
        "tone_values",
    }
)


def _make_item(row: dict[str, Any], syllables: list[SyllableInfo],
               segment: dict[str, Any]) -> Item:
    initials = frozenset(s.initial for s in syllables)
    finals = frozenset(s.final_canonical for s in syllables)
    front_nasal = frozenset(
        s.final_canonical for s in syllables if s.nasal_type == "FRONT_N"
    )
    back_nasal = frozenset(
        s.final_canonical for s in syllables if s.nasal_type == "BACK_NG"
    )
    compound = frozenset(
        s.final_canonical for s in syllables if s.final_structure == "COMPOUND"
    )
    return Item(
        item_id=row["item_id"],
        word_raw=row["word_raw"],
        pinyin_nfc=row["pinyin_nfc"],
        table_kind=row["table_kind"],
        global_seq=int(row["global_seq"]),
        syllable_count=int(row["syllable_count"]),
        length_bucket=row["length_bucket"] or str(row["syllable_count"]),
        initial_sequence=row["initial_sequence"],
        final_sequence=row["final_sequence"],
        tone_pattern_lexical=row["tone_pattern_lexical"],
        has_neutral_tone=bool(row["has_neutral_tone"]),
        has_erhua=bool(row["has_erhua"]),
        has_adjacent_33=bool(row["has_adjacent_33"]),
        has_flat_initial=bool(row["has_flat_initial"]),
        has_retroflex_initial=bool(row["has_retroflex_initial"]),
        has_n=bool(row["has_n"]),
        has_l=bool(row["has_l"]),
        has_jqx=bool(row["has_jqx"]),
        has_front_nasal=bool(row["has_front_nasal"]),
        has_back_nasal=bool(row["has_back_nasal"]),
        has_compound_final=bool(row["has_compound_final"]),
        has_third_tone=bool(row["has_third_tone"]),
        contains_yi=bool(row["contains_yi"]),
        contains_bu=bool(row["contains_bu"]),
        neutral_positions=row["neutral_positions"],
        erhua_position=row["erhua_position"],
        clip_path=segment["clip_path"],
        clip_duration_ms=int(segment["end_ms"]) - int(segment["start_ms"]),
        syllables=syllables,
        initials=initials,
        finals=finals,
        front_nasal_finals=front_nasal,
        back_nasal_finals=back_nasal,
        compound_finals=compound,
        final_structures=frozenset(s.final_structure for s in syllables),
        nasal_types=frozenset(s.nasal_type for s in syllables),
        compound_resonances=frozenset(
            s.compound_resonance for s in syllables
            if s.compound_resonance != "NA"
        ),
        tone_values=frozenset(str(s.tone) for s in syllables),
    )


def load_items(phonology_db: Path, corpus_db: Path) -> list[Item]:
    """Load the 16,149 available items with phonology features and clip durations.

    Both databases are opened read-only.  The result is sorted by
    ``(table_kind, global_seq)`` so generation is deterministic for a seed.
    """
    with sqlite3.connect(f"file:{phonology_db}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT item_id, table_kind, word_raw, pinyin_nfc, global_seq, "
            "syllable_count, length_bucket, initial_sequence, final_sequence, "
            "tone_pattern_lexical, has_neutral_tone, has_erhua, has_adjacent_33, "
            "has_flat_initial, has_retroflex_initial, has_n, has_l, has_jqx, "
            "has_front_nasal, has_back_nasal, has_compound_final, has_third_tone, "
            "contains_yi, contains_bu, "
            "neutral_positions, erhua_position "
            "FROM item_features_available ORDER BY table_kind, global_seq"
        ).fetchall()
        syll_rows = con.execute(
            "SELECT item_id, syllable_index, initial, final_canonical, "
            "final_structure, nasal_type, compound_resonance, tone_lexical "
            "FROM syllable_features_available ORDER BY item_id, syllable_index"
        ).fetchall()
    with sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        seg_rows = con.execute(
            "SELECT item_id, clip_path, start_ms, end_ms FROM segments"
        ).fetchall()

    segments = {r["item_id"]: dict(r) for r in seg_rows}
    syllables_by_item: dict[str, list[SyllableInfo]] = {}
    for r in syll_rows:
        syllables_by_item.setdefault(r["item_id"], []).append(
            SyllableInfo(
                index=int(r["syllable_index"]),
                initial=r["initial"],
                final_canonical=r["final_canonical"],
                final_structure=r["final_structure"],
                nasal_type=r["nasal_type"],
                compound_resonance=r["compound_resonance"],
                tone=int(r["tone_lexical"]),
            )
        )

    items: list[Item] = []
    for row in rows:
        item_id = row["item_id"]
        segment = segments.get(item_id)
        if segment is None:
            raise ValueError(
                f"available item {item_id} has no segment in the master corpus DB"
            )
        items.append(
            _make_item(dict(row), syllables_by_item.get(item_id, []), segment)
        )
    return items


def _evaluate_rule(item: Item, rule: dict[str, Any]) -> bool:
    if "all" in rule:
        return all(_evaluate_rule(item, r) for r in rule["all"])
    if "any" in rule:
        return any(_evaluate_rule(item, r) for r in rule["any"])
    if "not" in rule:
        return not _evaluate_rule(item, rule["not"])

    field = rule.get("field")
    if field is None:
        raise ValueError(f"rule without field: {rule}")
    if field in SET_FIELDS:
        values = getattr(item, field)
        if "contains_any" in rule:
            return bool(values & set(rule["contains_any"]))
        if "contains_all" in rule:
            return set(rule["contains_all"]) <= values
        if rule.get("nonempty"):
            return bool(values)
        raise ValueError(f"unsupported set rule for {field}: {rule}")

    value = getattr(item, field)
    if "eq" in rule:
        return value == rule["eq"]
    if "ne" in rule:
        return value != rule["ne"]
    if "gt" in rule:
        return value > rule["gt"]
    if rule.get("is_not_null"):
        return value is not None
    raise ValueError(f"unsupported scalar rule for {field}: {rule}")


def filter_candidates(items: list[Item], profile: TrainingProfile) -> list[Item]:
    return [i for i in items if _evaluate_rule(i, profile.candidate_rule)]


def finals_matching(item: Item, final_filter: dict[str, str]) -> frozenset[str]:
    if not final_filter:
        return item.finals
    key, expected = next(iter(final_filter.items()))
    return frozenset(
        s.final_canonical for s in item.syllables if getattr(s, key) == expected
    )


def matched_values(item: Item, dim: BalanceDimension) -> list[str]:
    """Return the dimension values this item contains."""
    if dim.kind == "initials":
        return [v for v in dim.values if v in item.initials]
    if dim.kind == "finals":
        matched = finals_matching(item, dim.final_filter)
        return [v for v in dim.values if v in matched]
    if dim.kind == "tones":
        return [v for v in dim.values if v in item.tone_values]
    if dim.kind == "resonances":
        return [v for v in dim.values if v in item.compound_resonances]
    if dim.kind == "structures":
        return [v for v in dim.values if v in item.final_structures]
    if dim.kind == "nasal_types":
        return [v for v in dim.values if v in item.nasal_types]
    if dim.kind == "lengths":
        return [v for v in dim.values if v == item.length_bucket]
    if dim.kind == "flags":
        return [
            v for v in dim.values
            if dim.flags.get(v) and getattr(item, dim.flags[v], False)
        ]
    raise ValueError(f"unknown dimension kind: {dim.kind}")


def matched_positions(item: Item, pos: PositionDimension) -> set[int]:
    """Return 1-based syllable positions matching the position dimension."""
    if pos.positions_column:
        raw = getattr(item, pos.positions_column)
        if not raw:
            return set()
        return {int(p) for p in str(raw).split(",") if p}
    positions: set[int] = set()
    for syll in item.syllables:
        match = False
        if pos.kind == "initials":
            match = syll.initial in pos.values
        elif pos.kind == "finals":
            match = syll.final_canonical in pos.values
            if match and pos.final_filter:
                key, expected = next(iter(pos.final_filter.items()))
                match = getattr(syll, key) == expected
        elif pos.kind == "tones":
            match = str(syll.tone) in pos.values
        elif pos.kind == "flags":
            # Flag positions always come from an item-level positions column.
            raise ValueError(f"flags position dimension requires positions_column: {pos.id}")
        else:
            raise ValueError(f"unsupported position kind: {pos.kind}")
        if match:
            positions.add(syll.index)
    return positions


def position_category(positions: set[int]) -> str | None:
    if not positions:
        return None
    if positions == {1}:
        return "1"
    if positions == {2}:
        return "2"
    if all(p >= 3 for p in positions):
        return "3+"
    return "multiple"


def occurrence_bucket(count: int) -> str:
    return str(min(count, 4)) if count >= 1 else "0"


def purity_bucket(occurrence_count: int, syllable_count: int) -> str:
    if occurrence_count <= 0:
        return "none"
    if occurrence_count >= syllable_count:
        return "full"
    return "partial"


def build_profile_index(items: list[Item],
                        profile: TrainingProfile) -> dict[str, dict[str, Any]]:
    """Precompute matched values / groups / positions for every candidate.

    Generation repeatedly scores thousands of candidates per step; this cache
    avoids recomputing syllable-level matching on every step.
    """
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        dims: dict[str, frozenset[str]] = {}
        groups: dict[str, frozenset[str]] = {}
        for dim in profile.balance_dimensions:
            vals = frozenset(matched_values(item, dim))
            dims[dim.id] = vals
            groups[dim.id] = frozenset(
                gid for gid, gvals in dim.groups.items()
                if any(v in gvals for v in vals)
            )
        positions = (
            matched_positions(item, profile.position_dimension)
            if profile.position_dimension
            else set()
        )
        index[item.item_id] = {
            "dims": dims,
            "groups": groups,
            "position": position_category(positions),
            "position_count": len(positions),
            "occurrence": occurrence_bucket(len(positions)),
            "purity": purity_bucket(len(positions), item.syllable_count),
            "length": item.length_bucket,
            "tone_pattern": item.tone_pattern_lexical,
        }
    return index


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def _duration_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "mean": 0.0, "max": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "min": round(min(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
        "p10": round(_percentile(values, 10), 3),
        "p90": round(_percentile(values, 90), 3),
    }


def compute_pool_stats(items: list[Item], profile: TrainingProfile,
                       config: Any) -> dict[str, Any]:
    """Compute candidate-pool statistics for one profile.

    ``config`` only supplies timing parameters for estimated durations.
    """
    candidates = filter_candidates(items, profile)
    n = len(candidates)
    stats: dict[str, Any] = {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "candidate_count": n,
        "candidate_share_of_available": round(n / max(1, len(items)), 6),
    }

    dims: dict[str, Any] = {}
    for dim in profile.balance_dimensions:
        counts: Counter[str] = Counter()
        group_counts: Counter[str] = Counter()
        for item in candidates:
            vals = matched_values(item, dim)
            for v in vals:
                counts[v] += 1
            for gid, gvals in dim.groups.items():
                if any(v in gvals for v in vals):
                    group_counts[gid] += 1
        shares = {
            k: round(v / max(1, n), 6)
            for k, v in sorted(counts.items())
        }
        # When the profile defines group target ratios, value-level targets are
        # derived as ``group_target * within-group pool share`` so the value
        # balancing and group balancing pull in the same direction.
        group_of: dict[str, str] = {}
        for gid, gvals in dim.groups.items():
            for v in gvals:
                group_of.setdefault(v, gid)
        target_shares: dict[str, float] = {}
        if dim.target_group_shares and group_of:
            for v in dim.values:
                gid = group_of.get(v)
                if gid is not None and gid in dim.target_group_shares:
                    gcount = group_counts.get(gid, 0)
                    target_shares[v] = (
                        dim.target_group_shares[gid] * (counts.get(v, 0) / gcount)
                        if gcount
                        else 0.0
                    )
                else:
                    target_shares[v] = shares.get(v, 0.0)
        else:
            target_shares = dict(shares)
        dims[dim.id] = {
            "label": dim.label,
            "kind": dim.kind,
            "counts": dict(sorted(counts.items())),
            "shares": shares,
            "target_shares": {
                k: round(v, 6) for k, v in sorted(target_shares.items())
            },
            "group_counts": dict(sorted(group_counts.items())),
            "group_shares": {
                k: round(v / max(1, n), 6)
                for k, v in sorted(group_counts.items())
            },
            "group_target_shares": dict(dim.target_group_shares),
        }
    stats["dimensions"] = dims

    pos_counts: Counter[str] = Counter()
    occ_counts: Counter[str] = Counter()
    purity_counts: Counter[str] = Counter()
    if profile.position_dimension:
        for item in candidates:
            positions = matched_positions(item, profile.position_dimension)
            cat = position_category(positions)
            if cat:
                pos_counts[cat] += 1
            occ_counts[occurrence_bucket(len(positions))] += 1
            purity_counts[purity_bucket(len(positions), item.syllable_count)] += 1
    stats["position"] = {
        "counts": dict(sorted(pos_counts.items())),
        "shares": {k: round(v / max(1, n), 6) for k, v in sorted(pos_counts.items())},
        "occurrence_counts": dict(sorted(occ_counts.items())),
        "occurrence_shares": {
            k: round(v / max(1, n), 6)
            for k, v in sorted(occ_counts.items())
        },
    }
    stats["purity"] = {
        "counts": dict(sorted(purity_counts.items())),
        "shares": {
            k: round(v / max(1, n), 6)
            for k, v in sorted(purity_counts.items())
        },
        "target_shares": dict(profile.purity_target_shares),
    }

    length_counts: Counter[str] = Counter()
    tone_counts: Counter[str] = Counter()
    clip_durs: list[float] = []
    for item in candidates:
        length_counts[item.length_bucket] += 1
        tone_counts[item.tone_pattern_lexical] += 1
        clip_durs.append(item.clip_duration_sec)
    stats["word_lengths"] = {
        "counts": dict(sorted(length_counts.items(), key=lambda kv: (int(kv[0][0]) if kv[0][0].isdigit() else 99, kv[0]))),
        "shares": {
            k: round(v / max(1, n), 6)
            for k, v in sorted(
                length_counts.items(),
                key=lambda kv: (int(kv[0][0]) if kv[0][0].isdigit() else 99, kv[0]),
            )
        },
    }
    stats["tone_patterns"] = {
        "counts": dict(sorted(tone_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "shares": {
            k: round(v / max(1, n), 6)
            for k, v in sorted(tone_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        },
    }
    stats["tone_pattern_top15"] = [
        [k, v] for k, v in list(stats["tone_patterns"]["counts"].items())[:15]
    ]
    stats["clip_duration_sec"] = _duration_stats(clip_durs)

    est1 = [
        max(c.clip_duration_sec + config.extra_follow_sec, config.min_follow_sec)
        + c.clip_duration_sec
        + config.transition_sec
        for c in candidates
    ]
    est2 = [
        2 * (
            max(c.clip_duration_sec + config.extra_follow_sec, config.min_follow_sec)
            + c.clip_duration_sec
        )
        + config.transition_sec
        for c in candidates
    ]
    stats["est_item_duration_sec"] = {
        "repetitions_1": _duration_stats(est1),
        "repetitions_2": _duration_stats(est2),
    }
    return stats


def compute_all_pool_stats(items: list[Item], profiles: list[TrainingProfile],
                           config: Any) -> dict[str, Any]:
    return {
        "profiles": [compute_pool_stats(items, p, config) for p in profiles],
        "available_item_count": len(items),
    }
