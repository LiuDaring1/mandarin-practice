"""Local ZIPA ONNX probe, based on the authors' documented preprocessing.

https://github.com/lingjzhu/zipa/tree/main/inference
Model weights: anyspeech/zipa-small-crctc-500k, CC BY 4.0. Not a validated
pronunciation assessor. No reference text is given to the acoustic model.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np

from nasal_acoustics import greedy_spans, read_audio


BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE / 'zipa-v1'
MODIFIERS = frozenset('ʰʲʷʼː˞ˠˤ̴̥̩̪̺̃̚')
VOWELS = frozenset('aeiouyæøœɐɑɒɔɘəɛɜɞɤɨɪɯɵɶʉʊʌʏ')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def terminal_nasal(spans):
    if any(s['token'] in ('<unk>', '<sos/eos>') for s in spans):
        return {'group': None, 'confidence': 0., 'reason': 'unknown_or_special_phone'}
    phones = [s for s in spans if s['token'] != '▁' and s['token'] not in MODIFIERS]
    if len(phones) < 2 or not any(s['token'] in VOWELS for s in phones[:-1]):
        return {'group': None, 'confidence': 0., 'reason': 'no_vowel_before_terminal_phone'}
    group = {'n': 'front', 'ŋ': 'back'}.get(phones[-1]['token'])
    return {'group': group, 'confidence': float(phones[-1]['peak_posterior']) if group else 0.,
            'reason': 'terminal_nasal' if group else 'no_terminal_nasal'}


class ZipaModel:
    def __init__(self):
        import onnxruntime as ort
        from lhotse.features.kaldi.extractors import Fbank, FbankConfig
        root = FOLDER / 'model'; manifest = json.loads((root / 'source.json').read_text())
        for item in manifest['files']:
            if digest(root / item['file']) != item['sha256']:
                raise ValueError('ZIPA pinned file changed')
        if importlib.metadata.version('lhotse') != '1.33.0':
            raise ValueError('Unverified Fbank dependency version')
        self.identity = {'model': manifest, 'preprocessing': 'lhotse-1.33.0-fbank80-dither0-snipfalse-pcm16k-v1',
                         'onnxruntime': ort.__version__}
        options = ort.SessionOptions(); options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root / 'model.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
        self.extractor = Fbank(FbankConfig(num_filters=80, dither=0., snip_edges=False))
        self.vocab = {line.rsplit(' ', 1)[0]: int(line.rsplit(' ', 1)[1]) for line in (root / 'tokens.txt').read_text().splitlines()}

    def infer(self, samples):
        import torch
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not 1600 <= len(samples) <= 16000*30 or not np.isfinite(samples).all():
            raise ValueError('ZIPA probe needs finite 0.1–30 second waveform')
        key = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode() + samples.tobytes()).hexdigest()
        cache = FOLDER / 'cache'; cache.mkdir(exist_ok=True); path = cache / (key + '.json')
        if path.exists():
            return json.loads(path.read_text())
        values = self.extractor.extract_batch([torch.from_numpy(samples.copy()).unsqueeze(0)], sampling_rate=16000)[0].unsqueeze(0)
        probabilities, lengths = self.session.run(None, {'x': values.numpy(), 'x_lens': np.array([values.shape[1]], dtype=np.int64)})
        valid = int(lengths[0])
        if not 0 < valid <= probabilities.shape[1] or probabilities.shape[2] != len(self.vocab) or not np.isfinite(probabilities[0, :valid]).all():
            raise ValueError('Invalid ONNX output length/vocabulary')
        spans = greedy_spans(probabilities[0, :valid], self.vocab)
        result = {'cache_key': key, 'spans': spans, 'observation': terminal_nasal(spans),
                  'sample_count': len(samples), 'output_frames': valid, 'reference_text_input': False}
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2)); path.chmod(0o600)
        return result


def main():
    plan_path = FOLDER / 'plan.json'; plan = json.loads(plan_path.read_text())
    if any(digest(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('ZIPA plan source changed')
    output = FOLDER / 'predictions.json'
    if output.exists():
        raise ValueError('ZIPA inference report frozen')
    model = ZipaModel(); results = {}; references = []
    for ref in plan['reference_inputs']:
        if digest(Path(ref['audio'])) != ref['audio_sha256']:
            raise ValueError('Reference control audio changed')
        record = model.infer(read_audio(Path(ref['audio'])))
        references.append({**ref, **record})
    for cohort in ('existing', 'griffith'):
        dataset = json.loads((FOLDER / f'{cohort}-dataset.json').read_text())
        if dataset['plan_sha256'] != digest(plan_path):
            raise ValueError('ZIPA dataset bound to a different plan')
        samples_cache = {}; records = []
        for row in dataset['rows']:
            if row['audio'] not in samples_cache:
                if digest(Path(row['audio'])) != row['audio_sha256']:
                    raise ValueError('ZIPA input audio changed')
                samples_cache[row['audio']] = read_audio(Path(row['audio']), max_seconds=180)
            samples = samples_cache[row['audio']]
            for padding in plan['padding_ms']:
                begin, end = row['bounds']['syllable']
                start = max(0, int(np.floor((begin-padding/1000)*16000)))
                stop = min(len(samples), int(np.ceil((end+padding/1000)*16000)))
                try:
                    result = model.infer(samples[start:stop])
                except ValueError as error:
                    result = {'unavailable': True, 'reason': str(error)}
                records.append({'id': row['id'], 'padding_ms': padding, 'sample_interval': [start, stop], **result})
            if len(records) % 40 == 0:
                print(cohort, len(records), 'conditions done', flush=True)
        results[cohort] = records
    report = {'complete': True, 'plan_sha256': digest(plan_path), 'model': model.identity,
              'dataset_sha256': {name: digest(FOLDER / f'{name}-dataset.json') for name in results},
              'reference_controls': references, 'cohorts': results,
              'limits': ['CTC phone posterior is not probability of correct pronunciation.',
                         'Terminal-phone heuristic may miss noncanonical or partially realized nasal endings.',
                         'Syllable crop depends on API alignment; no independent phonetic boundary claim.']}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)); output.chmod(0o600)
    print('ZIPA INFERENCE COMPLETE', flush=True)


if __name__ == '__main__':
    main()
