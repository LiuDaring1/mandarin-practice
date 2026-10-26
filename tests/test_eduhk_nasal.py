"""Protect annotated error identity and audio localisation in research probes."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from collect_eduhk_nasal import parse_annotations, plain_pinyin
from prepare_eduhk_crops import find_word
from probe_eduhk_nasal import model_final
from report_nasal_acoustics import load_completed_report


def test_only_explicit_nasal_substitutions_are_counted():
    raw = '''<span id="x_TaskOne_ctl03_ResultElement"><b>屏</b><br><font>píng→pín</font></span>
    <span id="x_TaskTwo_ctl04_ResultElement"><b>佳</b><br><font>jiā→jiē</font></span>'''
    rows = parse_annotations(raw, 4, "https://example.org")
    assert rows[0]["word"] == "屏"
    assert rows[0]["word_index"] == 3
    assert rows[0]["nasal_errors"][0]["actual_group"] == "front"
    assert rows[1]["nasal_errors"] == []


def test_tone_normalization_preserves_umlaut():
    assert plain_pinyin("lǜ") == "lv"
    assert plain_pinyin("chéng") == "cheng"
    assert model_final("zhi") == "ii"
    assert model_final("zi") == "iii"
    assert model_final("yun") == "vn"


def test_audio_localisation_does_not_assume_page_word_order():
    row = {"word": "等於", "nasal_errors": [{"expected_plain": "deng", "actual_plain": "den"}]}
    match = find_word(["jian", "zhen", "bao", "kuo", "den", "yu"], row)
    assert match == {"start": 4, "length": 2, "pinyin_edit_cost": 0}
    assert find_word(["den", "yu", "den", "yu"], row) is None
    assert find_word(["da", "jia"], row) is None


def test_partial_batch_is_not_published_as_completed(tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"complete": false, "rows": []}')
    with pytest.raises(ValueError, match="incomplete"):
        load_completed_report(path)
