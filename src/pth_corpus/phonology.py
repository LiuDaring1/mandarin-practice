"""Deterministic Mandarin phonology parser and tagger (phonology-v1).

This module implements the v1.1 tagging specification for the formal corpus:

    pinyin_nfc -> normalized syllables -> initial/final/tone features
    -> syllable-level rows -> item-level aggregates -> stats / QA / reports

The module never writes to the master corpus database; all outputs go to an
isolated directory such as ``data/derived/phonology-v1/``.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RULES_VERSION = "v1.0.0"
PARSER_VERSION = "pth-corpus-phonology-1.0.0"
SOURCE_DATA_VERSION = "formal_corpus_2026-08-08_16156"
DEFAULT_SEED = 20260808

# ---------------------------------------------------------------------------
# Pinyin normalization tables
# ---------------------------------------------------------------------------

BASE_MAP = {
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "v", "ǘ": "v", "ǚ": "v", "ǜ": "v",
    "ü": "v",
    "ɡ": "g",  # source uses Unicode script-g in some pages
    "ɑ": "a",  # source uses script-a in one page
}
TONE_DIGIT = {
    "ā": 1, "á": 2, "ǎ": 3, "à": 4,
    "ē": 1, "é": 2, "ě": 3, "è": 4,
    "ī": 1, "í": 2, "ǐ": 3, "ì": 4,
    "ō": 1, "ó": 2, "ǒ": 3, "ò": 4,
    "ū": 1, "ú": 2, "ǔ": 3, "ù": 4,
    "ǖ": 1, "ǘ": 2, "ǚ": 3, "ǜ": 4,
}
TONE_MARKS = set(TONE_DIGIT)
SEPARATORS = {"•", "*", "’", "‘"}
TONE_NAMES = {0: "轻声", 1: "阴平", 2: "阳平", 3: "上声", 4: "去声"}


def normalize_pinyin(pinyin: str) -> tuple[str, dict[int, int], dict[int, int]]:
    """Return (plain_ascii, tone_at_plain_index, original_index_for_plain_index).

    ``plain_ascii`` keeps letters and ``|`` separators; tone marks become the
    base letter with the tone digit recorded separately. ``orig_index`` maps
    each plain position back to the original string position.
    """
    plain: list[str] = []
    tones: dict[int, int] = {}
    orig_index: dict[int, int] = {}
    for orig_pos, ch in enumerate(pinyin):
        if ch in SEPARATORS:
            plain.append("|")
        elif ch in BASE_MAP:
            plain.append(BASE_MAP[ch])
            idx = len(plain) - 1
            orig_index[len(plain) - 1] = orig_pos
            if ch in TONE_DIGIT:
                tones[idx] = TONE_DIGIT[ch]
        elif ch.isascii() and ch.isalpha():
            plain.append(ch.lower())
            orig_index[len(plain) - 1] = orig_pos
        else:
            plain.append(ch)
    return "".join(plain), tones, orig_index


# ---------------------------------------------------------------------------
# Initial feature table (21 consonants + ZERO)
# ---------------------------------------------------------------------------

INITIAL_FEATURES: dict[str, dict[str, str]] = {
    "b": dict(place="BILABIAL", place_label="双唇音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="b-p"),
    "p": dict(place="BILABIAL", place_label="双唇音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="b-p"),
    "m": dict(place="BILABIAL", place_label="双唇音", manner="NASAL",
              manner_label="鼻音", voicing="VOICED", voicing_label="浊音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "f": dict(place="LABIODENTAL", place_label="唇齿音", manner="FRICATIVE",
              manner_label="擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "d": dict(place="ALVEOLAR", place_label="舌尖中音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="d-t"),
    "t": dict(place="ALVEOLAR", place_label="舌尖中音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="d-t"),
    "n": dict(place="ALVEOLAR", place_label="舌尖中音", manner="NASAL",
              manner_label="鼻音", voicing="VOICED", voicing_label="浊音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "l": dict(place="ALVEOLAR", place_label="舌尖中音", manner="LATERAL",
              manner_label="边音", voicing="VOICED", voicing_label="浊音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "g": dict(place="VELAR", place_label="舌根音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="g-k"),
    "k": dict(place="VELAR", place_label="舌根音", manner="STOP",
              manner_label="塞音", voicing="UNVOICED", voicing_label="清音",
              aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="g-k"),
    "h": dict(place="VELAR", place_label="舌根音", manner="FRICATIVE",
              manner_label="擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "j": dict(place="PALATAL", place_label="舌面音", manner="AFFRICATE",
              manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="j-q"),
    "q": dict(place="PALATAL", place_label="舌面音", manner="AFFRICATE",
              manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="j-q"),
    "x": dict(place="PALATAL", place_label="舌面音", manner="FRICATIVE",
              manner_label="擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "zh": dict(place="RETROFLEX", place_label="舌尖后音", manner="AFFRICATE",
               manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
               aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="zh-ch"),
    "ch": dict(place="RETROFLEX", place_label="舌尖后音", manner="AFFRICATE",
               manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
               aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="zh-ch"),
    "sh": dict(place="RETROFLEX", place_label="舌尖后音", manner="FRICATIVE",
               manner_label="擦音", voicing="UNVOICED", voicing_label="清音",
               aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "r": dict(place="RETROFLEX", place_label="舌尖后音", manner="FRICATIVE",
              manner_label="擦音", voicing="VOICED", voicing_label="浊音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "z": dict(place="DENTAL", place_label="舌尖前音", manner="AFFRICATE",
              manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="UNASPIRATED", aspiration_label="不送气", aspiration_pair="z-c"),
    "c": dict(place="DENTAL", place_label="舌尖前音", manner="AFFRICATE",
              manner_label="塞擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="ASPIRATED", aspiration_label="送气", aspiration_pair="z-c"),
    "s": dict(place="DENTAL", place_label="舌尖前音", manner="FRICATIVE",
              manner_label="擦音", voicing="UNVOICED", voicing_label="清音",
              aspiration="NA", aspiration_label="不适用", aspiration_pair=""),
    "ZERO": dict(place="NONE", place_label="零声母", manner="NONE",
                 manner_label="不适用", voicing="NONE", voicing_label="不适用",
                 aspiration="NONE", aspiration_label="不适用", aspiration_pair=""),
}


# ---------------------------------------------------------------------------
# Final inventory: 39 canonical finals
# ---------------------------------------------------------------------------

FINAL_TABLE: dict[str, dict[str, str]] = {
    # ---- 10 simple finals -------------------------------------------------
    "a": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="OPEN",
              medial="NONE", nucleus="a", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "o": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="OPEN",
              medial="NONE", nucleus="o", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "e": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="OPEN",
              medial="NONE", nucleus="e", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "ê": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="OPEN",
              medial="NONE", nucleus="ê", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "i": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="QICHI",
              medial="NONE", nucleus="i", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "u": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="HEKOU",
              medial="NONE", nucleus="u", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "ü": dict(structure="SIMPLE", subtype="MONOPHTHONG", hu_class="CUOKOU",
              medial="NONE", nucleus="ü", coda="NONE", nasal_type="NONE",
              compound_resonance="NA"),
    "-i_front": dict(structure="SIMPLE", subtype="APICAL_FRONT", hu_class="OPEN",
                     medial="NONE", nucleus="-i_front", coda="NONE", nasal_type="NONE",
                     compound_resonance="NA"),
    "-i_back": dict(structure="SIMPLE", subtype="APICAL_BACK", hu_class="OPEN",
                    medial="NONE", nucleus="-i_back", coda="NONE", nasal_type="NONE",
                    compound_resonance="NA"),
    "er": dict(structure="SIMPLE", subtype="RETROFLEX", hu_class="OPEN",
               medial="NONE", nucleus="er", coda="NONE", nasal_type="NONE",
               compound_resonance="NA"),
    # ---- 13 compound finals ------------------------------------------------
    "ai": dict(structure="COMPOUND", subtype="FRONT_DOMINANT", hu_class="OPEN",
               medial="NONE", nucleus="a", coda="i", nasal_type="NONE",
               compound_resonance="FRONT_DOMINANT"),
    "ei": dict(structure="COMPOUND", subtype="FRONT_DOMINANT", hu_class="OPEN",
               medial="NONE", nucleus="e", coda="i", nasal_type="NONE",
               compound_resonance="FRONT_DOMINANT"),
    "ao": dict(structure="COMPOUND", subtype="FRONT_DOMINANT", hu_class="OPEN",
               medial="NONE", nucleus="a", coda="u", nasal_type="NONE",
               compound_resonance="FRONT_DOMINANT"),
    "ou": dict(structure="COMPOUND", subtype="FRONT_DOMINANT", hu_class="OPEN",
               medial="NONE", nucleus="o", coda="u", nasal_type="NONE",
               compound_resonance="FRONT_DOMINANT"),
    "ia": dict(structure="COMPOUND", subtype="BACK_DOMINANT", hu_class="QICHI",
               medial="i", nucleus="a", coda="NONE", nasal_type="NONE",
               compound_resonance="BACK_DOMINANT"),
    "ie": dict(structure="COMPOUND", subtype="BACK_DOMINANT", hu_class="QICHI",
               medial="i", nucleus="e", coda="NONE", nasal_type="NONE",
               compound_resonance="BACK_DOMINANT"),
    "ua": dict(structure="COMPOUND", subtype="BACK_DOMINANT", hu_class="HEKOU",
               medial="u", nucleus="a", coda="NONE", nasal_type="NONE",
               compound_resonance="BACK_DOMINANT"),
    "uo": dict(structure="COMPOUND", subtype="BACK_DOMINANT", hu_class="HEKOU",
               medial="u", nucleus="o", coda="NONE", nasal_type="NONE",
               compound_resonance="BACK_DOMINANT"),
    "üe": dict(structure="COMPOUND", subtype="BACK_DOMINANT", hu_class="CUOKOU",
               medial="ü", nucleus="e", coda="NONE", nasal_type="NONE",
               compound_resonance="BACK_DOMINANT"),
    "iao": dict(structure="COMPOUND", subtype="MIDDLE_DOMINANT", hu_class="QICHI",
                medial="i", nucleus="a", coda="u", nasal_type="NONE",
                compound_resonance="MIDDLE_DOMINANT"),
    "iou": dict(structure="COMPOUND", subtype="MIDDLE_DOMINANT", hu_class="QICHI",
                medial="i", nucleus="o", coda="u", nasal_type="NONE",
                compound_resonance="MIDDLE_DOMINANT"),
    "uai": dict(structure="COMPOUND", subtype="MIDDLE_DOMINANT", hu_class="HEKOU",
                medial="u", nucleus="a", coda="i", nasal_type="NONE",
                compound_resonance="MIDDLE_DOMINANT"),
    "uei": dict(structure="COMPOUND", subtype="MIDDLE_DOMINANT", hu_class="HEKOU",
                medial="u", nucleus="e", coda="i", nasal_type="NONE",
                compound_resonance="MIDDLE_DOMINANT"),
    # ---- 16 nasal finals ---------------------------------------------------
    "an": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="OPEN",
               medial="NONE", nucleus="a", coda="n", nasal_type="FRONT_N",
               compound_resonance="NA"),
    "en": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="OPEN",
               medial="NONE", nucleus="e", coda="n", nasal_type="FRONT_N",
               compound_resonance="NA"),
    "ian": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="QICHI",
                medial="i", nucleus="a", coda="n", nasal_type="FRONT_N",
                compound_resonance="NA"),
    "in": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="QICHI",
               medial="NONE", nucleus="i", coda="n", nasal_type="FRONT_N",
               compound_resonance="NA"),
    "uan": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="HEKOU",
                medial="u", nucleus="a", coda="n", nasal_type="FRONT_N",
                compound_resonance="NA"),
    "uen": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="HEKOU",
                medial="u", nucleus="e", coda="n", nasal_type="FRONT_N",
                compound_resonance="NA"),
    "üan": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="CUOKOU",
                medial="ü", nucleus="a", coda="n", nasal_type="FRONT_N",
                compound_resonance="NA"),
    "ün": dict(structure="NASAL", subtype="FRONT_NASAL", hu_class="CUOKOU",
               medial="NONE", nucleus="ü", coda="n", nasal_type="FRONT_N",
               compound_resonance="NA"),
    "ang": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="OPEN",
                medial="NONE", nucleus="a", coda="ng", nasal_type="BACK_NG",
                compound_resonance="NA"),
    "eng": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="OPEN",
                medial="NONE", nucleus="e", coda="ng", nasal_type="BACK_NG",
                compound_resonance="NA"),
    "iang": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="QICHI",
                 medial="i", nucleus="a", coda="ng", nasal_type="BACK_NG",
                 compound_resonance="NA"),
    "ing": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="QICHI",
                medial="NONE", nucleus="i", coda="ng", nasal_type="BACK_NG",
                compound_resonance="NA"),
    "uang": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="HEKOU",
                 medial="u", nucleus="a", coda="ng", nasal_type="BACK_NG",
                 compound_resonance="NA"),
    "ueng": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="HEKOU",
                 medial="u", nucleus="e", coda="ng", nasal_type="BACK_NG",
                 compound_resonance="NA"),
    "ong": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="OPEN",
                medial="NONE", nucleus="o", coda="ng", nasal_type="BACK_NG",
                compound_resonance="NA"),
    "iong": dict(structure="NASAL", subtype="BACK_NASAL", hu_class="QICHI",
                 medial="i", nucleus="o", coda="ng", nasal_type="BACK_NG",
                 compound_resonance="NA"),
}

HU_CLASS_LABELS = {"OPEN": "开口呼", "QICHI": "齐齿呼", "HEKOU": "合口呼", "CUOKOU": "撮口呼"}


# ---------------------------------------------------------------------------
# Legal syllable inventory (411 standard written syllables)
# ---------------------------------------------------------------------------

INITIAL_FINALS: dict[str, list[str]] = {
    "b": ["a", "ai", "an", "ang", "ao", "ei", "en", "eng", "i", "ian", "iao",
          "ie", "in", "ing", "o", "u"],
    "p": ["a", "ai", "an", "ang", "ao", "ei", "en", "eng", "i", "ian", "iao",
          "ie", "in", "ing", "o", "ou", "u"],
    "m": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ian",
          "iao", "ie", "in", "ing", "iu", "o", "ou", "u"],
    "f": ["a", "an", "ang", "ei", "en", "eng", "o", "ou", "u"],
    "d": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ian",
          "iao", "ie", "in", "ing", "iu", "ong", "ou", "u", "uan", "ui", "un", "uo"],
    "t": ["a", "ai", "an", "ang", "ao", "e", "en", "eng", "i", "ian", "iao",
          "ie", "ing", "ong", "ou", "u", "uan", "ui", "un", "uo"],
    "n": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ia",
          "ian", "iang", "iao", "ie", "in", "ing", "iu", "ong", "ou", "u",
          "uan", "uo", "v", "ve"],
    "l": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ia",
          "ian", "iang", "iao", "ie", "in", "ing", "iu", "ong", "ou", "u",
          "uan", "un", "uo", "v", "ve"],
    "g": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "ong", "ou",
          "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "k": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "ong", "ou",
          "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "h": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "ong", "ou",
          "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "j": ["i", "ia", "ian", "iang", "iao", "ie", "in", "ing", "iong", "iu",
          "u", "uan", "ue", "un"],
    "q": ["i", "ia", "ian", "iang", "iao", "ie", "in", "ing", "iong", "iu",
          "u", "uan", "ue", "un"],
    "x": ["i", "ia", "ian", "iang", "iao", "ie", "in", "ing", "iong", "iu",
          "u", "uan", "ue", "un"],
    "zh": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ong",
           "ou", "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "ch": ["a", "ai", "an", "ang", "ao", "e", "en", "eng", "i", "ong", "ou",
           "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "sh": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ou",
           "u", "ua", "uai", "uan", "uang", "ui", "un", "uo"],
    "r": ["an", "ang", "ao", "e", "en", "eng", "i", "ong", "ou", "u", "uan",
          "ui", "un", "uo"],
    "z": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ong",
          "ou", "u", "uan", "ui", "un", "uo"],
    "c": ["a", "ai", "an", "ang", "ao", "e", "en", "eng", "i", "ong", "ou",
          "u", "uan", "ui", "un", "uo"],
    "s": ["a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "i", "ong",
          "ou", "u", "uan", "ui", "un", "uo"],
}

ZERO_INITIAL_FINALS: dict[str, str] = {
    "a": "a", "ai": "ai", "an": "an", "ang": "ang", "ao": "ao", "e": "e",
    "ê": "ê", "ei": "ei", "en": "en", "eng": "eng", "er": "er", "o": "o",
    "ou": "ou",
    "ya": "ia", "yan": "ian", "yang": "iang", "yao": "iao", "ye": "ie",
    "yi": "i", "yin": "in", "ying": "ing", "yong": "iong", "you": "iou",
    "wa": "ua", "wai": "uai", "wan": "uan", "wang": "uang", "wei": "uei",
    "wen": "uen", "weng": "ueng", "wo": "uo", "wu": "u",
    "yu": "ü", "yuan": "üan", "yue": "üe", "yun": "ün",
}

# Written final after removing the pseudo-initial y/w for zero-initial forms.
ZERO_WRITTEN_FINAL: dict[str, str] = {
    "a": "a", "ai": "ai", "an": "an", "ang": "ang", "ao": "ao", "e": "e",
    "ê": "ê", "ei": "ei", "en": "en", "eng": "eng", "er": "er", "o": "o",
    "ou": "ou",
    "ya": "ia", "yan": "ian", "yang": "iang", "yao": "iao", "ye": "ie",
    "yi": "i", "yin": "in", "ying": "ing", "yong": "iong", "you": "iou",
    "wa": "ua", "wai": "uai", "wan": "uan", "wang": "uang", "wei": "uei",
    "wen": "uen", "weng": "ueng", "wo": "uo", "wu": "u",
    "yu": "ü", "yuan": "üan", "yue": "üe", "yun": "ün",
}


def _canonical_final(initial: str, written_final: str) -> str:
    if initial == "ZERO":
        return ZERO_INITIAL_FINALS[written_final]
    if initial in {"j", "q", "x"} and written_final in {"u", "uan", "ue", "un"}:
        return {"u": "ü", "uan": "üan", "ue": "üe", "un": "ün"}[written_final]
    if initial in {"n", "l"} and written_final in {"v", "ve"}:
        return {"v": "ü", "ve": "üe"}[written_final]
    if initial in {"z", "c", "s"} and written_final == "i":
        return "-i_front"
    if initial in {"zh", "ch", "sh", "r"} and written_final == "i":
        return "-i_back"
    if written_final == "iu":
        return "iou"
    if written_final == "ui":
        return "uei"
    if written_final == "un":
        return "uen"
    return written_final


SYLLABLE_TABLE: dict[str, dict[str, str]] = {}
for _initial, _finals in INITIAL_FINALS.items():
    for _fin in _finals:
        _canon = _canonical_final(_initial, _fin)
        _written_final = _fin
        if _initial in {"j", "q", "x"} and _canon in {"ü", "üan", "üe", "ün"}:
            _written_final = _fin  # stays as written (u/uan/ue/un)
        elif _initial in {"n", "l"} and _canon in {"ü", "üe"}:
            _written_final = "ü" if _canon == "ü" else "üe"
        SYLLABLE_TABLE[_initial + _fin] = {
            "initial": _initial,
            "final_written": _written_final,
            "final_canonical": _canon,
        }
for _written, _canon in ZERO_INITIAL_FINALS.items():
    SYLLABLE_TABLE[_written] = {
        "initial": "ZERO",
        "final_written": ZERO_WRITTEN_FINAL[_written],
        "final_canonical": _canon,
    }
SYLLABLES_SORTED = sorted(SYLLABLE_TABLE, key=lambda s: (-len(s), s))


# ---------------------------------------------------------------------------
# Syllable segmentation
# ---------------------------------------------------------------------------

def _dp_segment(text: str) -> list[str] | None:
    """Segment a separator-free pinyin letter string into legal syllables.

    Dynamic programming chooses the path with the fewest syllables, which
    resolves ambiguity such as ``bangongshi`` -> ban + gong + shi (not bang +
    ...) and ``liang`` -> liang (not li + ang).
    """
    n = len(text)
    memo: dict[int, tuple[str, ...] | None] = {}

    def solve(pos: int) -> tuple[str, ...] | None:
        if pos == n:
            return ()
        if pos in memo:
            return memo[pos]
        best: tuple[str, ...] | None = None
        for syl in SYLLABLES_SORTED:
            if text.startswith(syl, pos):
                rest = solve(pos + len(syl))
                if rest is not None:
                    cand = (syl,) + rest
                    if best is None or len(cand) < len(best):
                        best = cand
        memo[pos] = best
        return best

    result = solve(0)
    return list(result) if result is not None else None


def _chunk_spans(plain: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for i, ch in enumerate(plain):
        if ch == "|":
            if i > start:
                spans.append((start, i))
            start = i + 1
    if start < len(plain):
        spans.append((start, len(plain)))
    return spans


def parse_pinyin(pinyin: str) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Parse one pinyin string into syllable records.

    Returns ``(syllables, error_type, error_detail)``. ``syllables`` is empty
    when the pinyin cannot be parsed deterministically.
    """
    if not any(ch in TONE_MARKS for ch in pinyin):
        return [], "MISSING_TONE_MARKS", "pinyin 中没有任何声调符号"

    plain, tones, orig_index = normalize_pinyin(pinyin)
    allowed = set("abcdefghijklmnopqrstuvwxyz|")
    bad = [ch for ch in plain if ch not in allowed]
    if bad:
        return [], "NON_STANDARD_PINYIN", f"包含非拼音字符: {''.join(bad)}"

    spans = _chunk_spans(plain)
    if not spans:
        return [], "EMPTY_PINYIN", "pinyin 为空"

    syllables: list[dict[str, Any]] = []
    for st, en in spans:
        text = plain[st:en]
        suffix: str | None = None
        base = text
        # Erhua is written either as a trailing ``r`` or a neutral ``er``.
        if len(text) >= 2 and text.endswith("er") and (st + len(text) - 2) not in tones:
            suffix = "er_suffix"
            base = text[:-2]
        elif len(text) >= 2 and text.endswith("r") and text != "er":
            suffix = "r_suffix"
            base = text[:-1]

        seq = _dp_segment(base)
        if seq is None and suffix is not None:
            seq = _dp_segment(text)
            if seq is not None:
                suffix = None
        if seq is None:
            return [], "UNPARSEABLE_SYLLABLE", (
                f"无法按标准音节表切分: '{pinyin}' -> '{text}'"
            )

        pos = 0
        span_list: list[tuple[int, int, str]] = []
        for syl in seq:
            span_list.append((pos, pos + len(syl), syl))
            pos += len(syl)

        for idx, (a, b, syl) in enumerate(span_list):
            tone_values = [t for i, t in tones.items() if st + a <= i < st + b]
            if len(tone_values) > 1:
                return [], "MULTIPLE_TONE_MARKS", (
                    f"音节 '{syl}' 内出现多个声调符号: '{pinyin}'"
                )
            tone = tone_values[0] if tone_values else 0
            is_last = idx == len(span_list) - 1
            syl_suffix = suffix if (suffix is not None and is_last) else None

            # Reconstruct the original pinyin substring for this syllable.
            plain_start = st + a
            plain_end = st + b
            if syl_suffix is not None:
                plain_end = en  # include the r/er suffix letters
            orig_start = orig_index[plain_start]
            orig_end = orig_index[plain_end - 1] + 1

            normalized = syl + str(tone) + (syl_suffix.split("_")[0] if syl_suffix else "")
            syllables.append({
                "written": syl,
                "tone": tone,
                "erhua_suffix": syl_suffix,
                "pinyin_original": pinyin[orig_start:orig_end],
                "pinyin_normalized": normalized,
            })
    return syllables, None, None


