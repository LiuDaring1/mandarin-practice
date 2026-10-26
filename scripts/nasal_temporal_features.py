"""Acoustic time representations without expected text or nasal labels."""
import numpy as np


VIEWS = ('trajectory2', 'resampled4', 'resampled8', 'tail_stats')


def temporal_features(values, times, begin, end, view):
    values = np.asarray(values)
    times = np.asarray(times, dtype=np.float64)
    if (values.ndim != 2 or times.shape != (len(values),) or len(times) < 2
            or not np.isfinite(values).all() or not np.isfinite(times).all()
            or not np.isfinite([begin, end]).all() or not begin < end
            or not np.all(np.diff(times) > 0) or times[0] < begin or times[-1] >= end):
        raise ValueError('Invalid or insufficient observed vowel frames')
    midpoint = (begin + end) / 2

    def mean(left, right):
        selected = values[(times >= left) & (times < right)]
        if not len(selected):
            raise ValueError('Empty temporal feature interval')
        return selected.mean(axis=0)

    if view == 'trajectory2':
        parts = [mean(begin, midpoint), mean(midpoint, end)]
    elif view in ('resampled4', 'resampled8'):
        count = int(view.removeprefix('resampled'))
        # Linear interpolation of observed acoustic frames. Endpoint values
        # repeat beyond the first/last frame; this is not new acoustic evidence.
        queries = begin + (np.arange(count) + .5) / count * (end - begin)
        return np.stack([np.interp(queries, times, channel) for channel in values.T], axis=1).astype(np.float32).reshape(-1)
    elif view == 'tail_stats':
        # Absolute-duration tail windows complement the relative-time view.
        early = mean(begin, min(end, begin + .06))
        late = mean(max(begin, end - .06), end)
        parts = [mean(begin, end), mean(max(begin, end - .12), end), late, late - early]
    else:
        raise ValueError('Unknown temporal representation')
    return np.stack(parts).reshape(-1)
