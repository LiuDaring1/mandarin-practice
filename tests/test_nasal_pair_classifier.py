from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from nasal_pair_classifier import (audit_training, fit_heads, pack_heads, pair_key,
                                   predict_heads, specialist_labels, unpack_heads)


def row(uid, final, expected, actual=None, speaker='speaker-a', split='train'):
    actual = expected if actual is None else actual
    return {'id': uid, 'expected_final': final, 'expected_label': expected, 'actual_label': actual,
            'speaker': speaker, 'split': split,
            'label_source': 'unanimous_vowel_scores' if actual==expected else 'explicit_nasal_substitution'}


def training():
    return [row('a', 'an', 'front'), row('b', 'ang', 'back'),
            row('c', 'an', 'front', speaker='speaker-b'), row('d', 'ang', 'back', speaker='speaker-b'),
            row('e', 'in', 'front'), row('f', 'a', 'other'), row('g', 'an', 'front', 'back')]


def constant(values):
    return {'mean': np.zeros(2), 'scale': np.ones(2), 'coefficient': np.zeros((2, 3)),
            'intercept': np.array(values, dtype=float)}


@pytest.mark.parametrize('left,right', [('an', 'ang'), ('en', 'eng'), ('in', 'ing'), ('ian', 'iang'),
                                        ('uan', 'uang'), ('un', 'ueng')])
def test_opposite_nasal_uses_identical_head_and_scores(left, right):
    key = pair_key(left)
    assert key==pair_key(right)
    heads = {'shared': constant([0., 1., 0.]), key: constant([1., 0., 0.])}
    for weight in (0., .5, 1.):
        scores = predict_heads(heads, np.ones((2, 2)), [left, right], weight)
        np.testing.assert_array_equal(scores[0], scores[1])


def test_sparse_pair_and_nonnasal_use_shared_without_expected_direction_prior():
    heads = {'shared': constant([.2, .3, .5]), 'an': constant([1, 0, 0])}
    scores = predict_heads(heads, np.zeros((4, 2)), ['an', 'ang', 'uang', 'a'], 1.)
    assert scores.tolist()==[[1, 0, 0], [1, 0, 0], [.2, .3, .5], [.2, .3, .5]]


def test_eligibility_uses_normal_controls_and_distinct_training_speakers():
    support = audit_training(training(), 2, 2)
    assert support['eligible_pairs']==['an']
    assert support['support']['an']['normal_controls']=={'front': 2, 'back': 2}
    assert audit_training(training(), 3, 2)['eligible_pairs']==[]
    one_speaker = [{**r, 'speaker': 'same'} for r in training()]
    assert audit_training(one_speaker, 2, 2)['eligible_pairs']==[]


def test_outside_family_speech_is_other_not_an_automatic_nasal_positive():
    rows = training()
    assert specialist_labels(rows, 'an').tolist()==[0, 1, 0, 1, 2, 2, 1]


@pytest.mark.parametrize('change,message', [({'split': 'dev'}, 'training rows only'),
    ({'split': 'test'}, 'training rows only'), ({'label_source': 'unmarked'}, 'Unverified normal'),
    ({'expected_final': 'ang'}, 'category mismatch')])
def test_unverified_labels_and_evaluation_rows_cannot_enter_fitting(change, message):
    rows = training(); rows[0] = {**rows[0], **change}
    with pytest.raises(ValueError, match=message):
        audit_training(rows, 2, 2)


def test_compound_errors_cannot_infer_actual_family_from_reference():
    rows = training(); rows[-1]['label_source'] = 'compound_substitution'
    with pytest.raises(ValueError, match='pure nasal substitution'):
        audit_training(rows, 2, 2)


def test_recovered_annotation_requires_same_syllable_except_nasal_tail():
    rows = training()
    rows[-1].update(label_source='explicit_nasal_substitution_at_html_highlight',
                    annotation={'expected_plain': 'fan', 'actual_plain': 'fang', 'actual_group': 'back'})
    assert audit_training(rows, 2, 2)['eligible_pairs']==['an']
    rows[-1]['annotation']['actual_plain'] = 'feng'
    with pytest.raises(ValueError, match='same final family'):
        audit_training(rows, 2, 2)


def test_frozen_support_and_model_round_trip():
    rows = training(); x = np.random.default_rng(9).normal(size=(len(rows), 2))
    support = audit_training(rows, 2, 2)
    heads = fit_heads(x, rows, .1, support)
    restored = unpack_heads(pack_heads(heads))
    finals = [r['expected_final'] for r in rows]
    np.testing.assert_array_equal(predict_heads(heads, x, finals, .5), predict_heads(restored, x, finals, .5))
    with pytest.raises(ValueError, match='support changed'):
        fit_heads(x, rows, .1, {**support, 'eligible_pairs': []})


def test_prediction_rejects_invalid_blend_and_identity_count():
    heads = {'shared': constant([0, 1, 0])}
    for weight in (-.1, 1.1, np.nan):
        with pytest.raises(ValueError, match='weight'):
            predict_heads(heads, [[0, 0]], ['an'], weight)
    with pytest.raises(ValueError, match='identity count'):
        predict_heads(heads, [[0, 0]], [], .5)


def test_excluded_targets_without_final_remain_in_pair_denominator():
    from probe_nasal_pairs import summarize_pairs
    unavailable = row('unavailable', 'in', 'front', 'back', split='test')
    del unavailable['expected_final']
    summary = summarize_pairs({'rows': [], 'excluded': [unavailable]}, [], ['in'])
    assert summary['unavailable_final']['selected_targets']==1
    assert summary['unavailable_final']['unavailable_errors']==1
    assert summary['unavailable_final']['route']=='unknown'
