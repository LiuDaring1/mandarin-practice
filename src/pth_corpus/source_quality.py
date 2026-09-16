"""Read-only source-quality screening for word/pinyin/audio consistency.

The pilot showed that source pages can contain three independent kinds of
error (wrong pinyin for a character, wrong tone in the recording, or both).
This module screens every entry against two independent signals:

1. pinyin-lexicon check: is the recorded pinyin a legal reading of the
   character(s)?  Uses ``pypinyin`` with heteronym readings.
2. tone-contour check: for single-syllable items, does the audio's F0
   contour match the tone written in the pinyin?

The module is deliberately read-only: it never writes to SQLite or media
files, and it produces a deterministic JSON report with flagged items for a
human to triage.  It is a pre-screen for the full corpus, not a gate.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import wave
from pathlib import Path
from typing import Any

import numpy as np
from pypinyin.constants import PINYIN_DICT
from pypinyin import Style, pinyin
from scipy.ndimage import median_filter

from .db import connect_db
from .detail_fetch import atomic_write_bytes


TONE_MARKS = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"
TONE_TO_NUM = {
    "ā": 1, "á": 2, "ǎ": 3, "à": 4,
    "ē": 1, "é": 2, "ě": 3, "è": 4,
    "ī": 1, "í": 2, "ǐ": 3, "ì": 4,
    "ō": 1, "ó": 2, "ǒ": 3, "ò": 4,
    "ū": 1, "ú": 2, "ǔ": 3, "ù": 4,
    "ǖ": 1, "ǘ": 2, "ǚ": 3, "ǜ": 4,
}
BASE_MAP = {
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "ü", "ǘ": "ü", "ǚ": "ü", "ǜ": "ü",
}
SEPARATOR_RE = re.compile(r"[•·\-\.\s]+")

SAMPLE_RATE = 16_000
FRAME_MS = 30
HOP_MS = 10
MAX_SYLLABLE_LEN = 8


def _strip_tone_marks(syllable: str) -> str:
    return "".join(BASE_MAP.get(ch, ch) for ch in syllable)


def _build_syllable_set() -> set[str]:
    """Collect every pinyin syllable pypinyin knows, marked and unmarked."""

    tokens: set[str] = set()
    for _, values in PINYIN_DICT.items():
        for value in values.split(","):
            token = unicodedata.normalize("NFC", value.strip().lower())
            if token:
                tokens.add(token)
                tokens.add(_strip_tone_marks(token))
    return tokens


_SYLLABLE_SET = _build_syllable_set()


def _segment_pinyin(text: str) -> list[str] | None:
    """Split a pinyin chunk into the fewest valid syllables (DP)."""

    length = len(text)
    best_count: list[int | None] = [None] * (length + 1)
    best_prev: list[int | None] = [None] * (length + 1)
    best_count[0] = 0
    for start in range(length):
        if best_count[start] is None:
            continue
        for end in range(
            min(length, start + MAX_SYLLABLE_LEN), start, -1
        ):
            if text[start:end] not in _SYLLABLE_SET:
                continue
            candidate = best_count[start] + 1
            if best_count[end] is None or candidate < best_count[end]:
                best_count[end] = candidate
                best_prev[end] = start
    if best_count[length] is None:
        return None
    path: list[str] = []
    position = length
    while position > 0:
        start = best_prev[position]
        if start is None:
            return None
        path.append(text[start:position])
        position = start
    return path[::-1]


def normalize_db_pinyin(pinyin_nfc: str) -> tuple[list[tuple[str, int | None]], bool]:
    """Split DB pinyin into ``(base, tone)`` syllables.

    Handles the corpus's punctuation separators (``bái•tiān``), erhua suffix
    (``bàr``, ``bǎméner``) and the script ``ɡ`` spelling used in one row.
    Returns ``(syllables, erhua)`` where ``erhua`` marks a trailing ``r`` that
    was removed from the DB spelling.
    """

    text = unicodedata.normalize("NFC", pinyin_nfc).strip().lower()
    text = text.replace("\u0261", "g")  # LATIN SMALL LETTER SCRIPT G
    # Apostrophes separate syllables (``cóng'ér``); separators like ``•`` are
    # dropped.  Erhua is decided per chunk so a standalone ``ér/èr/ěr``
    # syllable (从而/女儿) is never mistaken for an erhua suffix.
    text = SEPARATOR_RE.sub("", text)
    chunks = [chunk for chunk in text.replace("\u2019", "'").split("'") if chunk]
    erhua = False
    if chunks and chunks[-1].endswith("r") and len(chunks[-1]) > 2:
        erhua = True
        chunks[-1] = chunks[-1][:-1]
        if chunks[-1].endswith("e"):  # "méner" -> "mén"
            chunks[-1] = chunks[-1][:-1]
    text = "".join(chunks)
    syllables: list[tuple[str, int | None]] = []
    for chunk in chunks:
        parsed = _segment_pinyin(chunk)
        if parsed is None:
            return [], erhua
        for raw in parsed:
            mark = next((ch for ch in raw if ch in TONE_MARKS), None)
            syllables.append(
                (_strip_tone_marks(raw), TONE_TO_NUM.get(mark) if mark else None)
            )
    return syllables, erhua


def _pypinyin_reading_sequences(word: str) -> list[list[tuple[str, int | None]]]:
    """All heteronym reading sequences for a word (and its non-erhua form)."""

    candidates: list[str] = []
    if word:
        candidates.append(word)
    if word.endswith("儿") and word[:-1]:
        candidates.append(word[:-1])
    sequences: list[list[tuple[str, int | None]]] = []
    for candidate in dict.fromkeys(candidates):
        syllables = pinyin(candidate, heteronym=True, style=Style.TONE)
        combos: list[list[str]] = [[]]
        for options in syllables:
            combos = [combo + [option] for combo in combos for option in options]
        for combo in combos:
            sequence: list[tuple[str, int | None]] = []
            for syllable in combo:
                syllable = unicodedata.normalize("NFC", syllable).lower()
                mark = next((ch for ch in syllable if ch in TONE_MARKS), None)
                sequence.append(
                    (
                        _strip_tone_marks(syllable),
                        TONE_TO_NUM.get(mark) if mark else None,
                    )
                )
            if sequence:
                sequences.append(sequence)
    return sequences


def _sequences_match(
    db_syllables: list[tuple[str, int | None]],
    reading: list[tuple[str, int | None]],
    *,
    db_erhua: bool,
) -> bool:
    """True when every DB syllable is compatible with a lexicon reading."""

    if db_erhua and len(reading) == len(db_syllables) + 1 and reading[-1][0] == "er":
        reading = reading[:-1]
    if len(db_syllables) != len(reading):
        return False
    for (db_base, db_tone), (lex_base, lex_tone) in zip(db_syllables, reading):
        if db_base != lex_base:
            return False
        if db_base in {"yi", "bu"}:  # tone sandhi in connected speech
            continue
        if db_tone is not None and lex_tone is not None and db_tone != lex_tone:
            return False
    return True


def _character_readings(word: str) -> list[set[tuple[str, int | None]]]:
    """Per-character heteronym readings (``erhua`` final char excluded)."""

    if word.endswith("儿") and len(word) > 1:
        word = word[:-1]
    result: list[set[tuple[str, int | None]]] = []
    for character in word:
        options = pinyin(character, heteronym=True, style=Style.TONE)
        readings: set[tuple[str, int | None]] = set()
        for syllable in options[0]:
            syllable = unicodedata.normalize("NFC", syllable).lower()
            mark = next((ch for ch in syllable if ch in TONE_MARKS), None)
            readings.add(
                (
                    _strip_tone_marks(syllable),
                    TONE_TO_NUM.get(mark) if mark else None,
                )
            )
        result.append(readings)
    return result


def _syllable_is_legal(
    db_syllable: tuple[str, int | None],
    readings: set[tuple[str, int | None]],
) -> bool:
    db_base, db_tone = db_syllable
    if db_base in {"yi", "bu"}:
        return True
    for lex_base, lex_tone in readings:
        if db_base != lex_base:
            continue
        if db_tone is None or lex_tone is None or db_tone == lex_tone:
            return True
    return False


def check_pinyin_lexicon(word: str, pinyin_nfc: str) -> dict[str, Any]:
    """Check that the DB pinyin is one of the character's legal readings."""

    db_syllables, erhua = normalize_db_pinyin(pinyin_nfc)
    if not db_syllables:
        return {
            "status": "unchecked",
            "note": "DB pinyin is empty or unparseable",
        }
    readings = _pypinyin_reading_sequences(word)
    if not readings:
        return {
            "status": "unchecked",
            "note": "pypinyin has no reading for this word",
        }
    compact_readings = sorted({"/".join(s for s, _ in r) for r in readings})
    if any(_sequences_match(db_syllables, reading, db_erhua=erhua) for reading in readings):
        return {"status": "ok", "readings": compact_readings}
    character_readings = _character_readings(word)
    if len(character_readings) == len(db_syllables) and all(
        _syllable_is_legal(syllable, allowed)
        for syllable, allowed in zip(db_syllables, character_readings)
    ):
        return {
            "status": "context_mismatch",
            "readings": compact_readings,
            "note": "every syllable is a legal character reading, but the word-level "
            "reading differs (possible polyphone context or source error)",
        }
    return {"status": "mismatch", "readings": compact_readings}


