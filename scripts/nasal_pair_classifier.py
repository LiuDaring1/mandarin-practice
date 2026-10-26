"""Symmetric final-pair conditioning for a research-only acoustic classifier.

Both members of a nasal pair select the SAME head. No expected direction,
API score, source identity or actual label enters prediction. Scores are ridge
outputs, not probabilities. A specialist's third class includes outside-pair
speech as well as nonnasal speech; it must not be read as a nonnasal diagnosis.
"""
from collections import Counter

import numpy as np

from nasal_feature_probe import LABELS, assert_speaker_partition, fit_ridge, predict_ridge


def pair_key(final):
    value = str(final).strip().lower().replace('u:', 'v').replace('ü', 'v')
    value = {'un': 'uen'}.get(value, value)
    if value.endswith('ng'):
        return value[:-1]
    return value if value.endswith('n') else None


def audit_training(rows, minimum_controls=8, minimum_speakers=2):
    """Require trustworthy family labels and count normal training support only."""
    if not rows or any(r['split'] != 'train' for r in rows):
        raise ValueError('Pair fitting requires training rows only')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate training identity')
    if minimum_controls < 1 or minimum_speakers < 1:
        raise ValueError('Invalid support requirements')
    assert_speaker_partition(rows)
    counts = {}; speakers = {}; sources = Counter()
    for row in rows:
        expected, actual = row['expected_label'], row['actual_label']
        if expected not in LABELS or actual not in LABELS:
            raise ValueError('Unknown nasal label')
        key = pair_key(row['expected_final'])
        direction = 'other' if key is None else ('back' if row['expected_final'].strip().lower().endswith('ng') else 'front')
        if expected != direction:
            raise ValueError('Expected final/category mismatch')
        source = row['label_source']
        if expected == actual:
            if source not in ('unanimous_vowel_scores', 'native_score'):
                raise ValueError('Unverified normal family label')
        else:
            if source not in ('explicit_nasal_substitution', 'explicit_nasal_substitution_at_html_highlight') or {expected, actual} != {'front', 'back'}:
                raise ValueError('Actual family is not established by a pure nasal substitution')
            if source == 'explicit_nasal_substitution_at_html_highlight':
                annotation = row.get('annotation', {})
                intended, spoken = annotation.get('expected_plain', ''), annotation.get('actual_plain', '')
                if (not intended or not spoken or intended == spoken or pair_key(intended) != pair_key(spoken)
                        or not intended.endswith(row['expected_final']) or annotation.get('actual_group') != actual
                        or ('back' if spoken.endswith('ng') else 'front') != actual):
                    raise ValueError('Recovered annotation does not establish the same final family')
        sources[source] += 1
        if key is not None:
            counts.setdefault(key, Counter())
            speakers.setdefault(key, {'front': set(), 'back': set()})
            if expected == actual:
                counts[key][actual] += 1
                speakers[key][actual].add(row['speaker'])
    support = {key: {'normal_controls': {label: counts[key][label] for label in ('front', 'back')},
                     'normal_speakers': {label: len(speakers[key][label]) for label in ('front', 'back')}}
               for key in sorted(counts)}
    eligible = [key for key, item in support.items()
                if min(item['normal_controls'].values()) >= minimum_controls
                and min(item['normal_speakers'].values()) >= minimum_speakers]
    return {'eligible_pairs': eligible, 'support': support, 'label_sources': dict(sources),
            'minimum_controls_per_direction': minimum_controls,
            'minimum_speakers_per_direction': minimum_speakers}


def specialist_labels(rows, key):
    # Outside-pair nasal speech is explicitly trained as an abstention class.
    return np.array([LABELS.index(r['actual_label']) if pair_key(r['expected_final']) == key else 2
                     for r in rows], dtype=np.int64)


def fit_heads(features, rows, regularization, support):
    verified = audit_training(rows, support['minimum_controls_per_direction'],
                              support['minimum_speakers_per_direction'])
    if verified != support:
        raise ValueError('Frozen training support changed')
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    heads = {'shared': fit_ridge(features, labels, regularization)}
    for key in support['eligible_pairs']:
        heads[key] = fit_ridge(features, specialist_labels(rows, key), regularization)
    return heads


def predict_heads(heads, features, expected_finals, specialist_weight):
    """Final spelling is used only for its symmetric family; no row labels."""
    if not np.isfinite(specialist_weight) or not 0 <= specialist_weight <= 1:
        raise ValueError('Invalid specialist weight')
    if len(features) != len(expected_finals):
        raise ValueError('Prediction identity count mismatch')
    scores = predict_ridge(heads['shared'], features)
    if specialist_weight == 0:
        return scores
    keys = [pair_key(final) for final in expected_finals]
    for key in sorted(set(keys) - {None}):
        if key not in heads:
            continue  # Explicit shared fallback for unsupported final pairs.
        indices = np.array([i for i, value in enumerate(keys) if value == key])
        specialized = predict_ridge(heads[key], np.asarray(features)[indices])
        scores[indices] = (1-specialist_weight)*scores[indices] + specialist_weight*specialized
    return scores


def pack_heads(heads):
    return {f'{key}__{field}': value for key, head in heads.items() for field, value in head.items()}


def unpack_heads(values):
    heads = {}
    for name, value in values.items():
        key, field = name.split('__', 1)
        heads.setdefault(key, {})[field] = value
    if 'shared' not in heads or any(set(head) != {'mean', 'scale', 'coefficient', 'intercept'} for head in heads.values()):
        raise ValueError('Incomplete classifier bundle')
    return heads
