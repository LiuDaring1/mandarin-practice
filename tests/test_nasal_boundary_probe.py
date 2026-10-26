from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from probe_nasal_boundaries import replace_bounds, summarize_denominator


def test_clipping_never_fabricates_a_vowel_when_intervals_do_not_overlap():
    original = {'syllable': [.01, .6], 'vowel': [.38, .6]}
    assert replace_bounds(original, [.29, .52], 'clip') == {'syllable': [.29, .52], 'vowel': [.38, .52]}
    assert replace_bounds(original, [.7, .9], 'clip') is None
    assert replace_bounds(original, None, 'clip') is None


def test_rescaling_preserves_relative_vowel_geometry_without_labels():
    bounds = replace_bounds({'syllable': [0., 1.], 'vowel': [.5, 1.]}, [1., 1.4], 'rescale')
    assert bounds['vowel'] == pytest.approx([1.2, 1.4])
    with pytest.raises(ValueError, match='Invalid interval'):
        replace_bounds({'syllable': [0., 1.], 'vowel': [.4, 1.1]}, [1., 2.], 'clip')


def test_unavailable_errors_stay_in_denominator_and_cannot_be_scored_as_correct():
    rows = [{'id': 'a', 'expected_label': 'front', 'actual_label': 'back'},
            {'id': 'b', 'expected_label': 'front', 'actual_label': 'front'}]
    result = summarize_denominator(rows, [])
    assert result['selected_errors'] == result['missed_selected_errors'] == 1
    assert result['selected_normal'] == result['unavailable_normal'] == 1
    assert result['unknown_selected_targets'] == 2
    assert result['correct_error_directions'] == 0
    assert result['false_reassurances'] == 0
