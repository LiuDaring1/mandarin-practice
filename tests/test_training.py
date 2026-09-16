"""Unit tests for the balanced-random training generator."""

from pathlib import Path
import random

import pytest

from pth_corpus.training.candidates import (
    _make_item,
    build_profile_index,
    compute_pool_stats,
    filter_candidates,
    matched_positions,
    position_category,
    purity_bucket,
)
from pth_corpus.training.constraints import constraint_violations
from pth_corpus.training.generator import generate_session
from pth_corpus.training.models import (
    GeneratorConfig,
    Item,
    SyllableInfo,
    TrainingProfile,
)
from pth_corpus.training.scoring import CoverageState, score_candidates
from pth_corpus.training.timing import item_duration_sec


def make_config(**overrides) -> GeneratorConfig:
    defaults = {
        "version": "test",
        "top_k": 5,
        "max_attempts": 6,
        "random_jitter": 0.05,
        "max_same_target_consecutive": 2,
        "max_same_position_consecutive": 3,
        "max_same_length_consecutive": 4,
        "max_same_tone_pattern_consecutive": 3,
        "extra_follow_sec": 0.8,
        "min_follow_sec": 1.8,
        "transition_sec": 0.3,
        "duration_tolerance_ratio": 0.05,
        "weight_coverage": 1.0,
        "weight_group": 1.0,
        "weight_position": 0.8,
        "weight_length": 0.5,
        "weight_tone_pattern": 0.4,
        "weight_purity": 0.15,
        "weight_overshoot_penalty": 0.5,
        "allowed_duration_minutes": (5, 10),
        "allowed_practice_repetitions": (1, 2),
        "benchmark_seeds_5m": (1, 2),
        "benchmark_seeds_10m": (3, 4),
        "benchmark_seeds_20m": (5, 6),
    }
    defaults.update(overrides)
    return GeneratorConfig(**defaults)


def make_profile() -> TrainingProfile:
    return TrainingProfile.from_dict(
        {
            "id": "test_n_l",
            "name": "Test n/l",
            "aliases": [],
            "candidate_rule": {
                "field": "initials",
                "contains_any": ["n", "l"],
            },
            "balance_dimensions": [
                {
                    "id": "target_initial",
                    "label": "目标声母",
                    "kind": "initials",
                    "values": ["n", "l"],
                    "groups": {"n": ["n"], "l": ["l"]},
                    "target_group_shares": {"n": 0.5, "l": 0.5},
                    "primary": True,
                }
            ],
            "position_dimension": {
                "id": "target_position",
                "label": "目标音位置",
                "kind": "initials",
                "values": ["n", "l"],
            },
            "purity": True,
            "track_tone_pattern": True,
            "track_word_length": True,
        }
    )


def _syll(initial: str, index: int, tone: int = 1, final: str = "a") -> SyllableInfo:
    return SyllableInfo(
        index=index,
        initial=initial,
        final_canonical=final,
        final_structure="SIMPLE" if final not in {"an", "ang"} else "NASAL",
        nasal_type="FRONT_N" if final == "an" else "BACK_NG" if final == "ang" else "NONE",
        compound_resonance="NA",
        tone=tone,
    )


