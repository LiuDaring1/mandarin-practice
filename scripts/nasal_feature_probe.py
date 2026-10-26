"""Label-free acoustic pooling and a small regularized classifier.

No API score, expected syllable, source identity or speaker enters the features.
Ridge outputs and their gaps are not calibrated correctness probabilities.
"""
import numpy as np


LABELS = ('front', 'back', 'other')
LAYERS = (6, 12, 18, 24)
REGIONS = ('syllable', 'vowel', 'first_half', 'last_half')


def acoustic_window(bounds, sample_count):
    """A fixed waveform window containing the complete target, never a cut tail.

    Preserve whole-utterance extraction for <=60 s. Longer utterances use 45 s
    windows every 40 s; choose the containing window with most context. Window
    boundaries do not depend on labels, expected text or predictions.
    """
    if not 1600<=sample_count<=16000*180:
        raise ValueError('Audio outside research duration envelope')
    left,right=bounds['syllable']
    if not 0<=left<right<=sample_count/16000+.01:
        raise ValueError('Invalid target interval')
    if sample_count<=16000*60:
        return 0,sample_count
    candidates=[(start,min(sample_count,start+16000*45))
                for start in range(0,sample_count,16000*40)]
    containing=[(start,end) for start,end in candidates
                if start/16000<=left and right<=end/16000+.01]
    if not containing:
        raise ValueError('No window contains the complete target')
    return max(containing,key=lambda window:(min(left-window[0]/16000,window[1]/16000-right),-window[0]))


def local_context_window(bounds, sample_count, margin_ms, stride=320):
    """Crop context while retaining the parent's convolution frame grid.

    The original parent window still defines waveform normalization. Rounded
    crop edges expand outward; neither the target nor its requested context
    is shortened except at the parent waveform edge. No labels are consulted.
    """
    parent_start, parent_end = acoustic_window(bounds, sample_count)
    if not np.isfinite(margin_ms) or margin_ms < 0 or stride <= 0:
        raise ValueError('Invalid local context margin/grid')
    left, right = bounds['syllable']
    start = parent_start + int(np.floor((left*16000 - margin_ms*16 - parent_start)/stride))*stride
    end = parent_start + int(np.ceil((right*16000 + margin_ms*16 - parent_start)/stride))*stride
    return max(parent_start, start), min(parent_end, end)


def pool_regions(hidden, bounds, *, sample_count, stride=320, receptive_field=400):
    values = np.asarray(hidden)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError('Invalid hidden states')
    count = (sample_count - receptive_field) // stride + 1
    if len(values) != count:
        raise ValueError('Hidden-state time axis mismatch')
    start, end = bounds['syllable']
    begin, stop = bounds['vowel']
    if not 0 <= start <= begin < stop <= end <= sample_count/16000 + .01:
        raise ValueError('Invalid target interval')
    midpoint = (begin+stop)/2
    times = (np.arange(count)*stride + receptive_field/2)/16000
    pooled = []
    for left, right in [(start,end),(begin,stop),(begin,midpoint),(midpoint,stop)]:
        selected = values[(times >= left) & (times < right)]
        if not len(selected):
            raise ValueError('Empty feature interval')
        pooled.append(selected.mean(axis=0))
    return np.stack(pooled)


def feature_view(features, layer_index, view):
    # N x layer x region x width -> N x width (or N x 2*width).
    if view == 'trajectory':
        return features[:,layer_index,2:4,:].reshape(len(features), -1)
    return features[:,layer_index,REGIONS.index(view),:]


def fit_ridge(features, labels, regularization):
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if x.ndim != 2 or len(x) != len(y) or not len(y) or not np.isfinite(x).all():
        raise ValueError('Invalid training data')
    if set(y.tolist()) != set(range(len(LABELS))) or regularization <= 0:
        raise ValueError('Need all classes and positive regularization')
    # Class-balanced weighted centering/standardization uses training rows only.
    counts = np.bincount(y, minlength=len(LABELS))
    weight = len(y)/(len(LABELS)*counts[y])
    mean = np.average(x, axis=0, weights=weight)
    scale = np.maximum(np.sqrt(np.average((x-mean)**2, axis=0, weights=weight)), 1e-4)
    z = (x-mean)/scale/np.sqrt(x.shape[1])
    target = np.eye(len(LABELS))[y]
    intercept = np.average(target, axis=0, weights=weight)
    root = np.sqrt(weight)[:,None]
    a = z*root
    dual = np.linalg.solve(a@a.T + regularization*np.eye(len(x)), (target-intercept)*root)
    coefficient = a.T@dual
    return {'mean':mean, 'scale':scale, 'coefficient':coefficient, 'intercept':intercept}


def predict_ridge(model, features):
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(model['mean']) or not np.isfinite(x).all():
        raise ValueError('Invalid prediction data')
    return ((x-model['mean'])/model['scale']/np.sqrt(x.shape[1]))@model['coefficient']+model['intercept']


def balanced_accuracy(actual, predicted):
    y, p = np.asarray(actual), np.asarray(predicted)
    if not len(y) or len(y) != len(p):
        raise ValueError('No evaluation observations')
    recalls = [float(np.mean(p[y==label] == label)) for label in np.unique(y)]
    return float(np.mean(recalls))


def assert_speaker_partition(rows):
    splits = {}
    for row in rows:
        speaker, split = row['speaker'], row['split']
        if speaker in splits and splits[speaker] != split:
            raise ValueError('Speaker leakage between partitions')
        splits[speaker] = split


def select_on_development(features, rows, regularizations=(.001,.01,.1,1.,10.)):
    """Selection receives train/dev rows ONLY; refusing evaluation partitions."""
    if any(r['split'] not in ('train','dev') for r in rows):
        raise ValueError('Selection cannot receive test or transfer rows')
    assert_speaker_partition(rows)
    training = np.array([r['split']=='train' for r in rows])
    development = np.array([r['split']=='dev' for r in rows])
    if not training.any() or not development.any():
        raise ValueError('Both training and development data required')
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    ranking = []
    for layer_index, layer in enumerate(LAYERS):
        for view in ('syllable','vowel','last_half','trajectory'):
            x = feature_view(features, layer_index, view)
            for strength in regularizations:
                model = fit_ridge(x[training],labels[training],strength)
                predicted = predict_ridge(model,x[development]).argmax(axis=1)
                score = balanced_accuracy(labels[development], predicted)
                ranking.append({'layer':layer,'view':view,'regularization':strength,'dev_balanced_accuracy':score})
    # A deterministic tie break prefers stronger regularization, then earlier
    # layers and simpler region views, without seeing test labels.
    ranking.sort(key=lambda r:(-r['dev_balanced_accuracy'],-r['regularization'],r['layer'],r['view']))
    best = ranking[0]
    x = feature_view(features,LAYERS.index(best['layer']),best['view'])
    model = fit_ridge(x[training],labels[training],best['regularization'])
    return best, model, ranking
