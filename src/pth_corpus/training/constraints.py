"""Sequence constraints and automatic relaxation."""

from __future__ import annotations

from .candidates import matched_positions, matched_values, position_category
from .models import Item, TrainingProfile
from .scoring import CoverageState

# Relaxation order: lowest priority is relaxed first.
RELAX_ORDER = ("tone_pattern", "length", "position", "target")


def constraint_violations(item: Item, state: CoverageState,
                          profile: TrainingProfile, config: Any,
                          relax_level: int,
                          index: dict[str, dict[str, Any]] | None = None
                          ) -> list[str]:
    """Return violated sequence constraints at the given relaxation level."""
    violations: list[str] = []
    cached = (index or {}).get(item.item_id)

    if relax_level < 4:
        for dim in profile.balance_dimensions:
            # The "same concrete target sound" run constraint only applies to
            # specific initials / finals.  Coverage dimensions such as tone,
            # structure or flags are balanced but are not run-constrained.
            if dim.kind not in {"initials", "finals"}:
                continue
            vals = (
                cached["dims"][dim.id]
                if cached is not None
                else frozenset(matched_values(item, dim))
            )
            for v in vals:
                if (
                    state.current_dim_run(dim.id, v) + 1
                    > config.max_same_target_consecutive
                ):
                    violations.append(f"same_target:{dim.id}:{v}")
                    break
            if violations:
                break

    if relax_level < 3 and profile.position_dimension:
        cat = (
            cached["position"]
            if cached is not None
            else position_category(
                matched_positions(item, profile.position_dimension)
            )
        )
        if cat and (
            state.current_position_run(cat) + 1
            > config.max_same_position_consecutive
        ):
            violations.append(f"same_position:{cat}")

    if relax_level < 2:
        bucket = cached["length"] if cached is not None else item.length_bucket
        if (
            state.current_length_run(bucket) + 1
            > config.max_same_length_consecutive
        ):
            violations.append(f"same_length:{bucket}")

    if relax_level < 1 and profile.track_tone_pattern:
        pattern = (
            cached["tone_pattern"]
            if cached is not None
            else item.tone_pattern_lexical
        )
        if (
            state.current_tone_run(pattern) + 1
            > config.max_same_tone_pattern_consecutive
        ):
            violations.append(f"same_tone_pattern:{pattern}")

    return violations
