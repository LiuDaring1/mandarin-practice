"""Compare all finals in an independently located vowel interval.

Research only: likelihood margins are not calibrated student scores. ISE
beg_pos/end_pos are 10 ms frames (official ISE FAQ). Wav2Vec2 frames use the
pinned encoder's convolution stride/receptive field, not the API frame unit.
"""
import math

import numpy as np

from nasal_acoustics import ctc_log_probability, greedy_spans, log_softmax


def convolution_geometry(kernels, strides):
    if len(kernels) != len(strides) or not kernels:
        raise ValueError('Invalid convolution geometry')
    width, jump = 1, 1
    for kernel, stride in zip(kernels, strides):
        if not isinstance(kernel, int) or not isinstance(stride, int) or min(kernel, stride) <= 0:
            raise ValueError('Invalid convolution geometry')
        width += (kernel - 1) * jump
        jump *= stride
    return width, jump


def window_observation(logits, vocabulary, observation, expected, *, sample_count,
                       padding_seconds=0.04, receptive_field=400, stride=320,
                       interval_kind='vowel'):
    """Keep invalid/missing/omitted intervals unknown; include all rival finals.

    The whole-waveform model output is reused: expected text never enters the
    encoder. Padding is reported so sensitivity can be measured independently.
    """
    if observation.get('state') not in ('flagged', 'not_flagged'):
        return {'state': 'unknown', 'reason': 'unusable_provider_alignment'}
    nodes = observation.get('finals', [])
    if len(nodes) != 1:
        return {'state': 'unknown', 'reason': 'ambiguous_interval'}
    if interval_kind not in ('vowel', 'syllable'):
        raise ValueError('Unknown interval kind')
    prefix = 'syll_' if interval_kind == 'syllable' else ''
    try:
        begin = int(nodes[0][prefix + 'beg_pos']) / 100
        end = int(nodes[0][prefix + 'end_pos']) / 100
    except (KeyError, ValueError, TypeError):
        return {'state': 'unknown', 'reason': 'missing_interval'}
    duration = sample_count / 16000
    if not 0 <= begin < end <= duration + 0.01:
        return {'state': 'unknown', 'reason': 'invalid_interval'}
    values = np.asarray(logits)
    count = (sample_count - receptive_field) // stride + 1
    if values.ndim != 2 or len(values) != count or not np.isfinite(values).all():
        return {'state': 'unknown', 'reason': 'incompatible_model_timing'}
    if padding_seconds < 0 or not math.isfinite(padding_seconds):
        raise ValueError('Invalid padding')
    if expected.endswith('ng'):
        opposite = expected[:-1]
    elif expected.endswith('n'):
        opposite = expected + 'g'
    else:
        return {'state': 'unknown', 'reason': 'not_nasal'}
    if expected not in vocabulary or opposite not in vocabulary:
        return {'state': 'unknown', 'reason': 'unsupported_pair'}
    centers = (np.arange(count) * stride + receptive_field / 2) / 16000
    indices = np.flatnonzero((centers >= begin - padding_seconds) & (centers < end + padding_seconds))
    if len(indices) < 2:
        return {'state': 'unknown', 'reason': 'short_interval'}
    window = values[indices]
    probs = log_softmax(window)
    scores = {token: ctc_log_probability(probs, [index])
              for token, index in vocabulary.items() if index != 0}
    scores['<omitted>'] = ctc_log_probability(probs, [])
    ranking = sorted(scores, key=scores.get, reverse=True)
    decoded = [s['token'] for s in greedy_spans(window, vocabulary)]
    return {'state': 'observed', 'expected': expected, 'opposite': opposite,
            'interval_kind': interval_kind,
            'interval_seconds': [begin, end], 'padding_seconds': padding_seconds,
            'frame_range': [int(indices[0]), int(indices[-1]) + 1],
            'best_token': ranking[0], 'runner_up': ranking[1],
            'best_minus_runner_up': scores[ranking[0]] - scores[ranking[1]],
            'expected_minus_opposite': scores[expected] - scores[opposite],
            'decoded_tokens': decoded, 'scores': scores}
