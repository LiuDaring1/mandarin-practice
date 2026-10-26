from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from nasal_source_balance import source_weights, fit_weighted_ridge
from nasal_feature_probe import fit_ridge, predict_ridge


def example():
    labels = np.array([0]*5+[1]*5+[2]*6)
    sources = ['a']*4+['b']+['a']*2+['b']*3+['a']*6
    rows = [{'id': str(i), 'split': 'train', 'speaker': source+':speaker'} for i, source in enumerate(sources)]
    return rows, labels


def test_available_sources_receive_equal_mass_within_each_class():
    rows, y = example(); weights, audit = source_weights(rows, y)
    assert weights.sum()==pytest.approx(len(rows))
    for label in range(3):
        assert weights[y==label].sum()==pytest.approx(len(rows)/3)
    for label in ('front', 'back'):
        cells = [c for c in audit['cells'] if c['class']==label]
        assert cells[0]['total_weight']==pytest.approx(cells[1]['total_weight'])
    assert audit['missing_cells']==[{'class': 'other', 'source': 'b', 'targets': 0, 'total_weight': 0.}]


def test_reordering_preserves_identity_weights_and_training_prediction():
    rows, y = example(); x = np.random.default_rng(3).normal(size=(len(rows), 5))
    weights, _ = source_weights(rows, y)
    order = np.random.default_rng(4).permutation(len(rows))
    reordered, _ = source_weights([rows[i] for i in order], y[order])
    np.testing.assert_array_equal(weights[order], reordered)
    first = fit_weighted_ridge(x, y, .1, weights)
    second = fit_weighted_ridge(x[order], y[order], .1, reordered)
    np.testing.assert_allclose(predict_ridge(first, x), predict_ridge(second, x), atol=1e-12)


def test_class_balanced_weights_reproduce_original_ridge_exactly():
    rows, y = example(); x = np.random.default_rng(5).normal(size=(len(rows), 6))
    for row in rows: row['speaker']='one:recordist'
    weights, _ = source_weights(rows, y)
    baseline = fit_ridge(x, y, .1)
    model = fit_weighted_ridge(x, y, .1, weights)
    for key in baseline: np.testing.assert_array_equal(baseline[key], model[key])


@pytest.mark.parametrize('split', ['dev', 'test', 'transfer', 'holdout'])
def test_source_weighting_cannot_use_evaluation_rows(split):
    rows, y = example(); rows[0]['split']=split
    with pytest.raises(ValueError, match='training rows only'): source_weights(rows, y)


def test_speaker_identity_is_not_silently_treated_as_corpus_identity():
    rows, y = example(); rows[0]['speaker']='unqualified-speaker'
    with pytest.raises(ValueError, match='corpus/speaker'): source_weights(rows, y)


@pytest.mark.parametrize('bad', [np.nan, 0., -1.])
def test_invalid_weights_cannot_enter_normalization(bad):
    rows, y = example(); weights, _ = source_weights(rows, y); weights[0]=bad
    with pytest.raises(ValueError, match='weighted training'): fit_weighted_ridge(np.ones((len(rows), 2)), y, .1, weights)


def test_weight_scale_is_fixed_for_regularization_comparison():
    rows, y = example(); weights, _ = source_weights(rows, y)
    with pytest.raises(ValueError, match='sum to the target count'):
        fit_weighted_ridge(np.ones((len(rows), 2)), y, .1, weights*2)


def test_reused_experiment_root_restores_even_after_failure():
    import probe_nasal_pairs as engine
    from probe_nasal_source_balance import FOLDER, experiment_root
    prior = engine.FOLDER
    with pytest.raises(RuntimeError):
        with experiment_root():
            assert engine.FOLDER==FOLDER
            raise RuntimeError('intentional')
    assert engine.FOLDER==prior
