"""Explicit weak-target loss; never promote an unmarked position to gold.

Strong labels keep their original audit. Weak expected labels are pseudo targets
only. Each nasal class lends a fixed fraction of its original N_strong/3 mass
to weak samples; other-class mass and total mass stay fixed across experiments.
"""
from collections import Counter
import numpy as np

from nasal_feature_probe import LABELS, assert_speaker_partition, fit_ridge
from nasal_pair_classifier import audit_training

FINALS = frozenset(('an', 'ang', 'en', 'eng', 'ian', 'iang', 'in', 'ing'))


def audit_weak_rows(strong_rows, weak_rows, all_strong_rows):
    audit_training(strong_rows)
    assert_speaker_partition(all_strong_rows + weak_rows)
    train_speakers = {r['speaker'] for r in strong_rows}
    identities = {r['id'] for r in all_strong_rows}
    positions = {(r['audio_sha256'], r['position']) for r in all_strong_rows if 'position' in r}
    seen = set()
    for row in weak_rows:
        if row['split'] != 'train' or row['speaker'] not in train_speakers or not row['speaker'].startswith('eduhk:'):
            raise ValueError('Weak samples require existing training speakers only')
        if ('actual_label' in row or 'label_source' in row or row.get('label_status') != 'unverified'
                or row.get('eligible_for_gold_evaluation') is not False
                or row.get('annotation_status') != 'no_visible_vowel_annotation'):
            raise ValueError('Weak rows must remain explicitly unverified, without actual labels')
        final = row['expected_final']
        if final not in FINALS or row['expected_label'] != ('back' if final.endswith('ng') else 'front'):
            raise ValueError('Invalid expected weak target')
        position = (row['audio_sha256'], row['position'])
        if row['id'] in identities or position in positions or position in seen:
            raise ValueError('Duplicate or overlapping weak identity/position')
        identities.add(row['id']); seen.add(position)
    if not weak_rows or {r['expected_label'] for r in weak_rows} != {'front', 'back'}:
        raise ValueError('Both weak nasal directions required')
    return {'targets': len(weak_rows), 'speakers': len({r['speaker'] for r in weak_rows}),
            'pseudo_target_counts': dict(Counter(r['expected_label'] for r in weak_rows)),
            'actual_labels_assigned': False, 'eligible_for_gold_evaluation': False}


def weak_weights(strong_labels, pseudo_targets, fraction):
    y, weak = np.asarray(strong_labels), np.asarray(pseudo_targets)
    if (y.ndim != 1 or weak.ndim != 1 or y.dtype.kind not in 'iu' or weak.dtype.kind not in 'iu'
            or set(y.tolist()) != {0, 1, 2} or set(weak.tolist()) != {0, 1}):
        raise ValueError('Three strong classes and two integer weak nasal targets required')
    if not np.isfinite(fraction) or not 0 <= fraction <= .25:
        raise ValueError('Weak fraction must be between zero and 0.25')
    strong_weight = len(y)/(3*np.bincount(y)[y])
    strong_weight = strong_weight*np.where(y < 2, 1-fraction, 1.)
    weak_weight = fraction*len(y)/(3*np.bincount(weak)[weak])
    weight = np.concatenate((strong_weight, weak_weight))
    combined = np.concatenate((y, weak))
    audit = {'fraction': fraction, 'strong_targets': len(y), 'weak_targets': len(weak),
        'objective_mass': float(weight.sum()), 'reference_mass': len(y),
        'classes': [{'label': LABELS[label], 'strong_count': int((y==label).sum()),
                     'weak_count': int((weak==label).sum()),
                     'strong_mass': float(strong_weight[y==label].sum()),
                     'weak_mass': float(weak_weight[weak==label].sum())} for label in range(3)]}
    if not np.isclose(weight.sum(), len(y), rtol=1e-12, atol=1e-12):
        raise ValueError('Strong-reference loss mass changed')
    return combined, weight, audit


def fit_weak_ridge(strong_features, strong_labels, weak_features, pseudo_targets, fraction, regularization):
    strong = np.asarray(strong_features, dtype=np.float64)
    weak = np.asarray(weak_features, dtype=np.float64)
    if (strong.ndim != 2 or weak.ndim != 2 or not strong.shape[1] or strong.shape[1] != weak.shape[1]
            or len(strong) != len(strong_labels) or len(weak) != len(pseudo_targets)
            or not np.isfinite(strong).all() or not np.isfinite(weak).all()
            or not np.isfinite(regularization) or regularization <= 0):
        raise ValueError('Invalid weak training features or regularization')
    labels, weights, _ = weak_weights(strong_labels, pseudo_targets, fraction)
    if fraction == 0:
        # Exact old control: zero-weight data cannot change normalization or loss.
        return fit_ridge(strong, strong_labels, regularization)
    x = np.concatenate((strong, weak))
    mean = np.average(x, axis=0, weights=weights)
    scale = np.maximum(np.sqrt(np.average((x-mean)**2, axis=0, weights=weights)), 1e-4)
    z = (x-mean)/scale/np.sqrt(x.shape[1])
    target = np.eye(3)[labels]
    intercept = np.average(target, axis=0, weights=weights)
    root = np.sqrt(weights)[:, None]
    a = z*root
    dual = np.linalg.solve(a@a.T+regularization*np.eye(len(x)), (target-intercept)*root)
    return {'mean': mean, 'scale': scale, 'coefficient': a.T@dual, 'intercept': intercept}