def make_item(item_id: str, word: str, initials: list[str],
              tones: list[int] | None = None,
              finals: list[str] | None = None,
              clip_ms: int = 1000) -> Item:
    tones = tones or [1] * len(initials)
    finals = finals or ["a"] * len(initials)
    row = {
        "item_id": item_id,
        "table_kind": "table1",
        "word_raw": word,
        "pinyin_nfc": "".join(initials),
        "global_seq": int(item_id.rsplit("-", 1)[1]),
        "syllable_count": len(initials),
        "length_bucket": str(len(initials)),
        "initial_sequence": "-".join(initials),
        "final_sequence": "-".join(finals),
        "tone_pattern_lexical": "-".join(str(t) for t in tones),
        "has_neutral_tone": 0,
        "has_erhua": 0,
        "has_adjacent_33": 0,
        "has_flat_initial": int(any(i in {"z", "c", "s"} for i in initials)),
        "has_retroflex_initial": int(any(i in {"zh", "ch", "sh"} for i in initials)),
        "has_n": int("n" in initials),
        "has_l": int("l" in initials),
        "has_jqx": 0,
        "has_front_nasal": int(any(f == "an" for f in finals)),
        "has_back_nasal": int(any(f == "ang" for f in finals)),
        "has_compound_final": 0,
        "has_third_tone": int(3 in tones),
        "contains_yi": 0,
        "contains_bu": 0,
        "neutral_positions": None,
        "erhua_position": None,
    }
    syllables = [
        _syll(i, idx + 1, tone, final)
        for idx, (i, tone, final) in enumerate(zip(initials, tones, finals))
    ]
    segment = {
        "clip_path": f"derived/clips-v2/table1/{item_id}.wav",
        "start_ms": 0,
        "end_ms": clip_ms,
    }
    return _make_item(row, syllables, segment)


@pytest.fixture
def items() -> list[Item]:
    return [
        make_item("t1-0001", "男女", ["n", "n"], [2, 3], ["an", "an"]),
        make_item("t1-0002", "力量", ["l", "l"], [4, 2], ["a", "ang"]),
        make_item("t1-0003", "努力", ["n", "l"], [3, 4], ["u", "i"]),
        make_item("t1-0004", "列宁", ["l", "n"], [4, 2], ["ie", "in"]),
        make_item("t1-0005", "哪里", ["n", "l"], [3, 3], ["a", "i"]),
        make_item("t1-0006", "年龄", ["n", "l"], [2, 2], ["ian", "ing"]),
        make_item("t1-0007", "老师", ["l", "sh"], [3, 1], ["ao", "i"]),
        make_item("t1-0008", "奶奶", ["n", "n"], [3, 1], ["ai", "ai"]),
        make_item("t1-0009", "爸爸", ["b", "b"], [4, 4], ["a", "a"]),
        make_item("t1-0010", "牛", ["n"], [2], ["ou"]),
        make_item("t1-0011", "绿", ["l"], [4], ["ü"]),
    ]


def test_filter_candidates_n_l(items):
    profile = make_profile()
    candidates = filter_candidates(items, profile)
    ids = {i.item_id for i in candidates}
    assert ids == {
        "t1-0001",
        "t1-0002",
        "t1-0003",
        "t1-0004",
        "t1-0005",
        "t1-0006",
        "t1-0007",
        "t1-0008",
        "t1-0010",
        "t1-0011",
    }
    # "爸爸" has no n/l
    assert "t1-0009" not in ids


def test_position_category():
    assert position_category({1}) == "1"
    assert position_category({2}) == "2"
    assert position_category({3, 4}) == "3+"
    assert position_category({1, 3}) == "multiple"
    assert position_category(set()) is None


def test_purity_bucket():
    assert purity_bucket(0, 2) == "none"
    assert purity_bucket(1, 2) == "partial"
    assert purity_bucket(2, 2) == "full"
    assert purity_bucket(1, 1) == "full"


def test_matched_positions(items):
    profile = make_profile()
    item = items[0]  # 男女 n-n
    positions = matched_positions(item, profile.position_dimension)
    assert positions == {1, 2}


def test_constraint_same_target(items):
    profile = make_profile()
    config = make_config()
    state = CoverageState(profile)
    state.add(items[0])  # n,n
    state.add(items[7])  # n,n
    assert constraint_violations(items[1], state, profile, config, 0) == []
    n_item = items[0]
    violations = constraint_violations(n_item, state, profile, config, 0)
    assert any(v.startswith("same_target") for v in violations)
    assert constraint_violations(n_item, state, profile, config, 4) == []


def test_timing_formula():
    config = make_config()
    item = make_item("t1-0010", "三", ["s"], [1], ["an"], clip_ms=1000)
    assert item_duration_sec(item, config, 1) == pytest.approx(3.1)
    assert item_duration_sec(item, config, 2) == pytest.approx(5.9)