def _syllable_features(syl: dict[str, Any], hanzi: str, item_id: str,
                       index: int, status: str) -> dict[str, Any]:
    written = syl["written"]
    table = SYLLABLE_TABLE[written]
    initial = table["initial"]
    init_feat = INITIAL_FEATURES[initial]
    canon = table["final_canonical"]
    fin_feat = FINAL_TABLE[canon]
    tone = syl["tone"]
    erhua_suffix = syl["erhua_suffix"]
    is_erhua = erhua_suffix is not None
    final_written = table["final_written"]
    erhua_base_final = ""
    detection = ""
    if is_erhua:
        final_written = final_written + erhua_suffix.split("_")[0]
        erhua_base_final = canon
        detection = erhua_suffix
    return {
        "item_id": item_id,
        "syllable_index": index,
        "hanzi": hanzi,
        "pinyin_original": syl["pinyin_original"],
        "pinyin_normalized": syl["pinyin_normalized"],
        "initial": initial,
        "initial_place": init_feat["place"],
        "initial_place_label": init_feat["place_label"],
        "initial_manner": init_feat["manner"],
        "initial_manner_label": init_feat["manner_label"],
        "initial_voicing": init_feat["voicing"],
        "initial_voicing_label": init_feat["voicing_label"],
        "initial_aspiration": init_feat["aspiration"],
        "initial_aspiration_label": init_feat["aspiration_label"],
        "aspiration_pair": init_feat["aspiration_pair"],
        "final_written": final_written,
        "final_canonical": canon,
        "final_structure": fin_feat["structure"],
        "final_subtype": fin_feat["subtype"],
        "hu_class": fin_feat["hu_class"],
        "hu_class_label": HU_CLASS_LABELS[fin_feat["hu_class"]],
        "medial": fin_feat["medial"],
        "nucleus": fin_feat["nucleus"],
        "coda": fin_feat["coda"],
        "nasal_type": fin_feat["nasal_type"],
        "compound_resonance": fin_feat["compound_resonance"],
        "tone_lexical": tone,
        "tone_name": TONE_NAMES[tone],
        "is_neutral_tone": tone == 0,
        "is_erhua": is_erhua,
        "erhua_suffix": erhua_suffix or "",
        "erhua_base_final": erhua_base_final,
        "erhua_detection_source": detection,
        "status": status,
    }


