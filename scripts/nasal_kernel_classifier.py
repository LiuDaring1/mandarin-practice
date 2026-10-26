"""Train-only, class-weighted RBF ridge classifier on frozen acoustic features.

The kernel and response are centered using the same training class weights.
Bandwidth is fixed from training distances only. Inference receives features,
not expected pronunciation, corpus identity, API scores or actual labels.
"""
import numpy as np

from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training


def squared_distances(left, right):
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if (a.ndim != 2 or b.ndim != 2 or not a.shape[1] or a.shape[1] != b.shape[1]
            or not np.isfinite(a).all() or not np.isfinite(b).all()):
        raise ValueError('Expected compatible finite feature matrices')
    return np.maximum((a*a).sum(axis=1)[:, None]+(b*b).sum(axis=1)[None, :]-2*a@b.T, 0.)


def fit_kernel(features, rows, regularization, bandwidth_multiplier):
    audit_training(rows)  # Keeps pseudo labels and all non-train partitions out.
    x = np.asarray(features, dtype=np.float64)
    y = np.array([LABELS.index(r['actual_label']) for r in rows])
    if (x.ndim != 2 or not x.shape[1] or len(x) != len(rows) or not np.isfinite(x).all()
            or set(y.tolist()) != {0, 1, 2}):
        raise ValueError('Need finite features aligned with three strong classes')
    if (not np.isfinite([regularization, bandwidth_multiplier]).all()
            or regularization <= 0 or bandwidth_multiplier <= 0):
        raise ValueError('Positive finite ridge strength and bandwidth required')
    weights = len(y)/(3*np.bincount(y)[y]); mass = weights/weights.sum()
    mean = np.average(x, axis=0, weights=weights)
    scale = np.maximum(np.sqrt(np.average((x-mean)**2, axis=0, weights=weights)), 1e-4)
    support = (x-mean)/scale/np.sqrt(x.shape[1])
    distances = squared_distances(support, support)
    off_diagonal = distances[np.triu_indices(len(x), 1)]
    positive = off_diagonal[off_diagonal>0]
    if not len(positive):
        raise ValueError('No positive training distances for kernel bandwidth')
    median = float(np.median(positive))
    gamma = 1/(2*bandwidth_multiplier*median)
    kernel = np.exp(-gamma*distances)
    train_mean = kernel@mass; grand_mean = float(mass@train_mean)
    centered = kernel-train_mean[:, None]-train_mean[None, :]+grand_mean
    target = np.eye(3)[y]; intercept = np.average(target, axis=0, weights=weights)
    root = np.sqrt(weights)
    dual = np.linalg.solve(root[:, None]*centered*root[None, :]+regularization*np.eye(len(x)),
                           root[:, None]*(target-intercept))
    return {'mean': mean, 'scale': scale, 'support': support, 'mass': mass, 'train_mean': train_mean,
            'grand_mean': np.array(grand_mean), 'gamma': np.array(gamma), 'median_training_distance': np.array(median),
            'coefficient': root[:, None]*dual, 'intercept': intercept}


def predict_kernel(model, features):
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(model['mean']) or not np.isfinite(x).all():
        raise ValueError('Invalid kernel prediction features')
    support = np.asarray(model['support'])
    if (support.ndim != 2 or support.shape[1] != x.shape[1] or len(model['mass']) != len(support)
            or np.asarray(model['coefficient']).shape != (len(support), 3)):
        raise ValueError('Invalid kernel support geometry')
    z = (x-model['mean'])/model['scale']/np.sqrt(x.shape[1])
    kernel = np.exp(-model['gamma']*squared_distances(z, support))
    centered = kernel-(kernel@model['mass'])[:, None]-model['train_mean'][None, :]+model['grand_mean']
    return centered@model['coefficient']+model['intercept']
