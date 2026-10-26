from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from zipa_context import context_interval, target_scores

VOCAB = {'<blk>': 0, 'i': 1, 'n': 2, 'ŋ': 3, 'k': 4, '▁': 5}


def logits(tokens):
    values = np.full((len(tokens), len(VOCAB)), -9.)
    for i, t in enumerate(tokens):
        values[i, VOCAB[t]] = 0.
    return values


def test_context_keeps_short_utterance_and_does_not_clip_long_targets():
    assert context_interval(16000, [.2, .8]) == (0, 16000)
    for bounds in ([.1, .5], [19.8, 20.2], [31.8, 32.2], [59., 59.8]):
        a, b = context_interval(60*16000, bounds)
        assert a/16000 <= bounds[0] < bounds[1] <= b/16000
        assert b-a <= 20*16000
    with pytest.raises(ValueError):
        context_interval(16000, [.9, 1.1])


def test_nominal_grid_and_local_phone_only():
    values = logits(['i', 'n', '<blk>', 'i', 'ŋ', '<blk>'])
    # First syllable is front; the later back nasal cannot leak into its window.
    bounds = {'syllable': [0., .10], 'vowel': [.04, .10]}
    scores, reason = target_scores(values, VOCAB, 0., bounds, 'vowel', 0, 'terminal')
    assert scores.argmax() == 0 and reason == 'nasal_emission'
    second = {'syllable': [.10, .16], 'vowel': [.10, .16]}
    scores, _ = target_scores(values, VOCAB, 0., second, 'vowel', 0, 'terminal')
    assert scores.argmax() == 1


@pytest.mark.parametrize('tokens', [ ['i', 'k', '<blk>'], ['n', '<blk>', '<blk>'], ['i', 'n', 'ŋ'] ])
def test_missing_vowel_or_nasal_and_conflicting_tail_abstain(tokens):
    scores, _ = target_scores(logits(tokens), VOCAB, 0., {'syllable': [0., .2], 'vowel': [0., .2]}, 'vowel', 0, 'terminal')
    assert scores.tolist() == [0., 0., 1.]


def test_no_frames_and_weak_nasal_are_not_correctness_evidence():
    bounds = {'syllable': [1., 1.2], 'vowel': [1., 1.2]}
    assert target_scores(logits(['i', 'n']), VOCAB, 0., bounds, 'vowel', 0, 'peak')[1] == 'no_target_frames'
    values = np.zeros((3, len(VOCAB))); values[1, VOCAB['n']] = .01
    bounds = {'syllable': [0., .2], 'vowel': [0., .2]}
    assert target_scores(values, VOCAB, 0., bounds, 'vowel', 0, 'peak')[1] == 'weak_nasal_emission'