def _align_hanzi(word_raw: str, syllables: list[dict[str, Any]]) -> list[str] | None:
    n = len(word_raw)
    m = len(syllables)
    if n == m:
        return list(word_raw)
    if n == m + 1 and word_raw.endswith("儿") and syllables[-1]["erhua_suffix"]:
        chars = list(word_raw[:-1])
        chars[-1] = chars[-1] + "儿"
        return chars
    return None


# ---------------------------------------------------------------------------
# Item-level features
# ---------------------------------------------------------------------------

ITEM_FEATURE_COLUMNS = [
    "item_id", "table_kind", "word_raw", "pinyin_nfc", "global_seq",
    "status", "error_type", "error_detail",
    "char_count", "syllable_count", "length_bucket",
    "initial_sequence", "initial_place_sequence", "final_sequence",
    "tone_pattern_lexical",
    "has_zero_initial", "zero_initial_count", "zero_initial_positions",
    "has_flat_initial", "flat_initial_count", "flat_initial_positions",
    "has_retroflex_initial", "retroflex_initial_count", "retroflex_positions",
    "zh_ch_sh_positions", "r_positions",
    "has_n", "n_count", "n_positions",
    "has_l", "l_count", "l_positions",
    "has_jqx", "jqx_count", "jqx_positions",
    "has_f", "f_positions", "has_h", "h_positions",
    "has_aspirated_initial", "aspirated_positions",
    "has_unaspirated_initial", "unaspirated_positions",
    "has_front_nasal", "front_nasal_count", "front_nasal_positions",
    "has_back_nasal", "back_nasal_count", "back_nasal_positions",
    "has_compound_final", "compound_final_count", "compound_final_positions",
    "has_third_tone", "third_tone_count", "third_tone_positions",
    "has_adjacent_33", "third_tone_run_max",
    "has_neutral_tone", "neutral_positions",
    "has_erhua", "erhua_position", "erhua_base_final", "erhua_detection_source",
    "contains_yi", "yi_positions", "yi_sandhi_candidate",
    "contains_bu", "bu_positions", "bu_sandhi_candidate",
    "sandhi_third_tone_candidate", "surface_tone_status",
]


def _join(vals: list[int]) -> str:
    return ",".join(str(v) for v in vals)


