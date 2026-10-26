"""Offline analysis of cached API intervals and cached acoustic logits."""
import argparse
import json
from pathlib import Path
import wave

import numpy as np

from nasal_acoustics import MODELS
from nasal_window import convolution_geometry, window_observation
from suntone_probe import private_json


def main(args):
    base = Path('data/derived/nasal-acoustic-validation')
    inputs = json.loads(Path(args.input).read_text())
    results = json.loads(Path(args.results).read_text())
    if results.get('complete') is not True:
        raise ValueError('Incomplete API batch')
    cases = {r['id']: r for r in inputs['cases']}
    keys = {r['id']: r['cache_key'] for r in inputs['cases'] if 'cache_key' in r}
    for name in ['eduhk', 'eduhk-native']:
        report = json.loads((base / name / 'final-report.json').read_text())
        for row in report['rows']:
            identity = f"{name}-s{row['speaker']}-t{row['task']}-w{row['word_index']}-p{row['target_position']}"
            keys[identity] = row['cache_key']
    spec = MODELS['final']
    model = Path.home() / '.cache/huggingface/hub' / ('models--' + spec['repo'].replace('/', '--')) / 'snapshots' / spec['revision']
    vocab = json.loads((model / spec['vocab']).read_text())
    config = json.loads((model / 'config.json').read_text())['wav2vec2_config']
    field, stride = convolution_geometry(config['conv_kernel'], config['conv_stride'])
    rows = []
    for row in results['cases']:
        case = cases[row['id']]
        with wave.open(case['audio'], 'rb') as audio:
            if audio.getframerate() != 16000:
                raise ValueError('Unexpected audio rate')
            sample_count = audio.getnframes()
        with np.load(base / 'logits' / (keys[row['id']] + '.npz'), allow_pickle=False) as cached:
            logits = cached['logits']
        observations = {}
        for padding in [0.0, 0.04, 0.08]:
            observations[str(padding)] = window_observation(logits, vocab, row['ise_observation'],
                row['local']['final'], sample_count=sample_count, padding_seconds=padding,
                receptive_field=field, stride=stride)
        for padding in [0.0, 0.04]:
            observations['syllable_' + str(padding)] = window_observation(logits, vocab, row['ise_observation'],
                row['local']['final'], sample_count=sample_count, padding_seconds=padding,
                receptive_field=field, stride=stride, interval_kind='syllable')
        rows.append({**row, 'windows': observations})
    private_json(Path(args.output), {'complete': True, 'source_results': args.results,
                                    'model': spec, 'cases': rows})
    print('COMPLETE', len(rows), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--results', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
