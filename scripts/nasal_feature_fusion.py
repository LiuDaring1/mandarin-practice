"""Identity-safe acoustic feature fusion and label-free evidence gating."""
import numpy as np


def align_features(left_rows, left, right_rows, right):
    """Pair by target identity, checking labels and acoustic bounds before joining."""
    a, b = np.asarray(left), np.asarray(right)
    if a.ndim != 2 or b.ndim != 2 or len(a) != len(left_rows) or len(b) != len(right_rows):
        raise ValueError('Feature matrix does not match target rows')
    left_ids = [r['id'] for r in left_rows]
    lookup = {r['id']: i for i, r in enumerate(right_rows)}
    if len(set(left_ids)) != len(left_ids) or len(lookup) != len(right_rows) or set(left_ids) != set(lookup):
        raise ValueError('Duplicate or missing fusion target identity')
    order = []
    for row in left_rows:
        index = lookup[row['id']]
        other = right_rows[index]
        for key in ('speaker', 'split', 'expected_label', 'actual_label', 'audio_sha256', 'bounds'):
            if row[key] != other[key]:
                raise ValueError('Fusion target metadata conflict: '+key)
        order.append(index)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Non-finite fusion input')
    return np.stack([a, b[order]], axis=1)


def feature_source(paired, source):
    x = np.asarray(paired)
    if x.ndim != 3 or x.shape[1] != 2 or not np.isfinite(x).all():
        raise ValueError('Expected paired finite feature vectors')
    if source == 'local_phoneme':
        return x[:, 0]
    if source == 'xeus':
        return x[:, 1]
    if source == 'concatenated':
        return x.reshape(len(x), -1)
    raise ValueError('Unregistered fusion source')


def gate_scores(scores, present):
    values = np.asarray(scores, dtype=float)
    accept = np.asarray(present)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError('Invalid head score matrix')
    if accept.dtype != np.bool_ or accept.shape != (len(values),):
        raise ValueError('Evidence presence must be a per-target boolean')
    result = values.copy()
    result[~accept] = [0., 0., 1.]
    return result
