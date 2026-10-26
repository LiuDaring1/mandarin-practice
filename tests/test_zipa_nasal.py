from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from zipa_nasal import terminal_nasal
from probe_zipa_feedback import confidence_scores
from train_nasal_feature_probe import observe


def spans(*phones):
    return [{'token': p, 'peak_posterior': .8} for p in phones]


def test_terminal_nasal_requires_vowel_and_respects_last_real_phone():
    assert terminal_nasal(spans('▁', 's', 'i', 'n'))['group'] == 'front'
    assert terminal_nasal(spans('ɕ', 'i', 'ŋ', 'ː', '▁'))['group'] == 'back'
    assert terminal_nasal(spans('n', 'i'))['group'] is None
    assert terminal_nasal(spans('n'))['group'] is None
    assert terminal_nasal(spans('i', 'n', 'k'))['group'] is None
    assert terminal_nasal(spans('i', '<unk>', 'n'))['group'] is None


def test_missing_terminal_and_unavailable_outputs_never_generate_nasal_feedback():
    rows = [{'id': 'one', 'speaker': 'one', 'condition': 'test', 'expected_label': 'front', 'actual_label': 'back'}]
    for record in [{'unavailable': True}, {'observation': {'group': None, 'confidence': 0}},
                   {'observation': {'group': 'front', 'confidence': float('nan')}}]:
        result = observe(rows, np.array([confidence_scores(record)]), 0., 0.)[0]
        assert not result['candidate_nasal_change'] and not result['candidate_nasal_match']
