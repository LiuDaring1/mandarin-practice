from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from nasal_directional_calibration import directional_observations, select_directional_feedback


def fixture_rows():
    rows = []; scores = []
    def add(expected, actual, prediction, confidence):
        rows.append({'id': str(len(rows)), 'speaker': 'dev-only', 'split': 'dev', 'condition': 'synthetic',
                     'expected_label': expected, 'actual_label': actual, 'api_state': 'not_flagged'})
        score = [0., 0., 0.]; score[('front','back','other').index(prediction)] = confidence
        scores.append(score)
    for group in ['front','back']:
        for _ in range(19):add(group, group, group, .99)
    add('front', 'front', 'back', .95)
    add('back', 'back', 'front', .3)
    for _ in range(2):
        add('front', 'back', 'back', .9)
        add('back', 'front', 'front', .8)
    return rows, np.array(scores)


def test_unreliable_direction_does_not_erase_other_direction_or_create_false_claims():
    rows, scores = fixture_rows()
    review, matching, _ = select_directional_feedback(rows, scores)
    assert review['front'] is None and .3 < review['back'] <= .8
    observed = directional_observations(rows, scores, review, matching)
    assert sum(r['candidate_nasal_change'] for r in observed) == 2
    assert all(r['expected'] == 'back' and r['actual'] == 'front' for r in observed if r['candidate_nasal_change'])
    assert not any(r['candidate_nasal_match'] and r['actual'] != r['expected'] for r in observed)


def test_evaluation_rows_never_calibrate_and_unknown_never_passes():
    rows, scores = fixture_rows()
    rows[0]['split'] = 'test'
    with pytest.raises(ValueError):select_directional_feedback(rows, scores)
    result = directional_observations(rows[:1], [[0.,0.,1.]], {'front':0.}, {'front':0.})[0]
    assert not result['candidate_nasal_change'] and not result['candidate_nasal_match']
