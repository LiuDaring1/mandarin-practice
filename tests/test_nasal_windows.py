from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from nasal_window import convolution_geometry, window_observation


VOCAB = {'<blank>': 0, 'an': 1, 'ang': 2, 'a': 3}


def observe(logits, begin='0', end='20', state='flagged', **extra):
    return window_observation(logits, VOCAB,
        {'state': state, 'finals': [{'beg_pos': begin, 'end_pos': end}]},
        'an', sample_count=(len(logits)-1)*320+400, padding_seconds=0, **extra)


def test_geometry_and_provider_units_select_correct_position():
    assert convolution_geometry([10,3,3,3,3,2,2], [5,2,2,2,2,2,2]) == (400,320)
    logits = np.full((10,4), -5.)
    logits[:,0] = 5
    logits[1,1] = 15  # an at 32.5 ms, outside requested 100–180 ms
    logits[6,2] = 15  # ang at 132.5 ms, inside
    result = observe(logits, '10', '18')
    assert result['frame_range'] == [5,9]
    assert result['best_token'] == 'ang'
    assert result['decoded_tokens'] == ['ang']


def test_non_nasal_competitor_is_not_forced_into_binary_nasal_choice():
    logits = np.full((10,4), -5.)
    logits[:,0] = 5
    logits[5,3] = 15
    result = observe(logits)
    assert result['best_token'] == 'a'
    assert result['decoded_tokens'] == ['a']


def test_silence_is_omission_not_correctness():
    logits = np.full((10,4), -10.)
    logits[:,0] = 10
    assert observe(logits)['best_token'] == '<omitted>'


@pytest.mark.parametrize('begin,end,state', [('10','10','flagged'), ('-1','10','flagged'),
    ('0','999','flagged'), ('bad','10','flagged'), ('0','20','rejected'), ('0','20','unusable_alignment')])
def test_unusable_timing_stays_unknown(begin, end, state):
    assert observe(np.zeros((10,4)), begin, end, state)['state'] == 'unknown'


def test_mismatched_model_timing_cannot_map_to_neighbor():
    result = observe(np.zeros((10,4)), stride=160)
    assert result == {'state': 'unknown', 'reason': 'incompatible_model_timing'}
