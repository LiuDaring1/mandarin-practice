from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from calibrate_nasal_exact_margin import select_exact_feedback


def row(expected, actual, split='dev'):
    return {'id': 'fixture', 'speaker': 'fixture', 'condition': 'fixture', 'split': split,
            'expected_label': expected, 'actual_label': actual, 'api_state': 'not_flagged'}


def test_exact_boundary_retains_two_error_directions_between_coarse_grid_points():
    rows = [row('front', 'front'), row('front', 'back'), row('back', 'front'), row('back', 'front')]
    scores = np.array([[0, .8, 0], [0, .9, 0], [.85, 0, 0], [1.2, 0, 0]])
    review, _, _, _ = select_exact_feedback(rows, scores)
    assert .8 < review['margin'] < .85
    assert review['false_nasal_accusations'] == 0
    assert review['correct_error_directions'] == 3
    assert review['directions_by_expected'] == {'front': 1, 'back': 2}


def test_exact_calibration_refuses_test_labels_and_nonfinite_scores():
    for split in ('test', 'external', 'train', 'holdout'):
        with pytest.raises(ValueError, match='development rows only'):
            select_exact_feedback([row('front', 'back', split)], [[0, 1, 0]])
    with pytest.raises(ValueError, match='Invalid development scores'):
        select_exact_feedback([row('front', 'back')], [[0, float('nan'), 0]])
