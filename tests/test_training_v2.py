"""Unit tests for the v2 structure-first session generator."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import random

import pytest

from pth_corpus.training.candidates import _make_item
from pth_corpus.training.models import (
    GeneratorConfig,
    Item,
    SyllableInfo,
)
from pth_corpus.training.v2.engine import (
    candidate_matches,
    classify_item,
    compute_availability,
    matched_patterns,
    signature_of,
)
from pth_corpus.training.v2.generator import (
    V2State,
    _bucket_pool_stats,
    _score_candidates,
    _synthetic_profile,
    _universe_from_items,
    generate_session_v2,
)
from pth_corpus.training.v2.history import HistoryStore
from pth_corpus.training.v2.schema import V2Profile


def make_item(item_id: str, initials: list[str],
              finals: list[str] | None = None,
              tones: list[int] | None = None) -> Item:
    finals = finals or ["a"] * len(initials)
    tones = tones or [1] * len(initials)
    syllables = [
        SyllableInfo(
            index=i + 1,
            initial=initials[i],
            final_canonical=finals[i],
            final_structure="SIMPLE",
            nasal_type="NONE",
            compound_resonance="NA",
            tone=tones[i],
        )
        for i in range(len(initials))
    ]
    row = {
        "item_id": item_id,
        "table_kind": "table1",
        "word_raw": item_id,
        "pinyin_nfc": "-".join(initials),
        "global_seq": int(item_id.rsplit("-", 1)[1]),
        "syllable_count": len(initials),
        "length_bucket": str(len(initials)),
        "initial_sequence": "-".join(initials),
        "final_sequence": "-".join(finals),
        "tone_pattern_lexical": "-".join(str(t) for t in tones),
        "has_neutral_tone": 0,
        "has_erhua": 0,
        "has_adjacent_33": 0,
        "has_flat_initial": 0,
        "has_retroflex_initial": 0,
        "has_n": 0,
        "has_l": 0,
        "has_jqx": 0,
        "has_front_nasal": 0,
        "has_back_nasal": 0,
        "has_compound_final": 0,
        "has_third_tone": 0,
        "contains_yi": 0,
        "contains_bu": 0,
        "neutral_positions": None,
        "erhua_position": None,
    }
    segment = {
        "clip_path": f"derived/clips-v2/table1/{item_id}.wav",
        "start_ms": 0,
        "end_ms": 1000,
    }
    return _make_item(row, syllables, segment)


def bilabial_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "bilabial_focus",
            "name": "Bilabial",
            "dimension": "initial",
            "mode": "single_focus",
            "target_sets": {"T": ["b", "p", "m"]},
            "buckets": [
                {
                    "id": "core",
                    "label": "core",
                    "target_ratio": 0.8,
                    "role": "core",
                    "rule": {"op": "all_in", "sets": ["T"]},
                    "pair_specs": [{"left": "T", "right": "T"}],
                },
                {
                    "id": "supplement",
                    "label": "supp",
                    "target_ratio": 0.2,
                    "role": "supplement",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "any_in", "sets": ["T"]},
                            {"op": "not", "rule": {"op": "all_in", "sets": ["T"]}},
                        ],
                    },
                    "pair_specs": [
                        {"left": "T", "right": "O"},
                        {"left": "O", "right": "T"},
                    ],
                },
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 2, "min_gap": 20},
        }
    )


def contrast_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "contrast",
            "name": "Contrast",
            "dimension": "initial",
            "mode": "contrast",
            "target_sets": {"A": ["z", "c", "s"], "B": ["zh", "ch", "sh", "r"]},
            "allow_other": False,
            "buckets": [
                {
                    "id": "cross",
                    "label": "cross",
                    "target_ratio": 0.6,
                    "role": "cross",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "all_in", "sets": ["A", "B"]},
                            {"op": "groups_present", "sets": ["A", "B"], "min": 2},
                        ],
                    },
                    "pair_specs": [
                        {"left": "A", "right": "B"},
                        {"left": "B", "right": "A"},
                    ],
                },
                {
                    "id": "same",
                    "label": "same",
                    "target_ratio": 0.4,
                    "role": "same",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "all_in", "sets": ["A", "B"]},
                            {
                                "op": "not",
                                "rule": {
                                    "op": "groups_present",
                                    "sets": ["A", "B"],
                                    "min": 2,
                                },
                            },
                        ],
                    },
                    "pair_specs": [
                        {"left": "A", "right": "A"},
                        {"left": "B", "right": "B"},
                    ],
                },
            ],
            "scarcity": {"repeat_allowed": True, "max_repeat": 2, "min_gap": 20},
        }
    )


def make_config() -> GeneratorConfig:
    return GeneratorConfig(
        version="test",
        top_k=5,
        max_attempts=8,
        random_jitter=0.05,
        max_same_target_consecutive=2,
        max_same_position_consecutive=3,
        max_same_length_consecutive=4,
        max_same_tone_pattern_consecutive=3,
        extra_follow_sec=0.8,
        min_follow_sec=1.8,
        transition_sec=0.3,
        duration_tolerance_ratio=0.05,
        weight_coverage=1.0,
        weight_pattern=1.0,
        weight_group=1.0,
        weight_position=0.8,
        weight_length=0.5,
        weight_tone_pattern=0.4,
        weight_purity=0.15,
        weight_overshoot_penalty=0.5,
        allowed_duration_minutes=(5, 10),
        allowed_practice_repetitions=(1, 2),
        benchmark_seeds_5m=(1, 2),
        benchmark_seeds_10m=(3, 4),
        benchmark_seeds_20m=(5, 6),
    )


def test_signature_and_rules():
    profile = bilabial_profile()
    item = make_item("t1-0001", ["b", "b"])
    assert signature_of(item, "initial") == ["b", "b"]
    assert candidate_matches(item, profile)
    assert classify_item(item, profile) == "core"

    supplement = make_item("t1-0002", ["b", "k"])
    assert classify_item(supplement, profile) == "supplement"

    outsider = make_item("t1-0003", ["k", "k"])
    assert not candidate_matches(outsider, profile)
    assert classify_item(outsider, profile) is None


def test_contrast_classification_and_patterns():
    profile = contrast_profile()
    cross = make_item("t1-0010", ["z", "sh"])
    same = make_item("t1-0011", ["sh", "sh"])
    assert classify_item(cross, profile) == "cross"
    assert classify_item(same, profile) == "same"
    assert matched_patterns(cross, profile) == ["z+sh"]


def test_availability_duration_status():
    profile = bilabial_profile()
    items = [
        make_item(f"t1-01{i:02d}", ["b", "p"])
        for i in range(5)
    ] + [
        make_item(f"t1-02{i:02d}", ["b", "k"])
        for i in range(5)
    ]
    matrix = compute_availability(
        items, [profile], {"initial": ["b", "p", "m", "k"], "final": [], "tone": []}
    )
    prof = matrix["profiles"][0]
    assert prof["core_pool_size"] == 5
    assert prof["duration_sufficiency"]["5"]["status"] in {
        "OK",
        "need_repeat",
        "insufficient",
    }


def test_generate_session_v2_reproducible_and_valid():
    profile = contrast_profile()
    config = make_config()
    items = [
        make_item("t1-0101", ["z", "sh"]),
        make_item("t1-0102", ["sh", "z"]),
        make_item("t1-0103", ["z", "z"]),
        make_item("t1-0104", ["sh", "sh"]),
        make_item("t1-0105", ["c", "zh"]),
        make_item("t1-0106", ["zh", "s"]),
        make_item("t1-0107", ["zh", "zh"]),
        make_item("t1-0108", ["s", "s"]),
        make_item("t1-0109", ["ch", "ch"]),
        make_item("t1-0110", ["r", "ch"]),
    ]
    universe = {
        "initial": sorted({"z", "c", "s", "zh", "ch", "sh", "r", "k"}),
        "final": [],
        "tone": [],
    }
    availability = compute_availability(items, [profile], universe)["profiles"][0]
    a = generate_session_v2(
        profile, config, items, availability, duration_minutes=5, seed=7
    )
    b = generate_session_v2(
        profile, config, items, availability, duration_minutes=5, seed=7
    )
    c = generate_session_v2(
        profile, config, items, availability, duration_minutes=5, seed=8
    )
    ids_a = [e["item_id"] for e in a["items"]]
    assert ids_a == [e["item_id"] for e in b["items"]]
    assert len(ids_a) == len(set(ids_a))
    assert ids_a != [e["item_id"] for e in c["items"]]
    total = sum(
        v["count"] for v in a["summary"]["bucket_item_shares"].values()
    )
    assert total == a["item_count"]
    for entry in a["items"]:
        item = next(i for i in items if i.item_id == entry["item_id"])
        assert classify_item(item, profile) == entry["bucket_id"]


def test_generate_session_v2_random_seed_when_none():
    profile = contrast_profile()
    config = make_config()
    items = [
        make_item("t1-0101", ["z", "sh"]),
        make_item("t1-0102", ["sh", "z"]),
        make_item("t1-0103", ["z", "z"]),
        make_item("t1-0104", ["sh", "sh"]),
    ]
    universe = {
        "initial": sorted({"z", "c", "s", "zh", "ch", "sh", "r", "k"}),
        "final": [],
        "tone": [],
    }
    availability = compute_availability(items, [profile], universe)["profiles"][0]
    a = generate_session_v2(profile, config, items, availability, duration_minutes=5)
    b = generate_session_v2(profile, config, items, availability, duration_minutes=5)
    assert a["seed"] != b["seed"]


def test_history_window_pruning(tmp_path):
    # 以「此刻」为基准（此前硬编码 2026-08-10，跑得越久越容易误判过期）
    now = datetime.now(timezone.utc)
    path = tmp_path / "history.json"
    store = HistoryStore.load("p", path, window_days=7, window_sessions=7)
    store.add_session("s1", ["a", "b", "c"], now=now)
    assert store.recent_item_ids() == {"a", "b", "c"}
    store.save()
    # 8 days later everything is forgotten.
    store2 = HistoryStore.load("p", path, window_days=7, window_sessions=7)
    store2.entries = [
        {**e, "used_at": (now - timedelta(days=8)).isoformat()}
        for e in store2.entries
    ]
    store2.save()
    store3 = HistoryStore.load("p", path, window_days=7, window_sessions=7)
    assert store3.recent_item_ids() == set()


def test_history_soft_penalty(tmp_path):
    profile = contrast_profile()
    config = make_config()
    item = make_item("t1-0101", ["z", "sh"])
    universe = {
        "initial": sorted({"z", "c", "s", "zh", "ch", "sh", "r", "k"}),
        "final": [],
        "tone": [],
    }
    availability = compute_availability([item], [profile], universe)["profiles"][0]
    state = V2State(profile, config, _synthetic_profile(profile))
    pool_stats = _bucket_pool_stats([item], profile, config)
    rng1 = random.Random(1)
    rng2 = random.Random(1)
    without = _score_candidates(
        [item], "cross", state, profile, availability,
        config, rng1, pool_stats, set(),
    )[0][1]
    with_recent = _score_candidates(
        [item], "cross", state, profile, availability,
        config, rng2, pool_stats, {item.item_id},
    )[0][1]
    assert without - with_recent == pytest.approx(config.history_penalty)


def _front_nasal_profile() -> V2Profile:
    return V2Profile.from_dict(
        {
            "id": "front_nasal_all",
            "name": "front nasal",
            "dimension": "final",
            "mode": "single_focus",
            "target_sets": {"T": ["an", "en", "in"]},
            "buckets": [
                {
                    "id": "core",
                    "label": "core",
                    "target_ratio": 0.8,
                    "role": "core",
                    "rule": {"op": "all_in", "sets": ["T"]},
                    "pair_specs": [{"left": "T", "right": "T"}],
                },
                {
                    "id": "supplement",
                    "label": "supp",
                    "target_ratio": 0.2,
                    "role": "supplement",
                    "rule": {
                        "op": "all",
                        "rules": [
                            {"op": "any_in", "sets": ["T"]},
                            {"op": "not", "rule": {"op": "all_in", "sets": ["T"]}},
                        ],
                    },
                    "pair_specs": [
                        {"left": "T", "right": "O"},
                        {"left": "O", "right": "T"},
                    ],
                },
            ],
            "allow_other": True,
            "scarcity": {"repeat_allowed": True, "max_repeat": 3, "min_gap": 5},
        }
    )


def _nasal_items() -> list[Item]:
    items: list[Item] = []
    seq = 1
    for final in ("an", "en", "in"):
        for _ in range(40):
            items.append(
                make_item(f"t1-{seq:05d}", ["b", "b"], finals=[final, final])
            )
            seq += 1
    for _ in range(40):
        items.append(
            make_item(f"t1-{seq:05d}", ["b", "g"], finals=["ang", "ang"])
        )
        seq += 1
    for _ in range(40):
        items.append(
            make_item(f"t1-{seq:05d}", ["b", "k"], finals=["an", "a"])
        )
        seq += 1
    return items


def test_include_finals_filters_session_items():
    profile = _front_nasal_profile()
    items = _nasal_items()
    universe = _universe_from_items(items)
    availability = compute_availability(items, [profile], universe)["profiles"][0]
    session = generate_session_v2(
        profile,
        make_config(),
        items,
        availability,
        duration_minutes=5,
        seed=42,
        include_finals=["an"],
    )
    assert session["include_finals"] == ["an"]
    assert session["item_count"] > 0
    by_id = {item.item_id: item for item in items}
    target_union = set(profile.target_value_union)
    for entry in session["items"]:
        item = by_id[entry["item_id"]]
        carried = {s.final_canonical for s in item.syllables} & target_union
        assert carried == {"an"}


def test_include_finals_subset_excludes_other_targets():
    profile = _front_nasal_profile()
    items = _nasal_items()
    universe = _universe_from_items(items)
    availability = compute_availability(items, [profile], universe)["profiles"][0]
    session = generate_session_v2(
        profile,
        make_config(),
        items,
        availability,
        duration_minutes=5,
        seed=7,
        include_finals=["en", "in"],
    )
    by_id = {item.item_id: item for item in items}
    target_union = set(profile.target_value_union)
    for entry in session["items"]:
        item = by_id[entry["item_id"]]
        carried = {s.final_canonical for s in item.syllables} & target_union
        assert carried and carried <= {"en", "in"}
    assert any(
        {s.final_canonical for s in by_id[e["item_id"]].syllables} & target_union
        == {"in"}
        for e in session["items"]
    )


def test_include_finals_rejects_unknown_and_empty():
    profile = _front_nasal_profile()
    items = _nasal_items()
    universe = _universe_from_items(items)
    availability = compute_availability(items, [profile], universe)["profiles"][0]
    with pytest.raises(ValueError):
        generate_session_v2(
            profile,
            make_config(),
            items,
            availability,
            duration_minutes=5,
            seed=1,
            include_finals=["ang"],  # not in target set
        )
    with pytest.raises(ValueError):
        generate_session_v2(
            profile,
            make_config(),
            items,
            availability,
            duration_minutes=5,
            seed=1,
            include_finals=[],  # leaves no candidates
        )