def test_pool_stats(items):
    profile = make_profile()
    config = make_config()
    stats = compute_pool_stats(items, profile, config)
    assert stats["candidate_count"] == 10
    assert stats["dimensions"]["target_initial"]["group_counts"] == {
        "n": 7,
        "l": 7,
    }
    assert stats["dimensions"]["target_initial"]["target_shares"] == {
        "n": 0.5,
        "l": 0.5,
    }
    assert stats["position"]["counts"] == {"1": 3, "multiple": 7}
    assert stats["purity"]["counts"] == {"full": 9, "partial": 1}


def test_purity_target_shares_balance_direction():
    profile = TrainingProfile.from_dict(
        {
            "id": "purity_test",
            "name": "Purity test",
            "aliases": [],
            "candidate_rule": {"field": "item_id", "is_not_null": True},
            "balance_dimensions": [],
            "position_dimension": {
                "id": "target_position",
                "label": "目标音位置",
                "kind": "initials",
                "values": ["n"],
            },
            "purity": True,
            "purity_weight": 1.2,
            "purity_target_shares": {"full": 0.7, "partial": 0.3},
        }
    )
    config = make_config(weight_overshoot_penalty=0.5)
    full = make_item("t1-0030", "男女", ["n", "n"], [1, 1], ["a", "a"])
    partial = make_item("t1-0031", "南北", ["n", "b"], [1, 1], ["a", "a"])
    items = [full, partial]
    index = build_profile_index(items, profile)
    pool = compute_pool_stats(items, profile, config)
    state = CoverageState(profile, index)
    rng = random.Random(1)

    # With nothing selected, full-target items are preferred (start focused).
    scored = score_candidates(items, state, pool, profile, config, rng, index)
    scores = {r[0].item_id: r[1] for r in scored}
    assert scores[full.item_id] > scores[partial.item_id]

    # Once partial-target items are over-represented, full-target items win.
    for _ in range(3):
        state.add(partial)
    scored = score_candidates(items, state, pool, profile, config, rng, index)
    scores = {r[0].item_id: r[1] for r in scored}
    assert scores[full.item_id] > scores[partial.item_id]

    # At 70% full / 30% partial, partial-target items are pulled back up.
    for _ in range(7):
        state.add(full)
    scored = score_candidates(items, state, pool, profile, config, rng, index)
    scores = {r[0].item_id: r[1] for r in scored}
    assert scores[partial.item_id] > scores[full.item_id]


def test_generate_session_reproducible_and_valid(items):
    profile = make_profile()
    config = make_config()
    session_a = generate_session(profile, config, items, duration_minutes=5, seed=42)
    session_b = generate_session(profile, config, items, duration_minutes=5, seed=42)
    session_c = generate_session(profile, config, items, duration_minutes=5, seed=43)
    ids_a = [e["item_id"] for e in session_a["items"]]
    ids_b = [e["item_id"] for e in session_b["items"]]
    ids_c = [e["item_id"] for e in session_c["items"]]
    assert ids_a == ids_b
    assert len(ids_a) == len(set(ids_a))
    assert session_a["item_count"] <= len(items)
    assert session_a["item_count"] > 0
    assert ids_a != ids_c
    profile_ids = {i.item_id for i in filter_candidates(items, profile)}
    assert all(iid in profile_ids for iid in ids_a)


def test_generate_session_duration_validation(items):
    profile = make_profile()
    config = make_config()
    with pytest.raises(ValueError):
        generate_session(profile, config, items, duration_minutes=7)
    with pytest.raises(ValueError):
        generate_session(profile, config, items, duration_minutes=5,
                         practice_repetitions=3)


def test_generate_session_small_pool_no_duplicates(items):
    profile = make_profile()
    config = make_config()
    session = generate_session(profile, config, items[:3], duration_minutes=5, seed=7)
    ids = [e["item_id"] for e in session["items"]]
    assert len(ids) == len(set(ids)) == 3