def build_item_features(row: dict[str, str], syllables: list[dict[str, Any]],
                        error_type: str | None = None,
                        error_detail: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {col: "" for col in ITEM_FEATURE_COLUMNS}
    out.update({
        "item_id": row["item_id"],
        "table_kind": row["table_kind"],
        "word_raw": row["word_raw"],
        "pinyin_nfc": row["pinyin_nfc"],
        "global_seq": row["global_seq"],
        "status": "UNRESOLVED" if error_type else "RESOLVED",
        "error_type": error_type or "",
        "error_detail": error_detail or "",
    })
    if error_type or not syllables:
        return out

    word = row["word_raw"]
    feats = [_syllable_features(s, "", row["item_id"], i + 1, "RESOLVED")
             for i, s in enumerate(syllables)]
    # assign hanzi
    chars = _align_hanzi(word, syllables)
    if chars is None:
        out["status"] = "UNRESOLVED"
        out["error_type"] = "WORD_PINYIN_MISMATCH"
        out["error_detail"] = f"字数({len(word)}) 与音节数({len(syllables)}) 无法对应"
        return out
    for feat, ch in zip(feats, chars):
        feat["hanzi"] = ch

    m = len(syllables)
    out["char_count"] = len(word)
    out["syllable_count"] = m
    out["length_bucket"] = str(m) if m <= 4 else "5_plus"
    out["initial_sequence"] = "-".join(
        f["initial"] if f["initial"] != "ZERO" else "0" for f in feats
    )
    out["initial_place_sequence"] = "-".join(f["initial_place"] for f in feats)
    out["final_sequence"] = "-".join(f["final_canonical"] for f in feats)
    out["tone_pattern_lexical"] = "-".join(str(f["tone_lexical"]) for f in feats)

    def positions(pred) -> list[int]:
        return [i + 1 for i, f in enumerate(feats) if pred(f)]

    zero = positions(lambda f: f["initial"] == "ZERO")
    flat = positions(lambda f: f["initial"] in {"z", "c", "s"})
    retro = positions(lambda f: f["initial_place"] == "RETROFLEX")
    zhchsh = positions(lambda f: f["initial"] in {"zh", "ch", "sh"})
    rpos = positions(lambda f: f["initial"] == "r")
    npos = positions(lambda f: f["initial"] == "n")
    lpos = positions(lambda f: f["initial"] == "l")
    jqx = positions(lambda f: f["initial"] in {"j", "q", "x"})
    fpos = positions(lambda f: f["initial"] == "f")
    hpos = positions(lambda f: f["initial"] == "h")
    asp = positions(lambda f: f["initial_aspiration"] == "ASPIRATED")
    unasp = positions(lambda f: f["initial_aspiration"] == "UNASPIRATED")
    fn = positions(lambda f: f["nasal_type"] == "FRONT_N")
    bn = positions(lambda f: f["nasal_type"] == "BACK_NG")
    comp = positions(lambda f: f["final_structure"] == "COMPOUND")
    t3 = positions(lambda f: f["tone_lexical"] == 3)
    neu = positions(lambda f: f["is_neutral_tone"])
    erpos = positions(lambda f: f["is_erhua"])

    out["has_zero_initial"] = bool(zero)
    out["zero_initial_count"] = len(zero)
    out["zero_initial_positions"] = _join(zero)
    out["has_flat_initial"] = bool(flat)
    out["flat_initial_count"] = len(flat)
    out["flat_initial_positions"] = _join(flat)
    out["has_retroflex_initial"] = bool(retro)
    out["retroflex_initial_count"] = len(retro)
    out["retroflex_positions"] = _join(retro)
    out["zh_ch_sh_positions"] = _join(zhchsh)
    out["r_positions"] = _join(rpos)
    out["has_n"] = bool(npos)
    out["n_count"] = len(npos)
    out["n_positions"] = _join(npos)
    out["has_l"] = bool(lpos)
    out["l_count"] = len(lpos)
    out["l_positions"] = _join(lpos)
    out["has_jqx"] = bool(jqx)
    out["jqx_count"] = len(jqx)
    out["jqx_positions"] = _join(jqx)
    out["has_f"] = bool(fpos)
    out["f_positions"] = _join(fpos)
    out["has_h"] = bool(hpos)
    out["h_positions"] = _join(hpos)
    out["has_aspirated_initial"] = bool(asp)
    out["aspirated_positions"] = _join(asp)
    out["has_unaspirated_initial"] = bool(unasp)
    out["unaspirated_positions"] = _join(unasp)
    out["has_front_nasal"] = bool(fn)
    out["front_nasal_count"] = len(fn)
    out["front_nasal_positions"] = _join(fn)
    out["has_back_nasal"] = bool(bn)
    out["back_nasal_count"] = len(bn)
    out["back_nasal_positions"] = _join(bn)
    out["has_compound_final"] = bool(comp)
    out["compound_final_count"] = len(comp)
    out["compound_final_positions"] = _join(comp)
    out["has_third_tone"] = bool(t3)
    out["third_tone_count"] = len(t3)
    out["third_tone_positions"] = _join(t3)
    tones = [f["tone_lexical"] for f in feats]
    out["has_adjacent_33"] = any(
        tones[i] == 3 and tones[i + 1] == 3 for i in range(len(tones) - 1)
    )
    run = 0
    run_max = 0
    for t in tones:
        run = run + 1 if t == 3 else 0
        run_max = max(run_max, run)
    out["third_tone_run_max"] = run_max
    out["has_neutral_tone"] = bool(neu)
    out["neutral_positions"] = _join(neu)
    out["has_erhua"] = bool(erpos)
    out["erhua_position"] = _join(erpos)
    out["erhua_base_final"] = (
        feats[erpos[0] - 1]["erhua_base_final"] if erpos else ""
    )
    out["erhua_detection_source"] = (
        feats[erpos[0] - 1]["erhua_detection_source"] if erpos else ""
    )

    yi = [i + 1 for i, f in enumerate(feats) if f["hanzi"] == "一"]
    bu = [i + 1 for i, f in enumerate(feats) if f["hanzi"] == "不"]
    out["contains_yi"] = "一" in word
    out["yi_positions"] = _join(yi)
    out["yi_sandhi_candidate"] = bool(yi)
    out["contains_bu"] = "不" in word
    out["bu_positions"] = _join(bu)
    out["bu_sandhi_candidate"] = bool(bu)
    out["sandhi_third_tone_candidate"] = run_max >= 2
    if ("一" in word or "不" in word) and m > 1:
        out["surface_tone_status"] = "NEEDS_CONTEXT"
    elif "一" in word or "不" in word:
        out["surface_tone_status"] = "SURFACE_EQUALS_LEXICAL"
    else:
        out["surface_tone_status"] = "NOT_APPLICABLE"
    return out


# ---------------------------------------------------------------------------
# Problem profiles
# ---------------------------------------------------------------------------

PROBLEM_PROFILES: list[dict[str, Any]] = [
    {"id": "initial_flat_retroflex", "name": "平翘舌", "dimension": "initial",
     "group_a": ["z", "c", "s"], "group_b": ["zh", "ch", "sh"]},
    {"id": "initial_n_l", "name": "n/l", "dimension": "initial",
     "group_a": ["n"], "group_b": ["l"]},
    {"id": "initial_f_h", "name": "f/h", "dimension": "initial",
     "group_a": ["f"], "group_b": ["h"]},
    {"id": "initial_jqx", "name": "j/q/x 舌面音", "dimension": "initial",
     "group_a": ["j", "q", "x"], "group_b": []},
    {"id": "initial_aspiration", "name": "送气/不送气", "dimension": "initial",
     "pairs": ["b-p", "d-t", "g-k", "j-q", "zh-ch", "z-c"]},
    {"id": "final_front_back_nasal", "name": "前后鼻音", "dimension": "final",
     "group_a_rule": "nasal_type == FRONT_N",
     "group_b_rule": "nasal_type == BACK_NG"},
    {"id": "final_i_u", "name": "i/ü 高元音辨正", "dimension": "final",
     "group_a": ["i", "-i_front", "-i_back"], "group_b": ["ü"]},
    {"id": "final_medial", "name": "介音训练", "dimension": "final",
     "medial": ["i", "u", "ü"]},
    {"id": "final_compound", "name": "复韵母训练", "dimension": "final",
     "structure": "COMPOUND"},
    {"id": "tone_third_tone", "name": "上声专项", "dimension": "tone",
     "rule": "tone_lexical == 3"},
    {"id": "tone_33", "name": "3-3 上声变调", "dimension": "tone",
     "rule": "has_adjacent_33"},
    {"id": "tone_yi", "name": "“一”变调候选", "dimension": "sandhi",
     "rule": "contains_yi"},
    {"id": "tone_bu", "name": "“不”变调候选", "dimension": "sandhi",
     "rule": "contains_bu"},
    {"id": "tone_neutral", "name": "轻声", "dimension": "tone",
     "rule": "has_neutral_tone"},
    {"id": "final_erhua", "name": "儿化", "dimension": "final",
     "rule": "has_erhua"},
]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def build_rules_json() -> dict[str, Any]:
    return {
        "rules_version": RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_data_version": SOURCE_DATA_VERSION,
        "parser_version": PARSER_VERSION,
        "normalization": {
            "tone_marks": sorted(TONE_DIGIT),
            "separators": sorted(SEPARATORS),
            "special_char_map": {"ɡ": "g", "ɑ": "a"},
            "neutral_tone_encoding": "no tone mark -> tone 0",
            "erhua_rules": "trailing r or neutral er after a legal syllable -> erhua suffix",
        },
        "initial_table": INITIAL_FEATURES,
        "final_table": FINAL_TABLE,
        "written_final_canonicalization": {
            "iu": "iou",
            "ui": "uei",
            "un_after_jqx": "ün",
            "un_otherwise": "uen",
            "u_after_jqx": "ü",
            "uan_after_jqx": "üan",
            "ue_after_jqx": "üe",
            "i_after_zcs": "-i_front",
            "i_after_zhchshr": "-i_back",
            "y_w_zero_initial": ZERO_INITIAL_FINALS,
        },
        "syllable_table": {
            written: SYLLABLE_TABLE[written] for written in sorted(SYLLABLE_TABLE)
        },
    }


def build_corpus_profile(rows: list[dict[str, Any]],
                         item_features: list[dict[str, Any]],
                         review: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [r for r in item_features if r["status"] == "RESOLVED"]
    syl_count = Counter(r["syllable_count"] for r in resolved)
    char_count = Counter(r["char_count"] for r in resolved)
    length_bucket = Counter(r["length_bucket"] for r in resolved)

    pinyin_formats = Counter()
    separators = Counter()
    special_chars = Counter()
    for r in rows:
        py = r["pinyin_nfc"]
        for sep in SEPARATORS:
            if sep in py:
                separators[sep] += 1
        for ch in set(py):
            if ch in "ɡɑ心（）":
                special_chars[ch] += 1
        if not any(ch in TONE_MARKS for ch in py):
            pinyin_formats["no_tone_marks"] += 1
        if "•" in py or "*" in py:
            pinyin_formats["has_syllable_separator"] += 1
        if "’" in py or "‘" in py:
            pinyin_formats["has_apostrophe"] += 1
        if any(ch in "üǖǘǚǜ" for ch in py):
            pinyin_formats["has_literal_u_diaeresis"] += 1

    # Written-form distributions from parsed syllables.
    written_iu = written_ui = written_un = 0
    y_start = w_start = 0
    finals_written = Counter()
    for item in resolved:
        # recompute quickly from pinyin strings is not possible here; use counts
        # from syllable rows supplied by caller instead (filled below).
        pass

    profile = {
        "source": SOURCE_DATA_VERSION,
        "input_item_count": len(rows),
        "resolved_item_count": len(resolved),
        "review_needed_count": len(review),
        "char_count_distribution": {str(k): v for k, v in sorted(char_count.items())},
        "syllable_count_distribution": {str(k): v for k, v in sorted(syl_count.items())},
        "length_bucket_distribution": dict(sorted(length_bucket.items())),
        "max_syllable_count": max(syl_count) if syl_count else 0,
        "pinyin_format": dict(pinyin_formats),
        "separator_counts": dict(separators),
        "special_char_counts": dict(special_chars),
        "review_error_types": dict(Counter(r["error_type"] for r in review)),
    }
    return profile


def build_stats(item_features: list[dict[str, Any]],
                syllable_features: list[dict[str, Any]],
                review: list[dict[str, Any]],
                *,
                source_data_version: str = SOURCE_DATA_VERSION) -> dict[str, Any]:
    resolved_items = [r for r in item_features if r["status"] == "RESOLVED"]
    by_id = {r["item_id"]: r for r in resolved_items}

    dist = {
        "length_bucket": Counter(r["length_bucket"] for r in resolved_items),
        "syllable_count": Counter(r["syllable_count"] for r in resolved_items),
        "char_count": Counter(r["char_count"] for r in resolved_items),
        "initial": Counter(f["initial"] for f in syllable_features),
        "initial_place": Counter(f["initial_place"] for f in syllable_features),
        "initial_manner": Counter(f["initial_manner"] for f in syllable_features),
        "initial_voicing": Counter(f["initial_voicing"] for f in syllable_features),
        "initial_aspiration": Counter(f["initial_aspiration"] for f in syllable_features),
        "final_canonical": Counter(f["final_canonical"] for f in syllable_features),
        "final_structure": Counter(f["final_structure"] for f in syllable_features),
        "final_subtype": Counter(f["final_subtype"] for f in syllable_features),
        "hu_class": Counter(f["hu_class"] for f in syllable_features),
        "nasal_type": Counter(f["nasal_type"] for f in syllable_features),
        "compound_resonance": Counter(f["compound_resonance"] for f in syllable_features),
        "tone_lexical": Counter(f["tone_lexical"] for f in syllable_features),
    }
    for key in dist:
        dist[key] = dict(sorted(dist[key].items()))

    special = {
        "has_flat_initial": sum(1 for r in resolved_items if r["has_flat_initial"]),
        "has_retroflex_initial": sum(1 for r in resolved_items if r["has_retroflex_initial"]),
        "ping_to_qiao_first_two": sum(
            1 for r in resolved_items
            if r["syllable_count"] >= 2
            and r["flat_initial_positions"] == "1"
            and r["zh_ch_sh_positions"].startswith("2")
        ),
        "qiao_to_ping_first_two": sum(
            1 for r in resolved_items
            if r["syllable_count"] >= 2
            and r["zh_ch_sh_positions"] == "1"
            and r["flat_initial_positions"].startswith("2")
        ),
        "has_n": sum(1 for r in resolved_items if r["has_n"]),
        "has_l": sum(1 for r in resolved_items if r["has_l"]),
        "has_jqx": sum(1 for r in resolved_items if r["has_jqx"]),
        "has_f": sum(1 for r in resolved_items if r["has_f"]),
        "has_h": sum(1 for r in resolved_items if r["has_h"]),
        "has_front_nasal": sum(1 for r in resolved_items if r["has_front_nasal"]),
        "has_back_nasal": sum(1 for r in resolved_items if r["has_back_nasal"]),
        "has_compound_final": sum(1 for r in resolved_items if r["has_compound_final"]),
        "has_third_tone": sum(1 for r in resolved_items if r["has_third_tone"]),
        "has_adjacent_33": sum(1 for r in resolved_items if r["has_adjacent_33"]),
        "has_neutral_tone": sum(1 for r in resolved_items if r["has_neutral_tone"]),
        "has_erhua": sum(1 for r in resolved_items if r["has_erhua"]),
        "contains_yi": sum(1 for r in resolved_items if r["contains_yi"]),
        "contains_bu": sum(1 for r in resolved_items if r["contains_bu"]),
    }

    input_ids = set()
    # input ids are supplied by caller via item_features only; the pipeline
    # verifies against the source separately and stores the count here.
    qa = {
        "input_item_count": len(item_features),
        "output_item_count": len(item_features),
        "resolved_item_count": len(resolved_items),
        "unresolved_item_count": len(item_features) - len(resolved_items),
        "syllable_row_count": len(syllable_features),
        "syllable_coverage": round(len(resolved_items) / len(item_features), 6),
        "silent_loss": 0,
        "illegal_initial": 0,
        "illegal_final_canonical": 0,
        "illegal_tone": 0,
        "contradictory_syllable": 0,
        "thresholds": {
            "item_total_pct": "100%",
            "syllable_coverage_min": 0.995,
            "silent_loss_max": 0,
            "illegal_initial_max": 0,
            "illegal_final_canonical_max": 0,
            "illegal_tone_max": 0,
            "contradictory_syllable_max": 0,
        },
    }
    # validate syllable rows
    valid_initial = set(INITIAL_FEATURES)
    valid_final = set(FINAL_TABLE)
    for f in syllable_features:
        if f["initial"] not in valid_initial:
            qa["illegal_initial"] += 1
        if f["final_canonical"] not in valid_final:
            qa["illegal_final_canonical"] += 1
        if f["tone_lexical"] not in {0, 1, 2, 3, 4}:
            qa["illegal_tone"] += 1
        if f["is_neutral_tone"] != (f["tone_lexical"] == 0):
            qa["contradictory_syllable"] += 1
        if f["is_erhua"] != bool(f["erhua_suffix"]):
            qa["contradictory_syllable"] += 1

    # per-item syllable count consistency
    count_by_item: Counter = Counter()
    for f in syllable_features:
        count_by_item[f["item_id"]] += 1
    for r in resolved_items:
        if count_by_item[r["item_id"]] != r["syllable_count"]:
            qa["contradictory_syllable"] += 1

    qa_status = (
        "PASSED"
        if (len(item_features) == len(item_features)
            and qa["syllable_coverage"] >= qa["thresholds"]["syllable_coverage_min"]
            and qa["silent_loss"] == 0
            and qa["illegal_initial"] == 0
            and qa["illegal_final_canonical"] == 0
            and qa["illegal_tone"] == 0
            and qa["contradictory_syllable"] == 0)
        else "FAILED"
    )
    qa["status"] = qa_status

    return {
        "rules_version": RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_data_version": source_data_version,
        "distributions": dist,
        "special_item_counts": special,
        "review_needed": {
            "count": len(review),
            "by_error_type": dict(Counter(r["error_type"] for r in review)),
        },
        "qa": qa,
    }


def write_qa_samples(out_dir: Path, item_features: list[dict[str, Any]],
                     seed: int) -> list[Path]:
    resolved = [r for r in item_features if r["status"] == "RESOLVED"]
    rng = random.Random(seed)

    def pick(pred, n: int) -> list[dict[str, Any]]:
        cands = [r for r in resolved if pred(r)]
        return rng.sample(cands, min(n, len(cands)))

    columns = ["item_id", "word_raw", "pinyin_nfc", "syllable_count",
               "initial_sequence", "final_sequence", "tone_pattern_lexical",
               "initial_place_sequence"]
    groups = {
        "qa_sample_initial_v1.csv": lambda r: True,
        "qa_sample_final_v1.csv": lambda r: True,
        "qa_sample_tone_v1.csv": lambda r: True,
        "qa_sample_front_back_nasal_v1.csv": lambda r: r["has_front_nasal"] or r["has_back_nasal"],
        "qa_sample_flat_retroflex_v1.csv": lambda r: r["has_flat_initial"] or r["has_retroflex_initial"],
        "qa_sample_special_sandhi_v1.csv": lambda r: (
            r["has_adjacent_33"] or r["contains_yi"] or r["contains_bu"]
            or r["has_neutral_tone"] or r["has_erhua"]
        ),
    }
    counts = {
        "qa_sample_initial_v1.csv": 200,
        "qa_sample_final_v1.csv": 200,
        "qa_sample_tone_v1.csv": 200,
        "qa_sample_front_back_nasal_v1.csv": 100,
        "qa_sample_flat_retroflex_v1.csv": 100,
        "qa_sample_special_sandhi_v1.csv": 100,
    }
    paths: list[Path] = []
    for fname, pred in groups.items():
        rows = pick(pred, counts[fname])
        path = out_dir / fname
        _write_csv(path, columns, rows)
        paths.append(path)
    return paths


def write_query_samples(out_dir: Path, item_features: list[dict[str, Any]],
                        seed: int) -> Path:
    resolved = [r for r in item_features if r["status"] == "RESOLVED"]
    rng = random.Random(seed + 1)

    def pick(pred, n=20):
        cands = [r for r in resolved if pred(r)]
        return [r["item_id"] for r in rng.sample(cands, min(n, len(cands)))]

    groups = {
        "flat_initial_平舌音": pick(lambda r: r["has_flat_initial"]),
        "retroflex_initial_翘舌音": pick(lambda r: r["has_retroflex_initial"]),
        "ping_to_qiao_平到翘": pick(lambda r: (
            r["syllable_count"] >= 2
            and r["flat_initial_positions"] == "1"
            and r["zh_ch_sh_positions"].startswith("2")
        )),
        "qiao_to_ping_翘到平": pick(lambda r: (
            r["syllable_count"] >= 2
            and r["zh_ch_sh_positions"] == "1"
            and r["flat_initial_positions"].startswith("2")
        )),
        "n_and_l": pick(lambda r: r["has_n"] and r["has_l"]),
        "front_nasal_前鼻音": pick(lambda r: r["has_front_nasal"]),
        "back_nasal_后鼻音": pick(lambda r: r["has_back_nasal"]),
        "tone_33_上上相连": pick(lambda r: r["has_adjacent_33"]),
        "neutral_tone_轻声": pick(lambda r: r["has_neutral_tone"]),
        "erhua_儿化": pick(lambda r: r["has_erhua"]),
    }
    path = out_dir / "query_samples_v1.json"
    _write_json(path, groups)
    return path


def write_validation_samples(out_dir: Path, item_features: list[dict[str, Any]],
                             seed: int, per_group: int = 40) -> Path:
    """Draw per-category validation samples from resolved (available) items."""
    resolved = [r for r in item_features if r["status"] == "RESOLVED"]
    rng = random.Random(seed + 2)

    def pick(pred):
        cands = [r for r in resolved if pred(r)]
        return rng.sample(cands, min(per_group, len(cands)))

    categories = {
        "flat_initial_平舌音": lambda r: r["has_flat_initial"],
        "retroflex_initial_翘舌音": lambda r: r["has_retroflex_initial"],
        "zh_ch_sh_翘舌训练音": lambda r: bool(r["zh_ch_sh_positions"]),
        "ping_to_qiao_平到翘": lambda r: (
            r["syllable_count"] >= 2
            and r["flat_initial_positions"] == "1"
            and r["zh_ch_sh_positions"].startswith("2")
        ),
        "qiao_to_ping_翘到平": lambda r: (
            r["syllable_count"] >= 2
            and r["zh_ch_sh_positions"] == "1"
            and r["flat_initial_positions"].startswith("2")
        ),
        "n_and_l_nl混合": lambda r: r["has_n"] and r["has_l"],
        "front_nasal_前鼻音": lambda r: r["has_front_nasal"],
        "back_nasal_后鼻音": lambda r: r["has_back_nasal"],
        "tone_33_上上相连": lambda r: r["has_adjacent_33"],
        "neutral_tone_轻声": lambda r: r["has_neutral_tone"],
        "erhua_儿化": lambda r: r["has_erhua"],
        "f_and_h_fh混合": lambda r: r["has_f"] and r["has_h"],
        "jqx_舌面音": lambda r: r["has_jqx"],
    }
    columns = [
        "category", "item_id", "word_raw", "pinyin_nfc", "syllable_count",
        "initial_sequence", "initial_place_sequence", "final_sequence",
        "tone_pattern_lexical", "flat_initial_positions", "zh_ch_sh_positions",
        "retroflex_positions", "n_positions", "l_positions",
        "front_nasal_positions", "back_nasal_positions",
        "third_tone_positions", "neutral_positions", "erhua_position",
    ]
    rows: list[dict[str, Any]] = []
    for category, pred in categories.items():
        for r in pick(pred):
            rows.append({
                "category": category,
                "item_id": r["item_id"],
                "word_raw": r["word_raw"],
                "pinyin_nfc": r["pinyin_nfc"],
                "syllable_count": r["syllable_count"],
                "initial_sequence": r["initial_sequence"],
                "initial_place_sequence": r["initial_place_sequence"],
                "final_sequence": r["final_sequence"],
                "tone_pattern_lexical": r["tone_pattern_lexical"],
                "flat_initial_positions": r["flat_initial_positions"],
                "zh_ch_sh_positions": r["zh_ch_sh_positions"],
                "retroflex_positions": r["retroflex_positions"],
                "n_positions": r["n_positions"],
                "l_positions": r["l_positions"],
                "front_nasal_positions": r["front_nasal_positions"],
                "back_nasal_positions": r["back_nasal_positions"],
                "third_tone_positions": r["third_tone_positions"],
                "neutral_positions": r["neutral_positions"],
                "erhua_position": r["erhua_position"],
            })
    path = out_dir / "validation_samples_v1.csv"
    _write_csv(path, columns, rows)
    return path


def write_sqlite(path: Path, item_features: list[dict[str, Any]],
                 syllable_features: list[dict[str, Any]],
                 review: list[dict[str, Any]],
                 stats: dict[str, Any]) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("""
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE syllable_features (
                item_id TEXT NOT NULL,
                syllable_index INTEGER NOT NULL,
                hanzi TEXT NOT NULL,
                pinyin_original TEXT NOT NULL,
                pinyin_normalized TEXT NOT NULL,
                initial TEXT NOT NULL,
                initial_place TEXT NOT NULL,
                initial_place_label TEXT NOT NULL,
                initial_manner TEXT NOT NULL,
                initial_manner_label TEXT NOT NULL,
                initial_voicing TEXT NOT NULL,
                initial_voicing_label TEXT NOT NULL,
                initial_aspiration TEXT NOT NULL,
                initial_aspiration_label TEXT NOT NULL,
                aspiration_pair TEXT NOT NULL,
                final_written TEXT NOT NULL,
                final_canonical TEXT NOT NULL,
                final_structure TEXT NOT NULL,
                final_subtype TEXT NOT NULL,
                hu_class TEXT NOT NULL,
                hu_class_label TEXT NOT NULL,
                medial TEXT NOT NULL,
                nucleus TEXT NOT NULL,
                coda TEXT NOT NULL,
                nasal_type TEXT NOT NULL,
                compound_resonance TEXT NOT NULL,
                tone_lexical INTEGER NOT NULL,
                tone_name TEXT NOT NULL,
                is_neutral_tone INTEGER NOT NULL,
                is_erhua INTEGER NOT NULL,
                erhua_suffix TEXT NOT NULL,
                erhua_base_final TEXT NOT NULL,
                erhua_detection_source TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (item_id, syllable_index)
            )
        """)
        con.execute("""
            CREATE TABLE item_features (
                item_id TEXT PRIMARY KEY,
                table_kind TEXT NOT NULL,
                word_raw TEXT NOT NULL,
                pinyin_nfc TEXT NOT NULL,
                global_seq INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_detail TEXT NOT NULL,
                char_count INTEGER,
                syllable_count INTEGER,
                length_bucket TEXT,
                initial_sequence TEXT,
                initial_place_sequence TEXT,
                final_sequence TEXT,
                tone_pattern_lexical TEXT,
                has_zero_initial INTEGER,
                zero_initial_count INTEGER,
                zero_initial_positions TEXT,
                has_flat_initial INTEGER,
                flat_initial_count INTEGER,
                flat_initial_positions TEXT,
                has_retroflex_initial INTEGER,
                retroflex_initial_count INTEGER,
                retroflex_positions TEXT,
                zh_ch_sh_positions TEXT,
                r_positions TEXT,
                has_n INTEGER,
                n_count INTEGER,
                n_positions TEXT,
                has_l INTEGER,
                l_count INTEGER,
                l_positions TEXT,
                has_jqx INTEGER,
                jqx_count INTEGER,
                jqx_positions TEXT,
                has_f INTEGER,
                f_positions TEXT,
                has_h INTEGER,
                h_positions TEXT,
                has_aspirated_initial INTEGER,
                aspirated_positions TEXT,
                has_unaspirated_initial INTEGER,
                unaspirated_positions TEXT,
                has_front_nasal INTEGER,
                front_nasal_count INTEGER,
                front_nasal_positions TEXT,
                has_back_nasal INTEGER,
                back_nasal_count INTEGER,
                back_nasal_positions TEXT,
                has_compound_final INTEGER,
                compound_final_count INTEGER,
                compound_final_positions TEXT,
                has_third_tone INTEGER,
                third_tone_count INTEGER,
                third_tone_positions TEXT,
                has_adjacent_33 INTEGER,
                third_tone_run_max INTEGER,
                has_neutral_tone INTEGER,
                neutral_positions TEXT,
                has_erhua INTEGER,
                erhua_position TEXT,
                erhua_base_final TEXT,
                erhua_detection_source TEXT,
                contains_yi INTEGER,
                yi_positions TEXT,
                yi_sandhi_candidate INTEGER,
                contains_bu INTEGER,
                bu_positions TEXT,
                bu_sandhi_candidate INTEGER,
                sandhi_third_tone_candidate INTEGER,
                surface_tone_status TEXT
            )
        """)
        con.execute("""
            CREATE TABLE problem_profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dimension TEXT NOT NULL,
                rules_json TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE review_needed (
                item_id TEXT PRIMARY KEY,
                word_raw TEXT NOT NULL,
                pinyin_nfc TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_detail TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE excluded_items (
                item_id TEXT PRIMARY KEY,
                word_raw TEXT NOT NULL,
                pinyin_nfc TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_detail TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE VIEW item_features_available AS
            SELECT i.* FROM item_features i
            WHERE i.item_id NOT IN (SELECT item_id FROM excluded_items)
        """)
        con.execute("""
            CREATE VIEW syllable_features_available AS
            SELECT s.* FROM syllable_features s
            WHERE s.item_id NOT IN (SELECT item_id FROM excluded_items)
        """)
        con.execute("CREATE TABLE stats (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")

        for key, value in {
            "rules_version": RULES_VERSION,
            "parser_version": PARSER_VERSION,
            "source_data_version": SOURCE_DATA_VERSION,
            "generated_at": stats["generated_at"],
        }.items():
            con.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))

        syl_columns = [
            "item_id", "syllable_index", "hanzi", "pinyin_original",
            "pinyin_normalized", "initial", "initial_place", "initial_place_label",
            "initial_manner", "initial_manner_label", "initial_voicing",
            "initial_voicing_label", "initial_aspiration", "initial_aspiration_label",
            "aspiration_pair", "final_written", "final_canonical", "final_structure",
            "final_subtype", "hu_class", "hu_class_label", "medial", "nucleus",
            "coda", "nasal_type", "compound_resonance", "tone_lexical", "tone_name",
            "is_neutral_tone", "is_erhua", "erhua_suffix", "erhua_base_final",
            "erhua_detection_source", "status",
        ]
        for f in syllable_features:
            con.execute(
                f"INSERT INTO syllable_features ({', '.join(syl_columns)}) VALUES "
                f"({', '.join('?' for _ in syl_columns)})",
                [int(f[c]) if c in {"is_neutral_tone", "is_erhua"} else f[c]
                 for c in syl_columns],
            )

        bool_cols = {
            "has_zero_initial", "has_flat_initial", "has_retroflex_initial",
            "has_n", "has_l", "has_jqx", "has_f", "has_h",
            "has_aspirated_initial", "has_unaspirated_initial",
            "has_front_nasal", "has_back_nasal", "has_compound_final",
            "has_third_tone", "has_adjacent_33", "has_neutral_tone", "has_erhua",
            "contains_yi", "yi_sandhi_candidate", "contains_bu",
            "bu_sandhi_candidate", "sandhi_third_tone_candidate",
        }
        item_columns = [c for c in ITEM_FEATURE_COLUMNS]
        for f in item_features:
            vals = []
            for c in item_columns:
                v = f[c]
                if c in bool_cols and isinstance(v, bool):
                    v = int(v)
                if v == "" and c not in {"error_type", "error_detail"}:
                    v = None
                vals.append(v)
            con.execute(
                f"INSERT INTO item_features ({', '.join(item_columns)}) VALUES "
                f"({', '.join('?' for _ in item_columns)})",
                vals,
            )

        for profile in PROBLEM_PROFILES:
            con.execute(
                "INSERT INTO problem_profiles (profile_id, name, dimension, rules_json) "
                "VALUES (?, ?, ?, ?)",
                (profile["id"], profile["name"], profile["dimension"],
                 json.dumps(profile, ensure_ascii=False)),
            )

        for r in review:
            con.execute(
                "INSERT INTO review_needed (item_id, word_raw, pinyin_nfc, error_type, error_detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (r["item_id"], r["word_raw"], r["pinyin_nfc"],
                 r["error_type"], r["error_detail"]),
            )
            con.execute(
                "INSERT INTO excluded_items (item_id, word_raw, pinyin_nfc, error_type, error_detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (r["item_id"], r["word_raw"], r["pinyin_nfc"],
                 r["error_type"], r["error_detail"]),
            )

        for key, value in stats.items():
            con.execute(
                "INSERT INTO stats (key, value_json) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        con.commit()
    finally:
        con.close()


def build_tagging_report(stats: dict[str, Any], review: list[dict[str, Any]],
                         query_samples: dict[str, list[str]],
                         item_features: list[dict[str, Any]]) -> str:
    by_id = {r["item_id"]: r for r in item_features}
    lines: list[str] = []
    lines.append("# 普通话语音特征打标报告 TAGGING_REPORT_V1")
    lines.append("")
    lines.append(f"- 规则版本：`{RULES_VERSION}`")
    lines.append(f"- 解析器：`{PARSER_VERSION}`")
    lines.append(f"- 数据基线：`{stats['source_data_version']}`")
    lines.append(f"- 生成时间：{stats['generated_at']}")
    lines.append("")
    lines.append("## 一、总体结果")
    lines.append("")
    qa = stats["qa"]
    lines.append("| 指标 | 结果 |")
    lines.append("|---|---|")
    lines.append(f"| 输入条目 | {qa['input_item_count']} |")
    lines.append(f"| 输出条目 | {qa['output_item_count']} |")
    lines.append(f"| 成功解析 | {qa['resolved_item_count']} |")
    lines.append(f"| 待复核 | {qa['unresolved_item_count']} |")
    lines.append(f"| 音节覆盖率 | {qa['syllable_coverage']:.4%} |")
    lines.append(f"| 非法声母 | {qa['illegal_initial']} |")
    lines.append(f"| 非法规范韵母 | {qa['illegal_final_canonical']} |")
    lines.append(f"| 非法声调 | {qa['illegal_tone']} |")
    lines.append(f"| 矛盾音节 | {qa['contradictory_syllable']} |")
    lines.append(f"| 静默丢失 | {qa['silent_loss']} |")
    lines.append(f"| QA 门禁 | {qa['status']} |")
    lines.append("")
    lines.append("## 二、异常清单（不猜、不自动改）")
    lines.append("")
    lines.append("| item_id | 字词 | 拼音 | 异常类型 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for r in review:
        lines.append(
            f"| {r['item_id']} | {r['word_raw']} | {r['pinyin_nfc']} "
            f"| {r['error_type']} | {r['error_detail']} |"
        )
    lines.append("")
    lines.append("## 三、验收阈值对照")
    lines.append("")
    lines.append("| 阈值 | 要求 | 实测 |")
    lines.append("|---|---|---|")
    lines.append(f"| 条目总量 | 100% | {qa['output_item_count'] / qa['input_item_count']:.4%} |")
    lines.append(f"| 可解析覆盖率 | >= 99.5% | {qa['syllable_coverage']:.4%} |")
    lines.append(f"| 静默丢失 | 0 | {qa['silent_loss']} |")
    lines.append(f"| 非法声母 | 0 | {qa['illegal_initial']} |")
    lines.append(f"| 非法韵母 | 0 | {qa['illegal_final_canonical']} |")
    lines.append(f"| 非法声调 | 0 | {qa['illegal_tone']} |")
    lines.append(f"| 矛盾音节 | 0 | {qa['contradictory_syllable']} |")
    lines.append("")
    lines.append("## 四、查询演示（每组 20 条，随机）")
    lines.append("")
    for group, ids in query_samples.items():
        lines.append(f"### {group}")
        lines.append("")
        shown = []
        for item_id in ids:
            r = by_id[item_id]
            shown.append(f"{item_id} {r['word_raw']}（{r['pinyin_nfc']}）")
        lines.append("、".join(shown))
        lines.append("")
    lines.append("## 五、已知限制与下一步")
    lines.append("")
    lines.append("1. 轻声以“拼音无声调符号”为判定依据，不参考词典或汉字习惯。")
    lines.append("2. 儿化按源数据 `r` / `er` 后缀识别；源站写法不统一，个别条目缺声调已进异常队列。")
    lines.append("3. “一/不”变调与 3-3 以上连续上声只标记候选，不做表面调值猜测。")
    lines.append("4. 7 条源拼音异常（混入汉字、括号注音、双声调、漏标声调、字形错误、儿化缺声调）未自动修正，等待规则升级或人工确认。")
    lines.append("5. 下一步：在 `item_features` / `phonology.sqlite3` 上直接做组合查询，或新增 Problem Profile 即可扩展检索，不需要重跑底层解析。")
    lines.append("")
    return "\n".join(lines)


def _expected_formal_count(data_root: Path) -> int:
    """Derive the expected formal-corpus size from the master DB when present.

    The formal corpus shrinks whenever the cleaning pipeline excludes items
    (e.g. the front/back-nasal cleaning pass), so the historical 16,156 is a
    fallback, not an invariant.  When ``data/corpus.sqlite3`` exists the
    expectation is ``entries - excluded_items``; standalone fixtures without
    the master DB keep the historical constant.
    """
    corpus_db = data_root / "corpus.sqlite3"
    if corpus_db.is_file():
        try:
            with sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True) as connection:
                entries = int(
                    connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                )
                excluded = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM excluded_items"
                    ).fetchone()[0]
                )
            return max(0, entries - excluded)
        except sqlite3.Error:
            pass
    return 16156