def single_syllable_info(pinyin_nfc: str) -> tuple[str | None, int | None]:
    """Return ``(base, tone)`` when pinyin is a single plain syllable."""

    text = unicodedata.normalize("NFC", pinyin_nfc).strip().lower()
    if text.endswith("r"):
        return None, None  # 儿化 has its own contour; skip tone check
    syllables, _ = normalize_db_pinyin(text)
    if len(syllables) != 1:
        return None, None
    base, tone = syllables[0]
    if tone is None:
        return None, None
    return base, tone


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getframerate() != SAMPLE_RATE:
            raise ValueError(f"unsupported WAV for tone check: {path}")
        return (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
            .astype(np.float32)
            / 32768.0
        )


def tone_contour(path: Path) -> dict[str, Any]:
    """Estimate F0 contour and classify the tone of a single syllable."""

    samples = _read_wav(path)
    frame = int(FRAME_MS * SAMPLE_RATE / 1000)
    hop = int(HOP_MS * SAMPLE_RATE / 1000)
    if len(samples) < frame:
        return {"voiced_ms": 0, "tone": None, "confident": False, "note": "too short"}
    frames = [samples[i : i + frame] for i in range(0, len(samples) - frame + 1, hop)]
    energies = np.array([np.sqrt(np.mean(f**2)) for f in frames])
    energy_threshold = max(1e-4, 0.10 * energies.max())
    lo, hi = int(SAMPLE_RATE / 400), int(SAMPLE_RATE / 60)

    f0s: list[float] = []
    qualities: list[float] = []
    for i, frame_samples in enumerate(frames):
        centered = frame_samples - frame_samples.mean()
        length = len(centered)
        autocorr = np.correlate(centered, centered, mode="full")[length - 1 :]
        autocorr[hi + 1 :] = 0
        if autocorr[0] <= 1e-9:
            continue
        peak_index = lo + int(np.argmax(autocorr[lo : hi + 1]))
        peak_value = autocorr[peak_index] / autocorr[0]
        if peak_value < 0.30 or energies[i] < energy_threshold:
            continue
        # Prefer the subharmonic when the octave-lower candidate is plausible.
        half_index = min(peak_index * 2, hi)
        if (
            half_index > lo
            and autocorr[half_index] / autocorr[0] > peak_value * 0.95
        ):
            peak_index = half_index
            peak_value = autocorr[half_index] / autocorr[0]
        if 0 < peak_index < len(autocorr) - 1:
            a, b, c = autocorr[peak_index - 1], autocorr[peak_index], autocorr[peak_index + 1]
            denominator = a - 2 * b + c
            if abs(denominator) > 1e-12:
                delta = 0.5 * (a - c) / denominator
                peak_index = min(max(peak_index + delta, lo), hi)
        f0s.append(SAMPLE_RATE / peak_index)
        qualities.append(float(peak_value))

    if len(f0s) < 5:
        return {"voiced_ms": int(len(f0s) * HOP_MS), "tone": None, "confident": False,
                "note": "not enough voiced frames"}
    contour = median_filter(np.array(f0s), size=min(5, len(f0s)))
    times = np.arange(len(contour)) * HOP_MS / 1000.0
    quality = float(np.mean(qualities))
    voiced_ms = int(len(contour) * HOP_MS)
    n = len(contour)
    i0, i1 = int(n * 0.15), int(n * 0.85)
    if i1 <= i0:
        i0, i1 = 0, n - 1
    t, f = times[i0:i1], contour[i0:i1]
    median_hz = float(np.median(f))
    start_hz = float(contour[i0])
    end_hz = float(contour[i1 - 1])
    slope_st_s = (
        (np.log2(end_hz / median_hz) * 12) / max(t[-1] - t[0], 0.001)
        if len(t) > 2 and median_hz > 0
        else 0.0
    )
    if slope_st_s > 6:
        tone = 2 if median_hz >= 140 else 3
    elif slope_st_s < -6:
        tone = 4
    else:
        tone = 1 if median_hz >= 150 else 3
    confident = voiced_ms >= 180 and quality >= 0.55 and len(contour) >= 8
    return {
        "voiced_ms": voiced_ms,
        "median_hz": round(median_hz, 1),
        "start_hz": round(start_hz, 1),
        "end_hz": round(end_hz, 1),
        "slope_st_s": round(float(slope_st_s), 2),
        "quality": round(quality, 3),
        "tone": tone,
        "confident": confident,
    }


