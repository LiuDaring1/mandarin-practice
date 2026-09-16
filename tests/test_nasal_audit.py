"""Unit tests for the front/back-nasal audio-vs-text audit classifier."""

from __future__ import annotations

from pth_corpus.nasal_audit import (
    NasalItem,
    char_sim,
    classify,
    clean_asr_text,
    same_sound_ignoring_tone,
)


def _item(
    item_id: str = "t1-00001",
    word: str = "安全",
    finals: tuple[str, ...] = ("an",),
    syllable_count: int = 2,
    table_kind: str = "table1",
    global_seq: int = 1,
) -> NasalItem:
    return NasalItem(
        item_id=item_id,
        table_kind=table_kind,
        word=word,
        pinyin="ānquán",
        syllable_count=syllable_count,
        finals=finals,
        global_seq=global_seq,
    )


def test_clean_asr_text_keeps_only_hanzi():
    assert clean_asr_text("《诗经》。") == "诗经"
    assert clean_asr_text("  alright 123 ") == ""
    assert clean_asr_text("") == ""


def test_char_sim_and_homophone():
    assert char_sim("阿姨", "阿姨") == 1.0
    assert char_sim("收長", "首要") == 0.0
    assert same_sound_ignoring_tone("手要", "首要")
    assert not same_sound_ignoring_tone("收藏", "首要")
    assert not same_sound_ignoring_tone("", "首要")


def test_classify_ok_when_whisper_matches():
    item = _item(word="阿姨", finals=("a",), syllable_count=2)
    tier, _reason = classify(item, "阿姨", {}, "", "")
    assert tier == "OK"


def test_classify_homophone_tier():
    item = _item(word="首要", finals=("iao",), syllable_count=2)
    tier, _reason = classify(item, "手要", {}, "前词", "后词")
    assert tier == "T4_homophone"


def test_classify_shift_when_whisper_matches_neighbour():
    item = _item(word="本能", finals=("en",), syllable_count=2)
    tier, reason = classify(item, "本领", {}, "本领", "本事")
    assert tier == "T3_shift"
    assert "本领" in reason


def test_classify_strong_tier_with_qwen3_and_fresh_mismatch():
    item = _item(word="军区", finals=("ün",), syllable_count=2)
    evidence = {"qwen3_mismatch": {"asr": "近期。"}}
    tier, _reason = classify(item, "近期", evidence, "军备", "军号")
    assert tier == "T1_strong"


def test_classify_single_syllable_uses_tone_flag():
    item = _item(word="安", finals=("an",), syllable_count=1)
    evidence = {
        "sourcecheck_flag": {"kind": "audio_tone_mismatch"}
    }
    tier, _reason = classify(item, "岸", evidence, "阿姨", "安放")
    assert tier == "T4_tone"


def test_classify_single_syllable_without_flags_is_reference_only():
    item = _item(word="安", finals=("an",), syllable_count=1)
    tier, _reason = classify(item, "岸", {}, "阿姨", "安放")
    assert tier == "T5_single"


def test_classify_unverifiable_when_no_hanzi():
    item = _item(word="安全", finals=("an",), syllable_count=2)
    tier, _reason = classify(item, "alright", {}, "", "")
    assert tier == "T5_unverifiable"


def test_nasal_item_flags():
    front = _item(finals=("an", "en"))
    back = _item(finals=("ang",))
    both = _item(finals=("an", "ang"))
    assert front.has_front and not front.has_back and not front.is_contrast
    assert back.has_back and not back.has_front
    assert both.is_contrast


def test_classify_ok_requires_exact_match():
    # A half-identical whisper text is the "reads a different word" class the
    # audit hunts; it must never land in OK.
    item = _item(word="成人", finals=("eng",), syllable_count=2)
    tier, reason = classify(item, "行人", {}, "前词", "后词")
    assert tier == "T2_mismatch"
    assert "高度相似" in reason


def test_classify_near_match_with_both_asr_agree_is_strong():
    item = _item(word="成人", finals=("eng",), syllable_count=2)
    evidence = {"qwen3_audit": {"asr": "行人", "score": "0.3"}}
    tier, _reason = classify(item, "行人", evidence, "前词", "后词")
    assert tier == "T1_strong"


def test_classify_exact_match_still_ok():
    item = _item(word="安全", finals=("an",), syllable_count=2)
    tier, _reason = classify(item, "安全", {}, "前词", "后词")
    assert tier == "OK"


def test_classify_ok_tier_in_order():
    from pth_corpus.nasal_audit import TIER_ORDER

    assert TIER_ORDER.index("OK") > TIER_ORDER.index("T2_mismatch")
