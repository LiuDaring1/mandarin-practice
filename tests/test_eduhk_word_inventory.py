"""Actual web row semantics, ambiguous occurrences, and competing word claims."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from eduhk_word_inventory import collision_free, current_partitions, group_display_rows, match_word, positional_rows


def rows(contents):
    raw = ''.join(f'<span id="x_TaskTwo_ctl{i:02d}_ResultElement">{body}</span>'
                  for i, body in enumerate(contents))
    return positional_rows(raw, 10, 'https://example.org')


def test_complementary_bold_rows_are_one_word_with_one_labelled_position():
    parsed = rows(['<b>分</b>水嶺', '分<b>水</b>嶺',
                   '分水<b>嶺</b><br><b><font>lǐng→lǐn</font></b>'])
    grouped = group_display_rows(parsed)
    assert len(grouped) == 1 and grouped[0]['mergeable']
    assert grouped[0]['nasal_errors'][0]['position'] == 2
    assert grouped[0]['nasal_errors'][0]['character'] == '嶺'
    assert grouped[0]['nasal_errors'][0]['source_word_index'] == 2
    assert match_word(['fen', 'shui', 'lin'], grouped[0]) == {'start': 0, 'length': 3, 'cost': 0}


def test_unmarked_word_does_not_supply_a_normal_label():
    grouped = group_display_rows(rows(['<b>分</b>水嶺', '分<b>水</b>嶺']))
    assert grouped[0]['nasal_errors'] == []


@pytest.mark.parametrize('contents', [
    ['<b>等</b>於', '<b>等</b>於'], ['<b>牢</b>', '牢']])
def test_repeated_same_highlight_or_unknown_target_cannot_be_merged(contents):
    group = group_display_rows(rows(contents))[0]
    assert not group['mergeable']
    assert match_word(['deng', 'yu', 'lao'], group) is None


def test_equal_cost_audio_occurrences_remain_ambiguous():
    group = group_display_rows(rows(['<b>等</b>於<br><font>děng→děn</font>']))[0]
    assert match_word(['den', 'yu', 'deng', 'yu'], group) is None


def test_lower_cost_word_claim_wins_without_using_correctness_label():
    assert collision_free([{'start': 5, 'length': 1, 'cost': 0},
                           {'start': 5, 'length': 1, 'cost': 1}]) == {0}
    assert collision_free([{'start': 5, 'length': 1, 'cost': 0},
                           {'start': 5, 'length': 1, 'cost': 0}]) == set()


def test_different_length_overlaps_are_not_treated_as_independent_words():
    assert collision_free([{'start': 5, 'length': 2, 'cost': 1},
                           {'start': 6, 'length': 3, 'cost': 0},
                           {'start': 9, 'length': 1, 'cost': 1}]) == {1, 2}


@pytest.mark.parametrize('body', ['等於<br><font>děng→děn</font>',
                                  '<b>等於</b><br><font>děng→děn</font>'])
def test_error_note_cannot_invent_target_position(body):
    with pytest.raises(ValueError, match='highlighted'):
        rows([body])


def test_stale_excluded_split_cannot_move_a_heldout_speaker_into_training():
    splits, changes = current_partitions({'rows': [{'speaker': 's40', 'split': 'holdout'}],
        'excluded': [{'id': 'unavailable', 'speaker': 's40', 'split': 'train'}]})
    assert splits == {'s40': 'holdout'}
    assert changes == [{'id': 'unavailable', 'old_split': 'train', 'current_split': 'holdout'}]
    with pytest.raises(ValueError, match='safely'):
        current_partitions({'rows': [{'speaker': 's40', 'split': 'train'}],
            'excluded': [{'id': 'unavailable', 'speaker': 's40', 'split': 'holdout'}]})
