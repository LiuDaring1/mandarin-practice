"""ZIPA with natural acoustic context and target-local phone evidence.

The output grid is nominal, not a physical phoneme boundary: 10 ms Fbank,
three valid convolutions (stride 1,2,1; receptive field 9 frames). The pinned
export has no further output downsampling: nominal center 45 ms, stride 20 ms.
The frozen ONNX must agree with the documented output-length equation.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_acoustics import greedy_spans, log_softmax, read_audio
from zipa_nasal import BASE, MODIFIERS, VOWELS, ZipaModel, digest

FOLDER = BASE / 'zipa-context-v2'


def context_interval(sample_count, syllable, maximum=20.):
    begin, end = syllable
    duration = sample_count / 16000
    if not np.isfinite([begin, end, maximum]).all() or not 0 <= begin < end <= duration or not 4 < maximum <= 30:
        raise ValueError('Invalid context geometry')
    if end - begin > maximum:
        raise ValueError('Target longer than context limit')
    # Long recordings use a fixed, overlapping grid, not a label-dependent cut.
    # Keep at least two seconds around an interior target where possible.
    if duration <= maximum:
        return 0, sample_count
    start = np.floor(max(0., begin - 2.) / (maximum - 4.)) * (maximum - 4.)
    if end + 2. > start + maximum:
        start = max(0., end + 2. - maximum)
    start = min(start, duration - maximum)
    a = int(np.floor(start * 16000)); b = min(sample_count, a + int(maximum * 16000))
    if not a / 16000 <= begin < end <= b / 16000:
        raise ValueError('Context would clip target')
    return a, b


def target_scores(log_probs, vocabulary, start_seconds, bounds, region, extension_ms, method):
    """Produce three ranking signals; abstention is the 'other' sentinel.

    A peak must beat every competing phone on its own frame. Opposite nasal
    emissions in the same interval are ambiguous. Never select using the
    requested answer. Neither the peak nor its margin is a correctness grade.
    """
    values = np.asarray(log_probs)
    unknown = np.array([0., 0., 1.])
    if values.ndim != 2 or not len(values) or not np.isfinite(values).all():
        raise ValueError('Invalid acoustic matrix')
    if region not in ('syllable', 'vowel') or method not in ('terminal', 'peak') or extension_ms not in (0, 80):
        raise ValueError('Unregistered evidence policy')
    begin, end = bounds[region]
    if not np.isfinite([begin, end, start_seconds]).all() or not 0 <= begin < end:
        raise ValueError('Invalid target interval')
    centers = start_seconds + .045 + np.arange(len(values)) * .02
    mask = (centers >= begin) & (centers < end + extension_ms / 1000)
    if not mask.any():
        return unknown, 'no_target_frames'
    probabilities = np.exp(log_softmax(values))
    spans = greedy_spans(values, vocabulary)
    in_window = [s for s in spans if mask[s['start_frame']:s['end_frame']].any()]
    phones = [s for s in in_window if s['token'] != '▁' and s['token'] not in MODIFIERS]
    if not phones or any(s['token'] in ('<unk>', '<sos/eos>') for s in phones):
        return unknown, 'no_unambiguous_phones'
    nasal = [s for s in phones if s['token'] in ('n', 'ŋ')]
    if len({s['token'] for s in nasal}) != 1:
        return unknown, 'absent_or_conflicting_nasals'
    if method == 'terminal':
        if phones[-1]['token'] not in ('n', 'ŋ'):
            return unknown, 'terminal_phone_not_nasal'
        # A vowel can begin before the API vowel interval, but must occur in
        # this target's syllable neighborhood, not arbitrarily earlier speech.
        terminal_frame = phones[-1]['start_frame']
        if not any(s['token'] in VOWELS and s['end_frame'] <= terminal_frame and
                   centers[s['end_frame']-1] >= bounds['syllable'][0] - .08 for s in spans):
            return unknown, 'no_preceding_target_vowel'
    token = nasal[-1]['token']
    peak = float(probabilities[mask, vocabulary[token]].max())
    if peak <= .5:
        return unknown, 'weak_nasal_emission'
    scores = np.zeros(3); scores[0 if token == 'n' else 1] = peak
    return scores, 'nasal_emission'


class ContextModel(ZipaModel):
    def infer_context(self, samples):
        import torch
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not 1600 <= len(samples) <= 16000*20 or not np.isfinite(samples).all():
            raise ValueError('Context needs finite 0.1–20 second audio')
        key = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode() + b'context-logprobs-v2' + samples.tobytes()).hexdigest()
        folder = FOLDER / 'cache'; folder.mkdir(exist_ok=True)
        path = folder / (key + '.npz')
        if path.exists():
            with np.load(path, allow_pickle=False) as stored:
                return stored['log_probs'], key
        features = self.extractor.extract_batch([torch.from_numpy(samples.copy()).unsqueeze(0)], sampling_rate=16000)[0].unsqueeze(0)
        values, lengths = self.session.run(None, {'x': features.numpy(), 'x_lens': np.array([features.shape[1]], dtype=np.int64)})
        valid = int(lengths[0]); expected = (features.shape[1] - 7) // 2
        if valid != expected or not 0 < valid <= values.shape[1] or values.shape[2] != len(self.vocab) or not np.isfinite(values[0, :valid]).all():
            raise RuntimeError('ONNX output disagrees with verified grid or vocabulary')
        result = values[0, :valid]
        tmp = path.with_suffix('.tmp.npz'); np.savez_compressed(tmp, log_probs=result)
        tmp.chmod(0o600); tmp.replace(path)
        return result, key


def main():
    plan_path = FOLDER / 'plan.json'; plan = json.loads(plan_path.read_text())
    if any(digest(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('Frozen context sources changed')
    output = FOLDER / 'predictions.json'
    if output.exists():
        raise ValueError('Context predictions frozen')
    model = ContextModel(); reports = {}; audio_cache = {}; inference_cache = {}
    for cohort in ('existing', 'griffith'):
        dataset = json.loads((BASE / 'zipa-v1' / f'{cohort}-dataset.json').read_text())
        records = []
        for number, row in enumerate(dataset['rows']):
            path = row['audio']
            if path not in audio_cache:
                if digest(Path(path)) != row['audio_sha256']:
                    raise ValueError('Input audio changed')
                audio_cache[path] = read_audio(Path(path), max_seconds=180)
            try:
                interval = context_interval(len(audio_cache[path]), row['bounds']['syllable'])
                a, b = interval; identity = (path, a, b)
                if identity not in inference_cache:
                    inference_cache[identity] = model.infer_context(audio_cache[path][a:b])
                values, key = inference_cache[identity]
                for policy in plan['policies']:
                    scores, reason = target_scores(values, model.vocab, a/16000, row['bounds'], **policy)
                    records.append({'id': row['id'], 'policy': policy, 'scores': scores.tolist(), 'reason': reason,
                                    'context_samples': interval, 'cache_key': key})
            except ValueError as error:
                for policy in plan['policies']:
                    records.append({'id': row['id'], 'policy': policy, 'unavailable': True, 'reason': str(error)})
            if (number+1) % 40 == 0:
                print(cohort, number+1, 'targets complete', flush=True)
        reports[cohort] = records
    report = {'complete': True, 'plan_sha256': digest(plan_path), 'cohorts': reports,
              'reference_text_input': False, 'model': model.identity,
              'nominal_grid': {'first_center_seconds': .045, 'stride_seconds': .02},
              'inference_windows': len(inference_cache)}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n'); output.chmod(0o600)
    print('CONTEXT INFERENCE COMPLETE', len(inference_cache), flush=True)


if __name__ == '__main__':
    main()
