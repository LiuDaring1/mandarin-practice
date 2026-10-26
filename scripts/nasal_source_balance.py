"""Training-only source/class balancing; source never enters prediction.

Each class gets N/3 total weight. Within a class, each represented corpus gets
equal mass, regardless of its number of targets. Missing source/class cells
remain missing and are reported; weighting cannot create matched controls.
"""
from collections import Counter

import numpy as np

from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training, specialist_labels


def source_weights(rows, labels):
    if not rows or any(r['split'] != 'train' for r in rows):
        raise ValueError('Source weighting requires training rows only')
    y = np.asarray(labels)
    if y.shape != (len(rows),) or y.dtype.kind not in 'iu' or set(y.tolist()) != {0, 1, 2}:
        raise ValueError('Need three integer training classes')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate training identity')
    sources = []
    for row in rows:
        source, separator, speaker = row['speaker'].partition(':')
        if not separator or not source or not speaker:
            raise ValueError('Missing explicit corpus/speaker identity')
        sources.append(source)
    counts = Counter(zip(y.tolist(), sources))
    domains = {label: {source for target, source in counts if target==label} for label in range(3)}
    weight = np.array([len(rows)/(3*len(domains[int(label)])*counts[(int(label), source)])
                       for label, source in zip(y, sources)], dtype=np.float64)
    cells = []
    for label in range(3):
        for source in sorted(set(sources)):
            mask = (y==label) & (np.asarray(sources)==source)
            cells.append({'class': LABELS[label], 'source': source, 'targets': int(mask.sum()),
                          'total_weight': float(weight[mask].sum())})
    return weight, {'cells': cells, 'missing_cells': [c for c in cells if c['targets']==0],
                    'weight_min': float(weight.min()), 'weight_max': float(weight.max()),
                    'weight_sum': float(weight.sum()),
                    'effective_sample_size': float(weight.sum()**2/(weight@weight))}


def fit_weighted_ridge(features, labels, regularization, weights):
    """Same weighted ridge objective/scaling as the original class-balanced fit."""
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels)
    weight = np.asarray(weights, dtype=np.float64)
    if (x.ndim != 2 or not x.shape[1] or not len(x) or y.shape != (len(x),)
            or weight.shape != (len(x),) or not np.isfinite(x).all()
            or not np.isfinite(weight).all() or (weight<=0).any()):
        raise ValueError('Invalid weighted training data')
    if y.dtype.kind not in 'iu' or set(y.tolist()) != {0, 1, 2} or not np.isfinite(regularization) or regularization<=0:
        raise ValueError('Need three integer classes and positive regularization')
    # Fix the objective scale so the same regularization is comparable.
    if not np.isclose(weight.sum(), len(x), rtol=1e-12, atol=1e-12):
        raise ValueError('Training weights must sum to the target count')
    mean = np.average(x, axis=0, weights=weight)
    scale = np.maximum(np.sqrt(np.average((x-mean)**2, axis=0, weights=weight)), 1e-4)
    z = (x-mean)/scale/np.sqrt(x.shape[1])
    target = np.eye(3)[y]
    intercept = np.average(target, axis=0, weights=weight)
    root = np.sqrt(weight)[:, None]
    a = z*root
    dual = np.linalg.solve(a@a.T+regularization*np.eye(len(x)), (target-intercept)*root)
    return {'mean': mean, 'scale': scale, 'coefficient': a.T@dual, 'intercept': intercept}


def training_labels(rows, support):
    verified = audit_training(rows, support['minimum_controls_per_direction'], support['minimum_speakers_per_direction'])
    if verified != support:
        raise ValueError('Frozen training support changed')
    labels = {'shared': np.array([LABELS.index(r['actual_label']) for r in rows])}
    labels.update({key: specialist_labels(rows, key) for key in support['eligible_pairs']})
    return labels


def fit_source_heads(features, rows, regularization, support):
    return {key: fit_weighted_ridge(features, y, regularization, source_weights(rows, y)[0])
            for key, y in training_labels(rows, support).items()}
