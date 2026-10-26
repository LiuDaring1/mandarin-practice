"""Target-local IPA evidence from Xeus; no expected answer in acoustic rules."""
import numpy as np

from nasal_acoustics import greedy_spans, log_softmax

FRONT = frozenset(('n', 'nː', 'nʲ', 'n̥', 'n̤', 'n̪'))
BACK = frozenset(('ŋ', 'ŋː', 'ŋʲ', 'ŋ̥', 'ŋ̤', 'ŋ̰'))
VOWELS = frozenset('aeiouyæøœɐɑɒɔɘəɛɜɞɤɨɪɯɵɶʉʊʌʏ')
SPECIAL = frozenset(('<unk>', '<sos>', '<eos>'))
IGNORED = frozenset((' ', '<space>', '▁'))


def nasal_class(token):
    return 'front' if token in FRONT else 'back' if token in BACK else None


def target_evidence(logits, vocabulary, centers, bounds, region, extension_ms, method):
    values = np.asarray(logits); centers = np.asarray(centers)
    if (values.ndim != 2 or centers.shape != (len(values),) or not len(values)
            or not np.isfinite(values).all() or not np.isfinite(centers).all()
            or not np.all(np.diff(centers) > 0)):
        raise ValueError('Invalid acoustic time grid')
    if region not in ('syllable', 'vowel') or extension_ms not in (0, 80) or method not in ('terminal', 'peak'):
        raise ValueError('Unregistered evidence policy')
    begin, end = bounds[region]
    if not np.isfinite([begin, end]).all() or not 0 <= begin < end:
        raise ValueError('Invalid target interval')
    unknown = np.array([0., 0., 1.])
    mask = (centers >= begin) & (centers < end + extension_ms/1000)
    if not mask.any():
        return unknown, 'no_target_frames'
    spans = greedy_spans(values, vocabulary)
    phones = [s for s in spans if mask[s['start_frame']:s['end_frame']].any() and s['token'] not in IGNORED]
    if not phones or any(s['token'] in SPECIAL for s in phones):
        return unknown, 'no_unambiguous_phones'
    if any(s['token'].startswith(('n', 'ŋ', 'ɲ', 'ɴ')) and not nasal_class(s['token']) for s in phones):
        return unknown, 'unsupported_nasal_realization'
    nasal = [s for s in phones if nasal_class(s['token'])]
    if len({nasal_class(s['token']) for s in nasal}) != 1:
        return unknown, 'absent_or_conflicting_nasals'
    if method == 'terminal':
        if not nasal_class(phones[-1]['token']):
            return unknown, 'terminal_phone_not_nasal'
        if not any(s['token'] and s['token'][0] in VOWELS and s['end_frame'] <= phones[-1]['start_frame']
                   and centers[s['end_frame']-1] >= bounds['syllable'][0]-.08 for s in spans):
            return unknown, 'no_preceding_target_vowel'
    group = nasal_class(nasal[-1]['token'])
    ids = [vocabulary[t] for t in (FRONT if group == 'front' else BACK) if t in vocabulary]
    # Sum only predefined articulatory variants; a competing phone must still
    # lose on at least one frame. Palatal/uvular/syllabic nasals stay unknown.
    probabilities = np.exp(log_softmax(values))
    peak = float(probabilities[mask][:, ids].sum(axis=1).max())
    if peak <= .5:
        return unknown, 'weak_nasal_emission'
    scores = np.zeros(3); scores[0 if group == 'front' else 1] = peak
    return scores, 'nasal_emission'
