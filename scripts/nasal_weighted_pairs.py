"""Symmetric vowel-family heads over frozen, training-weighted feature blocks."""
import numpy as np

from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training, pair_key, specialist_labels
from nasal_weighted_fusion import fit_weighted, predict_weighted


def fit_heads(paired, rows, regularization, support, hubert_weight):
    verified = audit_training(rows, support['minimum_controls_per_direction'],
                              support['minimum_speakers_per_direction'])
    if verified != support:
        raise ValueError('Frozen training support changed')
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    heads = {'shared': fit_weighted(paired, labels, regularization, hubert_weight)}
    for key in support['eligible_pairs']:
        heads[key] = fit_weighted(paired, specialist_labels(rows, key), regularization, hubert_weight)
    return heads


def predict_heads(heads, paired, expected_finals, specialist_weight, hubert_weight):
    """Only the symmetric family selects a head; direction is never an input."""
    if not np.isfinite(specialist_weight) or not 0 <= specialist_weight <= 1:
        raise ValueError('Invalid specialist weight')
    if len(paired) != len(expected_finals):
        raise ValueError('Prediction identity count mismatch')
    scores = predict_weighted(heads['shared'], paired, hubert_weight)
    if specialist_weight == 0:
        return scores
    keys = [pair_key(final) for final in expected_finals]
    for key in sorted(set(keys) - {None}):
        if key not in heads:
            continue
        indices = np.array([i for i, value in enumerate(keys) if value == key])
        specialized = predict_weighted(heads[key], np.asarray(paired)[indices], hubert_weight)
        scores[indices] = (1-specialist_weight)*scores[indices] + specialist_weight*specialized
    return scores
