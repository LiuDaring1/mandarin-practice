from pathlib import Path
import sys

from lxml import html
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from collect_eduhk_passages import parse_passage
from prepare_eduhk_passage_probe import chinese_reference
from prepare_ompal_controls import unanimous_correct


def test_passage_annotation_preserves_repeated_character_position():
    node = html.fromstring('<span>心，<b>心</b><b><font color="#FF0000">xīn→xìng</font></b>！<b>心</b></span>')
    result = parse_passage(node)
    assert result['text'] == '心，心！心'
    assert result['characters'] == '心心心'
    assert result['nasal_errors'][0]['position'] == 1
    assert result['nasal_errors'][0]['actual_plain'] == 'xing'


def test_non_nasal_or_tone_only_changes_are_not_nasal_labels():
    node = html.fromstring('<span>价<font color="#ff0000">jià→jiè</font>心<font color="#ff0000">xīn→xìn</font>。</span>')
    assert parse_passage(node)['nasal_errors'] == []


@pytest.mark.parametrize('scores', [[], ['1'], ['1','1'], ['1','1','0'], ['1','1','?'], 1, ['1','1',None]])
def test_insufficient_or_disagreeing_teacher_scores_are_not_positive_controls(scores):
    assert not unanimous_correct(scores)


def test_unanimous_teacher_positive_control():
    assert unanimous_correct(['1','1','1'])


def test_editorial_notes_are_not_part_of_api_reference():
    assert chinese_reference('我們相信 ，每一件ok事情。你要(miss)能問心無愧。') == '我們相信，每一件事情。你要能問心無愧。'
