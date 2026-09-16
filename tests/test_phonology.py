"""Unit tests for the deterministic phonology parser and tagger."""

import pytest

from pth_corpus.phonology import (
    FINAL_TABLE,
    INITIAL_FEATURES,
    build_item_features,
    normalize_pinyin,
    parse_pinyin,
)


def test_normalize_pinyin_keeps_tone_positions():
    plain, tones, orig = normalize_pinyin("āyí")
    assert plain == "ayi"
    assert tones == {0: 1, 2: 2}
    assert [orig[i] for i in range(len(plain))] == [0, 1, 2]


def test_normalize_pinyin_handles_source_special_glyphs_and_separators():
    plain, tones, _ = normalize_pinyin("bóɡěnger")
    assert plain == "bogenger"
    assert tones == {1: 2, 3: 3}


@pytest.mark.parametrize(
    "pinyin,expected",
    [
        ("bàngōngshì", ["ban", "gong", "shi"]),
        ("liàng", ["liang"]),  # not li + ang
        ("bái•tiān", ["bai", "tian"]),
        ("bù’ān", ["bu", "an"]),
        ("nǚ’ér", ["nv", "er"]),
    ],
)
def test_parse_pinyin_segmentation(pinyin, expected):
    sylls, err_type, err_detail = parse_pinyin(pinyin)
    assert err_type is None, (err_type, err_detail)
    assert [s["written"] for s in sylls] == expected


def test_parse_pinyin_erhua_r_suffix():
    sylls, err_type, _ = parse_pinyin("cháguǎnr")
    assert err_type is None
    assert [s["written"] for s in sylls] == ["cha", "guan"]
    assert sylls[-1]["erhua_suffix"] == "r_suffix"
    assert sylls[-1]["tone"] == 3


def test_parse_pinyin_erhua_er_suffix():
    sylls, err_type, _ = parse_pinyin("dànjuéer")
    assert err_type is None
    assert [s["written"] for s in sylls] == ["dan", "jue"]
    assert sylls[-1]["erhua_suffix"] == "er_suffix"
    assert sylls[-1]["tone"] == 2


def test_parse_pinyin_full_er_syllable_not_erhua():
    sylls, err_type, _ = parse_pinyin("nǚ’ér")
    assert err_type is None
    assert sylls[-1]["written"] == "er"
    assert sylls[-1]["erhua_suffix"] is None
    assert sylls[-1]["tone"] == 2


def test_parse_pinyin_missing_tone_marks_is_reviewed():
    sylls, err_type, _ = parse_pinyin("zhaizi")
    assert sylls == []
    assert err_type == "MISSING_TONE_MARKS"


def test_parse_pinyin_special_chars_is_reviewed():
    sylls, err_type, _ = parse_pinyin("piān心xīn")
    assert sylls == []
    assert err_type == "NON_STANDARD_PINYIN"


def test_parse_pinyin_unknown_syllable_is_reviewed():
    sylls, err_type, _ = parse_pinyin("zìɡǐ")
    assert sylls == []
    assert err_type == "UNPARSEABLE_SYLLABLE"


def test_item_features_aggregate_counts_and_positions():
    row = {
        "item_id": "t1-00001",
        "table_kind": "table1",
        "word_raw": "哪里",
        "pinyin_nfc": "nǎlǐ",
        "global_seq": "1",
    }
    sylls, err_type, _ = parse_pinyin(row["pinyin_nfc"])
    assert err_type is None
    item = build_item_features(row, sylls)
    assert item["status"] == "RESOLVED"
    assert item["syllable_count"] == 2
    assert item["initial_sequence"] == "n-l"
    assert item["tone_pattern_lexical"] == "3-3"
    assert item["has_adjacent_33"] is True
    assert item["third_tone_run_max"] == 2
    assert item["n_positions"] == "1"
    assert item["l_positions"] == "2"


def test_item_features_yi_and_bu_candidates():
    row = {
        "item_id": "t1-00002",
        "table_kind": "table1",
        "word_raw": "一定",
        "pinyin_nfc": "yīdìng",
        "global_seq": "2",
    }
    sylls, err_type, _ = parse_pinyin(row["pinyin_nfc"])
    assert err_type is None
    item = build_item_features(row, sylls)
    assert item["contains_yi"] is True
    assert item["yi_sandhi_candidate"] is True
    assert item["surface_tone_status"] == "NEEDS_CONTEXT"


def test_rule_tables_are_complete():
    assert len(INITIAL_FEATURES) == 22  # 21 initials + ZERO
    assert len(FINAL_TABLE) == 39
