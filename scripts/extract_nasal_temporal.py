"""Cache local vowel-frame trajectories from the pinned frozen encoder.

Same normalization, crop, frame grid and layer as the v8 baseline. Reference
text and labels never enter inference. Existing baseline features are checked
on every available target, before any new classifier is fitted.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import wave

import numpy as np

from nasal_acoustics import AcousticModel, read_audio
from nasal_feature_probe import LAYERS, acoustic_window, local_context_window, pool_regions
from nasal_temporal_features import VIEWS, temporal_features
from nasal_window import convolution_geometry


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(args):
    import torch
    folder = Path(args.directory)
    dataset = json.loads((folder / 'dataset.json').read_text())
    plan_path = folder.parent / 'plan.json'; plan = json.loads(plan_path.read_text())
    if dataset['temporal_plan_sha256'] != digest(plan_path):
        raise ValueError('Prepared dataset belongs to a different plan')
    for name, expected in plan['sources'].items():
        if digest(Path(name)) != expected:
            raise ValueError('Frozen source or implementation changed')
    baseline_folder = Path(dataset['baseline_folder'])
    baseline_index = json.loads((baseline_folder / 'feature-index.json').read_text())
    baseline = {r['id']: r for r in baseline_index['rows']}
    model = AcousticModel('phoneme'); encoder = model.model.wav2vec2
    if model.spec != plan['encoder'] or model.spec != baseline_index['model']:
        raise ValueError('Pinned encoder mismatch')
    field, stride = convolution_geometry(encoder.config.conv_kernel, encoder.config.conv_stride)
    cache = folder / 'features'; cache.mkdir(exist_ok=True)
    groups = defaultdict(list)
    for row in dataset['rows']:
        groups[row['audio']].append(row)
    output = []; exclusions = []; replay_count = 0; replay_max = 0.
    for audio, rows in groups.items():
        audio_sha = digest(Path(audio))
        if any(r['audio_sha256'] != audio_sha for r in rows):
            raise ValueError('Audio changed after source freeze')
        identity = {'audio_sha256': audio_sha, 'model': model.spec,
            'layer': plan['layer'], 'context_ms': plan['context_ms'],
            'targets': [(r['id'], r['bounds']) for r in rows], 'views': VIEWS,
            'preprocessing': 'parent-normalization-local-grid-vowel-time-v1'}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        path = cache / (key + '.npz'); meta_path = cache / (key + '.json')
        if not path.exists() or not meta_path.exists():
            with wave.open(audio, 'rb') as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                    raise ValueError('Expected PCM16 mono 16 kHz source')
                count = wav.getnframes()
            samples = read_audio(Path(audio), max_seconds=180)
            chunks = defaultdict(list)
            for row in rows:
                parent = acoustic_window(row['bounds'], count)
                window = local_context_window(row['bounds'], count, plan['context_ms'], stride)
                chunks[(parent, window)].append(row)
            normalized = {}; valid = []; vectors = {v: [] for v in VIEWS}
            rejected = []; replayed = 0; maximum = 0.
            for (parent, (start, end)), selected in chunks.items():
                if parent not in normalized:
                    normalized[parent] = model.extractor(samples[parent[0]:parent[1]], sampling_rate=16000, return_tensors='pt')
                inputs = {k: v[:, start-parent[0]:end-parent[0]].to('mps') for k, v in normalized[parent].items()}
                with torch.inference_mode():
                    states = encoder(**inputs, output_hidden_states=True).hidden_states
                    hidden = states[plan['layer']][0].float().cpu().numpy()
                times = (np.arange(len(hidden))*stride + field/2)/16000
                for row in selected:
                    bounds = {k: [t-start/16000 for t in interval] for k, interval in row['bounds'].items()}
                    try:
                        pooled = pool_regions(hidden, bounds, sample_count=end-start, stride=stride, receptive_field=field)
                        begin, stop = bounds['vowel']; mask = (times >= begin) & (times < stop)
                        views = {v: temporal_features(hidden[mask], times[mask], begin, stop, v) for v in VIEWS}
                    except ValueError as error:
                        rejected.append({'id': row['id'], 'reason': str(error)})
                        continue
                    if row['id'] not in baseline:
                        raise ValueError('Temporal row lacks baseline replay')
                    reference = baseline[row['id']]
                    with np.load(reference['cache'], allow_pickle=False) as stored:
                        if str(stored['ids'][reference['index']]) != row['id']:
                            raise ValueError('Baseline cache/label mismatch')
                        original = stored['features'][reference['index'], LAYERS.index(plan['layer']), 2:4].reshape(-1)
                    difference = float(np.max(np.abs(original-views['trajectory2'])))
                    if not np.array_equal(pooled[2:4].reshape(-1), views['trajectory2']) or difference > 1e-6:
                        raise ValueError('Temporal baseline differs from frozen v8 extraction')
                    maximum = max(maximum, difference); replayed += 1; valid.append(row['id'])
                    for view in VIEWS:
                        vectors[view].append(views[view])
                del states, hidden, inputs
                torch.mps.empty_cache()
            arrays = {v: np.stack(items) if items else np.empty((0, {'trajectory2': 2, 'resampled4': 4, 'resampled8': 8, 'tail_stats': 4}[v]*1024), dtype=np.float32)
                      for v, items in vectors.items()}
            temporary = path.with_suffix('.tmp.npz')
            np.savez_compressed(temporary, ids=np.array(valid, dtype=str), **arrays)
            temporary.chmod(0o600); temporary.replace(path)
            meta_path.write_text(json.dumps({'identity': identity, 'excluded': rejected,
                'replayed': replayed, 'max_baseline_difference': maximum}, ensure_ascii=False, indent=2)); meta_path.chmod(0o600)
        meta = json.loads(meta_path.read_text())
        exclusions.extend(meta['excluded']); replay_count += meta['replayed']
        replay_max = max(replay_max, meta['max_baseline_difference'])
        with np.load(path, allow_pickle=False) as stored:
            output.extend({'id': str(uid), 'cache': str(path), 'index': i} for i, uid in enumerate(stored['ids']))
        print('TEMPORAL', len(output), 'targets cached', flush=True)
    report = {'complete': True, 'dataset_sha256': digest(folder / 'dataset.json'),
              'model': model.spec, 'layer': plan['layer'], 'context_ms': plan['context_ms'],
              'views': VIEWS, 'rows': output, 'excluded': exclusions,
              'baseline_replayed': replay_count, 'max_baseline_feature_difference': replay_max}
    path = folder / 'feature-index.json'; path.write_text(json.dumps(report, ensure_ascii=False, indent=2)); path.chmod(0o600)
    print('COMPLETE', len(output), 'EXCLUDED', len(exclusions), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', required=True)
    main(parser.parse_args())