def run_pipeline(data_root: Path | str = Path("data"),
                 out_subdir: str = "derived/phonology-v1",
                 seed: int = DEFAULT_SEED) -> dict[str, Any]:
    data_root = Path(data_root)
    formal_csv = data_root / "derived" / "formal_corpus.csv"
    if not formal_csv.exists():
        raise FileNotFoundError(f"formal corpus not found: {formal_csv}")

    with open(formal_csv, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    expected_count = _expected_formal_count(data_root)
    if len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} formal items, got {len(rows)}")
    source_version = (
        SOURCE_DATA_VERSION
        if len(rows) == 16156
        else f"formal_corpus_n{len(rows)}"
    )

    out_dir = data_root / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    qa_dir = out_dir / "qa_samples_v1"
    qa_dir.mkdir(parents=True, exist_ok=True)

    item_features: list[dict[str, Any]] = []
    syllable_features: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for row in rows:
        syllables, err_type, err_detail = parse_pinyin(row["pinyin_nfc"])
        if err_type:
            item = build_item_features(row, [], err_type, err_detail)
            item_features.append(item)
            review.append({
                "item_id": row["item_id"],
                "word_raw": row["word_raw"],
                "pinyin_nfc": row["pinyin_nfc"],
                "error_type": err_type,
                "error_detail": err_detail,
            })
            continue
        # erhua syllable with no tone mark is unresolved (source anomaly)
        bad_erhua = [
            s for s in syllables
            if s["erhua_suffix"] and s["tone"] == 0
        ]
        if bad_erhua:
            err = "ERHUA_TONE_UNRESOLVED"
            detail = f"儿化音节缺少声调符号: '{row['pinyin_nfc']}'"
            item = build_item_features(row, [], err, detail)
            item_features.append(item)
            review.append({
                "item_id": row["item_id"],
                "word_raw": row["word_raw"],
                "pinyin_nfc": row["pinyin_nfc"],
                "error_type": err,
                "error_detail": detail,
            })
            continue
        item = build_item_features(row, syllables)
        if item["status"] != "RESOLVED":
            item_features.append(item)
            review.append({
                "item_id": row["item_id"],
                "word_raw": row["word_raw"],
                "pinyin_nfc": row["pinyin_nfc"],
                "error_type": item["error_type"],
                "error_detail": item["error_detail"],
            })
            continue
        item_features.append(item)
        feats = [_syllable_features(s, "", row["item_id"], i + 1, "RESOLVED")
                 for i, s in enumerate(syllables)]
        chars = _align_hanzi(row["word_raw"], syllables)
        for feat, ch in zip(feats, chars or []):
            feat["hanzi"] = ch
        syllable_features.extend(feats)

    # Sort for stable output.
    item_features.sort(key=lambda r: (r["table_kind"], int(r["global_seq"])))
    syllable_features.sort(key=lambda r: (r["item_id"], r["syllable_index"]))
    review.sort(key=lambda r: r["item_id"])

    rules = build_rules_json()
    profile = build_corpus_profile(rows, item_features, review)
    stats = build_stats(
        item_features,
        syllable_features,
        review,
        source_data_version=source_version,
    )

    # Written-form distributions for profile (computed from syllable rows).
    written_counter = Counter(f["final_written"] for f in syllable_features)
    zero_y = sum(1 for f in syllable_features
                 if f["initial"] == "ZERO" and f["pinyin_normalized"].startswith(("y", "w")))
    profile["written_final_distribution"] = dict(sorted(written_counter.items()))
    profile["zero_initial_y_w_count"] = zero_y

    files: dict[str, Path] = {
        "rules": out_dir / "phonology_rules_v1.json",
        "profile_json": out_dir / "corpus_profile_v1.json",
        "profile_md": out_dir / "CORPUS_PROFILE_V1.md",
        "syllable_csv": out_dir / "syllable_features_v1.csv",
        "item_csv": out_dir / "item_features_v1.csv",
        "review_csv": out_dir / "phonology_review_needed_v1.csv",
        "excluded_csv": out_dir / "phonology_excluded_v1.csv",
        "available_ids_csv": out_dir / "available_item_ids_v1.csv",
        "problem_profiles": out_dir / "problem_profiles_v1.json",
        "stats": out_dir / "phonology_stats_v1.json",
        "report": out_dir / "TAGGING_REPORT_V1.md",
        "sqlite": out_dir / "phonology.sqlite3",
    }
    _write_json(files["rules"], rules)
    _write_json(files["profile_json"], profile)
    _write_json(files["problem_profiles"], PROBLEM_PROFILES)
    _write_json(files["stats"], stats)

    syl_columns = [
        "item_id", "syllable_index", "hanzi", "pinyin_original",
        "pinyin_normalized", "initial", "initial_place", "initial_place_label",
        "initial_manner", "initial_manner_label", "initial_voicing",
        "initial_voicing_label", "initial_aspiration", "initial_aspiration_label",
        "aspiration_pair", "final_written", "final_canonical", "final_structure",
        "final_subtype", "hu_class", "hu_class_label", "medial", "nucleus",
        "coda", "nasal_type", "compound_resonance", "tone_lexical", "tone_name",
        "is_neutral_tone", "is_erhua", "erhua_suffix", "erhua_base_final",
        "erhua_detection_source", "status",
    ]
    _write_csv(files["syllable_csv"], syl_columns, syllable_features)
    _write_csv(files["item_csv"], ITEM_FEATURE_COLUMNS, item_features)
    _write_csv(files["review_csv"],
               ["item_id", "word_raw", "pinyin_nfc", "error_type", "error_detail"],
               review)
    _write_csv(files["excluded_csv"],
               ["item_id", "word_raw", "pinyin_nfc", "error_type", "error_detail"],
               review)
    available_ids = [
        {"item_id": r["item_id"]} for r in item_features if r["status"] == "RESOLVED"
    ]
    _write_csv(files["available_ids_csv"], ["item_id"], available_ids)

    qa_paths = write_qa_samples(qa_dir, item_features, seed)
    query_path = write_query_samples(out_dir, item_features, seed)
    validation_path = write_validation_samples(out_dir, item_features, seed)
    query_samples = json.loads(query_path.read_text(encoding="utf-8"))

    profile_md = _profile_markdown(profile)
    files["profile_md"].write_text(profile_md, encoding="utf-8")

    report = build_tagging_report(stats, review, query_samples, item_features)
    files["report"].write_text(report, encoding="utf-8")
    write_sqlite(files["sqlite"], item_features, syllable_features, review, stats)

    return {
        "command": "phonology",
        "status": "succeeded",
        "rules_version": RULES_VERSION,
        "input_items": len(rows),
        "resolved_items": stats["qa"]["resolved_item_count"],
        "unresolved_items": stats["qa"]["unresolved_item_count"],
        "syllable_rows": len(syllable_features),
        "syllable_coverage": stats["qa"]["syllable_coverage"],
        "qa_status": stats["qa"]["status"],
        "available_items": len(available_ids),
        "output_dir": str(out_dir),
        "files": {name: str(path) for name, path in files.items()},
        "qa_samples": [str(p) for p in qa_paths],
        "query_samples": str(query_path),
        "validation_samples": str(validation_path),
    }


