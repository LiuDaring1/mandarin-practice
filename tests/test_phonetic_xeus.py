import ast
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from phonetic_xeus import lazy_audio_import
from xeus_nasal_evidence import nasal_class, target_evidence


@pytest.mark.parametrize('source', [
    'import torchaudio\ndef unused():\n    return torchaudio.load("a.wav")\n',
    '"""Model docstring."""\nx = 1\nif __name__ == "__main__":\n    import torchaudio\n    y = torchaudio.load("a.wav")\n',
])
def test_optional_audio_patch_preserves_valid_code_and_does_not_import_at_load(source):
    patched = lazy_audio_import(source)
    assert ast.get_docstring(ast.parse(patched)) == ast.get_docstring(ast.parse(source))
    namespace = {'__name__': 'research_test'}
    exec(patched, namespace)
    assert 'torchaudio' not in namespace
    assert '_optional_torchaudio().load' in patched


def test_place_variants_and_unmapped_nasals_remain_distinct():
    assert nasal_class('n̪') == 'front' and nasal_class('ŋː') == 'back'
    for token in ['ɲ', 'ɴ', 'nˠ', 'n̩', 'ŋ̩', 'm', '<unk>']:
        assert nasal_class(token) is None


VOCAB = {'<blank>': 0, 'i': 1, 'n': 2, 'ŋ': 3, 'ɲ': 4, 'nː': 5, '<unk>': 6}


def acoustic(tokens):
    values = np.full((len(tokens), len(VOCAB)), -9.)
    for i, token in enumerate(tokens):
        values[i, VOCAB[token]] = 0.
    return values, .0125 + np.arange(len(tokens))*.02


def evidence(tokens, end=.16, method='terminal'):
    values, centers = acoustic(tokens)
    return target_evidence(values, VOCAB, centers, {'syllable': [0., end], 'vowel': [0., end]}, 'syllable', 0, method)


def test_unknown_or_conflicting_nasals_and_missing_vowel_do_not_pass():
    for tokens in [['i', 'ɲ'], ['i', 'n', 'ŋ'], ['i', '<unk>', 'n'], ['n', '<blank>'], ['i', 'n', 'ɲ']]:
        scores, _ = evidence(tokens)
        assert scores.tolist() == [0., 0., 1.]
    assert evidence(['i', 'n', 'ɲ'], method='peak')[1] == 'unsupported_nasal_realization'


def test_phone_evidence_uses_target_grid_and_does_not_leak_later_nasal():
    scores, reason = evidence(['i', 'nː', '<blank>', 'i', 'ŋ'], end=.06)
    assert scores.argmax() == 0 and reason == 'nasal_emission'
    values, centers = acoustic(['i', 'ŋ'])
    with pytest.raises(ValueError):
        target_evidence(values, VOCAB, centers[::-1], {'syllable': [0., .1]}, 'syllable', 0, 'terminal')
