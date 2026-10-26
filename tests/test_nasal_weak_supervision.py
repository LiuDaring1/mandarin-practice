from pathlib import Path
import copy
import sys
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from nasal_weak_supervision import audit_weak_rows, fit_weak_ridge, weak_weights
from nasal_feature_probe import fit_ridge, predict_ridge
from nasal_pair_classifier import audit_training


def numerical():
    rng = np.random.default_rng(2)
    return rng.normal(size=(15, 8)), np.array([0]*3+[1]*5+[2]*7), rng.normal(size=(11, 8)), np.array([0]*7+[1]*4)


def rows():
    strong = [{'id': str(i), 'speaker': 'eduhk:1', 'split': 'train', 'audio_sha256': 'a', 'position': i,
               'expected_final': final, 'expected_label': label, 'actual_label': label,
               'label_source': 'unanimous_vowel_scores'}
              for i, (final, label) in enumerate([('an', 'front'), ('ang', 'back'), ('a', 'other')])]
    weak = [{'id': 'weak'+str(i), 'speaker': 'eduhk:1', 'split': 'train', 'audio_sha256': 'a', 'position': i+10,
             'expected_final': final, 'expected_label': label, 'annotation_status': 'no_visible_vowel_annotation',
             'label_status': 'unverified', 'eligible_for_gold_evaluation': False}
            for i, (final, label) in enumerate([('an', 'front'), ('ang', 'back')])]
    return strong, weak


def test_weak_candidates_stay_unverified_and_fail_strong_audit():
    strong, weak = rows(); original = copy.deepcopy(weak)
    assert audit_weak_rows(strong, weak, strong)['actual_labels_assigned'] is False
    assert weak == original
    with pytest.raises((ValueError, KeyError)):
        audit_training(strong+weak)


@pytest.mark.parametrize('field,value', [('split', 'dev'), ('speaker', 'eduhk:new'), ('actual_label', 'front'),
    ('label_source', 'native_score'), ('label_status', 'verified'), ('eligible_for_gold_evaluation', True),
    ('position', 0), ('id', '0'), ('expected_label', 'back'), ('annotation_status', 'marked')])
def test_bad_weak_rows_are_rejected(field, value):
    strong, weak = rows(); weak[0][field] = value
    with pytest.raises(ValueError):
        audit_weak_rows(strong, weak, strong)


def test_speaker_partition_checked_against_all_selected_strong_rows():
    strong, weak = rows()
    heldout = {**strong[0], 'id': 'test', 'split': 'test'}
    with pytest.raises(ValueError, match='Speaker leakage'):
        audit_weak_rows(strong, weak, strong+[heldout])


def test_duplicate_weak_position_is_rejected_even_under_different_id():
    strong, weak = rows(); weak[1]['position'] = weak[0]['position']
    with pytest.raises(ValueError, match='overlapping'):
        audit_weak_rows(strong, weak, strong)


@pytest.mark.parametrize('fraction', [0., .1, .25])
def test_loss_mass_fixed_by_strong_count_not_combined_count(fraction):
    x, y, wx, wy = numerical()
    combined, weights, audit = weak_weights(y, wy, fraction)
    assert weights.sum() == pytest.approx(len(y))
    for label in range(3):
        assert weights[combined==label].sum() == pytest.approx(len(y)/3)
        assert audit['classes'][label]['weak_mass'] == pytest.approx(fraction*len(y)/3 if label<2 else 0)
    assert np.all(weights[len(y):] < weights[:len(y)].max())


def test_zero_weight_has_exact_control_even_if_weak_features_change():
    x, y, wx, wy = numerical(); baseline = fit_ridge(x, y, .1)
    for alternative in (wx, wx*1e20):
        model = fit_weak_ridge(x, y, alternative, wy, 0, .1)
        for key in model:
            np.testing.assert_array_equal(model[key], baseline[key])


def test_weak_duplication_with_same_class_mass_does_not_change_prediction():
    x, y, wx, wy = numerical()
    first = fit_weak_ridge(x, y, wx, wy, .1, .1)
    duplicate = fit_weak_ridge(x, y, np.repeat(wx, 2, axis=0), np.repeat(wy, 2), .1, .1)
    np.testing.assert_allclose(predict_ridge(first, x), predict_ridge(duplicate, x), atol=1e-12)


def test_weak_loss_matches_independent_primal_normal_equations():
    x, y, wx, wy = numerical(); strength = .3
    labels, weights, _ = weak_weights(y, wy, .25)
    model = fit_weak_ridge(x, y, wx, wy, .25, strength)
    z = (np.concatenate((x, wx))-model['mean'])/model['scale']/np.sqrt(x.shape[1])
    target = np.eye(3)[labels]-model['intercept']
    coefficient = np.linalg.solve(z.T@(weights[:, None]*z)+strength*np.eye(x.shape[1]), z.T@(weights[:, None]*target))
    np.testing.assert_allclose(model['coefficient'], coefficient, atol=1e-12)


@pytest.mark.parametrize('fraction', [-.1, .26, float('nan')])
def test_excessive_or_invalid_weak_mass_rejected(fraction):
    _, y, _, wy = numerical()
    with pytest.raises(ValueError, match='Weak fraction'):
        weak_weights(y, wy, fraction)


def test_weak_pseudo_target_must_be_a_nasal_class():
    _, y, _, wy = numerical(); wy[0] = 2
    with pytest.raises(ValueError, match='integer weak'):
        weak_weights(y, wy, .1)


def test_weak_output_root_restored_after_failure():
    import probe_nasal_pairs as engine
    from probe_nasal_weak import FOLDER, experiment_root
    old = engine.FOLDER
    with pytest.raises(RuntimeError):
        with experiment_root():
            assert engine.FOLDER == FOLDER
            raise RuntimeError('test')
    assert engine.FOLDER == old


def test_feature_extraction_keeps_absolute_time_and_trajectory_regions():
    from extract_weak_xeus import trajectory
    # 2 second window starts at 4 seconds; vowel [4.4, 4.8] lies inside it.
    frames = (32000-400)//320+1
    hidden = np.repeat(np.arange(frames)[:, None], 3, axis=1)
    value = trajectory(hidden, {'syllable': [4.2, 4.9], 'vowel': [4.4, 4.8]}, 64000, 96000, 320, 400)
    times = (np.arange(frames)*320+200)/16000
    expected = np.concatenate([hidden[(times>=a) & (times<b)].mean(axis=0) for a,b in [(.4,.6),(.6,.8)]])
    np.testing.assert_array_equal(value, expected)


def test_control_replay_compares_exact_serialized_metadata_not_tuple_list_types():
    from probe_nasal_weak import same_serialized_policy
    live = {'label_order': ('front', 'back', 'other'), 'threshold': .4}
    stored = {'label_order': ['front', 'back', 'other'], 'threshold': .4}
    assert same_serialized_policy(live, stored)
    assert not same_serialized_policy(live, {**stored, 'threshold': .4000000001})
    assert not same_serialized_policy(live, {'label_order': stored['label_order']})