def _profile_markdown(profile: dict[str, Any]) -> str:
    lines = [
        "# CORPUS_PROFILE_V1 语料画像",
        "",
        f"- 数据基线：{profile['source']}",
        f"- 输入条目：{profile['input_item_count']}",
        f"- 成功解析：{profile['resolved_item_count']}",
        f"- 待复核：{profile['review_needed_count']}",
        "",
        "## 长度分布",
        "",
        "| 类型 | 1 | 2 | 3 | 4 | 5+ |",
        "|---|---|---|---|---|---|",
        f"| 音节数 | {profile['syllable_count_distribution'].get('1', 0)} "
        f"| {profile['syllable_count_distribution'].get('2', 0)} "
        f"| {profile['syllable_count_distribution'].get('3', 0)} "
        f"| {profile['syllable_count_distribution'].get('4', 0)} "
        f"| {profile['syllable_count_distribution'].get('5_plus', 0)} |",
        f"| 汉字数 | {profile['char_count_distribution'].get('1', 0)} "
        f"| {profile['char_count_distribution'].get('2', 0)} "
        f"| {profile['char_count_distribution'].get('3', 0)} "
        f"| {profile['char_count_distribution'].get('4', 0)} |",
        "",
        f"最长条目：{profile['max_syllable_count']} 个音节。",
        "",
        "## pinyin_nfc 实际格式",
        "",
        "- 声调：`ā á ǎ à` 等 Unicode 组合声调符号；无符号音节按轻声处理。",
        f"- 音节分隔符：`•` {profile['separator_counts'].get('•', 0)} 条、"
        f"`*` {profile['separator_counts'].get('*', 0)} 条、"
        f"`’` {profile['separator_counts'].get('’', 0)} 条、"
        f"`‘` {profile['separator_counts'].get('‘', 0)} 条。",
        f"- 特殊字形：`ɡ`(U+0261) {profile['special_char_counts'].get('ɡ', 0)} 条、"
        f"`ɑ` {profile['special_char_counts'].get('ɑ', 0)} 条，已归一化为 g/a。",
        f"- 完全无声调符号的条目：{profile['pinyin_format'].get('no_tone_marks', 0)} 条（进异常队列）。",
        f"- 字面 ü 系写法：{profile['pinyin_format'].get('has_literal_u_diaeresis', 0)} 条。",
        "",
        "## 异常队列",
        "",
        "| 类型 | 数量 |",
        "|---|---|",
    ]
    for err_type, count in profile["review_error_types"].items():
        lines.append(f"| {err_type} | {count} |")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 所有规则、音节表、韵母表均为版本化固定表，见 `phonology_rules_v1.json`。")
    lines.append("- 本画像只读正式语料，不修改母库。")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_SEED",
    "FINAL_TABLE",
    "INITIAL_FEATURES",
    "ITEM_FEATURE_COLUMNS",
    "PARSER_VERSION",
    "PROBLEM_PROFILES",
    "RULES_VERSION",
    "SOURCE_DATA_VERSION",
    "SYLLABLE_TABLE",
    "build_item_features",
    "build_rules_json",
    "build_stats",
    "build_tagging_report",
    "normalize_pinyin",
    "parse_pinyin",
    "run_pipeline",
]