def check_audio_tone(pinyin_nfc: str, clip_path: Path) -> dict[str, Any]:
    """Compare audio tone contour with the tone written in the pinyin."""

    base, expected_tone = single_syllable_info(pinyin_nfc)
    if base is None or expected_tone is None:
        return {"applicable": False}
    try:
        contour = tone_contour(clip_path)
    except (OSError, wave.Error, ValueError) as exc:
        return {"applicable": True, "status": "unchecked", "note": str(exc)}
    contour.update(
        {
            "applicable": True,
            "expected_tone": expected_tone,
            "syllable": base,
        }
    )
    if not contour["confident"]:
        contour["status"] = "low_confidence"
        return contour
    if contour["tone"] == expected_tone:
        contour["status"] = "ok"
    else:
        contour["status"] = "mismatch"
    return contour


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _latest_review_statuses(db_path: Path) -> dict[str, str]:
    with connect_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT r.item_id, r.status
            FROM reviews r
            JOIN (
                SELECT item_id, MAX(revision) AS revision
                FROM reviews GROUP BY item_id
            ) latest ON latest.item_id = r.item_id AND latest.revision = r.revision
            """
        ).fetchall()
    return {str(item_id): str(status) for item_id, status in rows}


def run_source_quality(
    db_path: str | Path,
    data_root: str | Path,
    *,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Screen every entry and write a deterministic source-quality report."""

    root = Path(data_root)
    review_statuses = _latest_review_statuses(Path(db_path))
    with connect_db(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT e.item_id, e.word_raw, e.pinyin_nfc,
                   s.clip_path, s.clip_sha256, s.algorithm_version
            FROM entries e
            JOIN segments s ON s.item_id = e.item_id
            ORDER BY CASE e.table_kind WHEN 'table1' THEN 0 ELSE 1 END,
                     e.global_seq, e.item_id
            """
        ).fetchall()

    flags: list[dict[str, Any]] = []
    suspicions: list[dict[str, Any]] = []
    lexicon_checked = 0
    tone_checked = 0
    for row in rows:
        item_id = str(row["item_id"])
        word = str(row["word_raw"])
        pinyin_nfc = str(row["pinyin_nfc"])
        clip_path = root / str(row["clip_path"])
        entry: dict[str, Any] = {
            "item_id": item_id,
            "word_raw": word,
            "pinyin_nfc": pinyin_nfc,
            "review_status": review_statuses.get(item_id, "pending"),
        }
        lexicon = check_pinyin_lexicon(word, pinyin_nfc)
        if lexicon["status"] == "ok":
            lexicon_checked += 1
        elif lexicon["status"] == "mismatch":
            flag_entry = dict(entry)
            flag_entry.update(
                {
                    "kind": "pinyin_mismatch",
                    "detail": (
                        f"DB pinyin {pinyin_nfc} is not among lexicon readings "
                        f"{', '.join(lexicon['readings'])}"
                    ),
                }
            )
            flags.append(flag_entry)
        elif lexicon["status"] == "context_mismatch":
            suspect_entry = dict(entry)
            suspect_entry.update(
                {
                    "kind": "pinyin_context_mismatch",
                    "detail": (
                        f"DB pinyin {pinyin_nfc} differs from lexicon word reading "
                        f"{', '.join(lexicon['readings'])}; syllables are legal "
                        f"character readings, so confirm polyphone context"
                    ),
                }
            )
            suspicions.append(suspect_entry)
        tone = check_audio_tone(pinyin_nfc, clip_path)
        if tone.get("applicable"):
            if tone["status"] == "ok":
                tone_checked += 1
            elif tone["status"] == "mismatch":
                flag_entry = dict(entry)
                flag_entry.update(
                    {
                        "kind": "audio_tone_mismatch",
                        "expected_tone": tone["expected_tone"],
                        "measured_tone": tone["tone"],
                        "f0": {
                            "median_hz": tone["median_hz"],
                            "start_hz": tone["start_hz"],
                            "end_hz": tone["end_hz"],
                            "slope_st_s": tone["slope_st_s"],
                            "quality": tone["quality"],
                            "voiced_ms": tone["voiced_ms"],
                        },
                    }
                )
                flags.append(flag_entry)
            elif tone["status"] == "low_confidence":
                if tone["tone"] != tone["expected_tone"]:
                    suspect_entry = dict(entry)
                    suspect_entry.update(
                        {
                            "kind": "tone_low_confidence_mismatch",
                            "expected_tone": tone["expected_tone"],
                            "measured_tone": tone["tone"],
                            "f0": {
                                "median_hz": tone["median_hz"],
                                "slope_st_s": tone["slope_st_s"],
                                "quality": tone["quality"],
                                "voiced_ms": tone["voiced_ms"],
                            },
                        }
                    )
                    suspicions.append(suspect_entry)

    report: dict[str, Any] = {
        "scope": "pilot",
        "checked_items": len(rows),
        "lexicon_ok": lexicon_checked,
        "tone_ok": tone_checked,
        "flags": flags,
        "suspicions": suspicions,
        "stats": {
            "flag_count": len(flags),
            "suspicion_count": len(suspicions),
        },
    }
    if out_path is not None:
        destination = Path(out_path)
        if not destination.is_absolute():
            destination = root / destination
        atomic_write_bytes(destination, _json_bytes(report))
        report["report_path"] = str(destination)
    return report


__all__ = [
    "check_audio_tone",
    "check_pinyin_lexicon",
    "normalize_db_pinyin",
    "run_source_quality",
    "single_syllable_info",
    "tone_contour",
]
