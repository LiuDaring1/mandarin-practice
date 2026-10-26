from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from nasal_feature_probe import pool_regions
from nasal_temporal_features import temporal_features


def test_two_part_control_exactly_matches_existing_pooling():
    hidden = np.arange(20, dtype=np.float32).reshape(10, 2)
    times = (np.arange(10)*320 + 200)/16000
    bounds = {'syllable': [0., .2], 'vowel': [.04, .16]}
    mask = (times >= .04) & (times < .16)
    expected = pool_regions(hidden, bounds, sample_count=3280)[2:4].reshape(-1)
    np.testing.assert_array_equal(temporal_features(hidden[mask], times[mask], .04, .16, 'trajectory2'), expected)


def test_temporal_order_is_retained_and_interpolation_cannot_overshoot_observed_values():
    values = np.array([[0.], [1.], [2.], [3.]], dtype=np.float32)
    times = np.array([.01, .03, .05, .07])
    forward = temporal_features(values, times, 0, .08, 'resampled8')
    backward = temporal_features(values[::-1], times, 0, .08, 'resampled8')
    np.testing.assert_allclose(forward, backward[::-1])
    assert forward.min() == 0 and forward.max() == 3
    assert np.all(np.diff(forward) >= 0)
    np.testing.assert_array_equal(temporal_features(values, times, 0, .08, 'resampled4'), values[:, 0])


def test_tail_statistics_keep_absolute_time_and_tail_change():
    values = np.arange(10, dtype=np.float32)[:, None]
    times = .01 + np.arange(10)*.02
    np.testing.assert_allclose(temporal_features(values, times, 0, .2, 'tail_stats'), [4.5, 6.5, 8., 7.])


@pytest.mark.parametrize('times,values,begin,end', [
    ([.01], [[1]], 0, .02), ([.01, .01], [[1], [2]], 0, .04),
    ([.01, .05], [[1], [2]], .02, .06), ([.01, .05], [[1], [2]], 0, .05),
    ([.01, .03], [[1], [float('nan')]], 0, .04)])
def test_unobserved_or_invalid_frames_do_not_become_a_prediction(times, values, begin, end):
    with pytest.raises(ValueError, match='Invalid or insufficient'):
        temporal_features(values, times, begin, end, 'resampled8')
