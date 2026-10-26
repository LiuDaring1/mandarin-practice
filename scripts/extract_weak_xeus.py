"""Extract fixed Xeus L19 features for unverified train-only candidates.

Expected text is never passed to the encoder. Existing strong train targets in
the same windows are replay anchors, not new labels or selection evidence.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_acoustics import read_audio
from nasal_feature_probe import pool_regions
from phonetic_xeus import XeusModel
from probe_nasal_weak import FOLDER, checked, engine
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def trajectory(states, bounds, a, b, stride, field):
    relative = {key: [t-a/16000 for t in limits] for key, limits in bounds.items()}
    pooled = pool_regions(states, relative, sample_count=b-a, stride=stride, receptive_field=field)
    return pooled[2:4].reshape(-1)


def main():
    import torch
    plan = checked()
    if (FOLDER/'feature-report.json').exists():
        raise ValueError('Weak feature report already frozen')
    dataset = json.loads((FOLDER/'weak-dataset.json').read_text())
    if dataset['plan_sha256'] != engine.sha(FOLDER/'plan.json'):
        raise ValueError('Weak dataset plan changed')
    strong_rows, strong_x, _ = engine.load('existing')
    anchors = {r['id']: (r, strong_x[i, 1]) for i, r in enumerate(strong_rows) if r['split']=='train'}
    anchor_by_audio = defaultdict(list)
    for row, _ in anchors.values():
        anchor_by_audio[row['audio']].append(row)
    groups = defaultdict(list)
    for row in dataset['rows']:
        if row['split']!='train' or row.get('label_status')!='unverified' or 'actual_label' in row:
            raise ValueError('Weak candidate became evaluation data or gold')
        groups[row['audio']].append(row)
    model = XeusModel()
    cache = FOLDER/'features'; cache.mkdir(exist_ok=True)
    vectors = {}; excluded = []; replay = {}; cache_hashes = {}; windows_done = 0
    for audio, rows in groups.items():
        if any(engine.sha(audio) != r['audio_sha256'] for r in rows):
            raise ValueError('Weak audio changed')
        samples = read_audio(Path(audio), max_seconds=180)
        windows = defaultdict(list)
        for row in rows:
            try:
                windows[context_interval(len(samples), row['bounds']['syllable'])].append(row)
            except ValueError as error:
                excluded.append({'id': row['id'], 'reason': str(error)})
        for (a, b), targets in windows.items():
            controls = [r for r in anchor_by_audio[audio] if context_interval(len(samples), r['bounds']['syllable'])==(a,b)]
            waveform = samples[a:b]
            acoustic_key = hashlib.sha256(json.dumps(model.identity, sort_keys=True).encode()+waveform.tobytes()).hexdigest()
            identity = {'acoustic_key': acoustic_key, 'layer': plan['layer'], 'view': plan['view'],
                'weak': [(r['id'], r['bounds']) for r in targets], 'anchors': [(r['id'], r['bounds']) for r in controls]}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            path = cache/(key+'.npz'); meta_path = cache/(key+'.json')
            if not (path.exists() and meta_path.exists()):
                speech = torch.from_numpy(waveform.copy()).unsqueeze(0).to(model.device)
                lengths = torch.tensor([len(waveform)], dtype=torch.long, device=model.device)
                model.conditioning_calls = 0; model.conditioning_norms = []
                with torch.inference_mode():
                    encoded, output_lengths = model.model.encode(speech, lengths)
                    final, intermediate = encoded
                    states = final[0].float().cpu().numpy().copy()
                expected = (len(waveform)-model.field)//model.stride+1
                if (int(output_lengths[0]) != expected or len(states) != expected or not np.isfinite(states).all()
                        or [i for i, _ in intermediate] != [4, 8, 12] or model.conditioning_calls != 3
                        or not all(np.isfinite(n) and n>0 for n in model.conditioning_norms)):
                    raise RuntimeError('Fixed Xeus path or frame grid changed')
                ids = []; values = []; rejected = []; anchor_ids = []; anchor_values = []
                for row in targets:
                    try:
                        value = trajectory(states, row['bounds'], a, b, model.stride, model.field)
                    except ValueError as error:
                        rejected.append({'id': row['id'], 'reason': str(error)}); continue
                    ids.append(row['id']); values.append(value)
                for row in controls:
                    anchor_ids.append(row['id'])
                    anchor_values.append(trajectory(states, row['bounds'], a, b, model.stride, model.field))
                temporary = path.with_suffix('.tmp.npz')
                engine.save_npz(temporary, ids=np.array(ids, dtype=str),
                    features=np.stack(values) if values else np.empty((0, 2048), dtype=np.float32),
                    anchor_ids=np.array(anchor_ids, dtype=str),
                    anchors=np.stack(anchor_values) if anchor_values else np.empty((0, 2048), dtype=np.float32))
                temporary.replace(path)
                save_json(meta_path, {'identity': identity, 'features_sha256': engine.sha(path), 'excluded': rejected})
                del encoded, final, intermediate, states, speech, lengths
                torch.mps.empty_cache()
            metadata = json.loads(meta_path.read_text())
            if (metadata['identity'] != json.loads(json.dumps(identity))
                    or metadata['features_sha256'] != engine.sha(path)):
                raise ValueError('Weak feature cache changed')
            with np.load(path, allow_pickle=False) as values:
                for uid, value in zip(values['ids'].tolist(), values['features']):
                    if uid in vectors:
                        raise ValueError('Duplicate weak feature')
                    vectors[uid] = value
                for uid, value in zip(values['anchor_ids'].tolist(), values['anchors']):
                    difference = float(np.max(np.abs(value-anchors[uid][1])))
                    if difference > plan['anchor_feature_tolerance']:
                        raise ValueError('Strong-anchor feature replay changed')
                    replay[uid] = difference
            excluded.extend(metadata['excluded'])
            cache_hashes[str(path)] = engine.sha(path); cache_hashes[str(meta_path)] = engine.sha(meta_path)
            windows_done += 1
        print('WEAK FEATURES', len(vectors), 'targets;', windows_done, 'windows;', len(replay), 'anchors', flush=True)
    if not replay:
        raise ValueError('No strong train anchor replay available')
    ids = [r['id'] for r in dataset['rows'] if r['id'] in vectors]
    if len(ids)+len(excluded) != len(dataset['rows']):
        raise ValueError('Weak feature denominator changed')
    path = FOLDER/'weak-features.npz'
    engine.save_npz(path, ids=np.array(ids), features=np.stack([vectors[uid] for uid in ids]))
    checked()
    save_json(FOLDER/'feature-report.json', {'complete': True, 'plan_sha256': engine.sha(FOLDER/'plan.json'),
        'dataset_sha256': engine.sha(FOLDER/'weak-dataset.json'), 'features_sha256': engine.sha(path),
        'model': model.identity, 'layer': plan['layer'], 'view': plan['view'], 'targets': len(ids),
        'excluded': excluded, 'selected_weak_targets': dataset['selected_targets'],
        'unavailable_alignment': len(dataset['excluded']), 'windows': windows_done, 'recordings': len(groups),
        'strong_train_anchor_replay': {'targets': len(replay), 'maximum_absolute_difference': max(replay.values())},
        'cache_sources': cache_hashes, 'reference_text_input': False, 'actual_labels_assigned': False})
    print('WEAK EXTRACTION COMPLETE', len(ids), 'features;', len(excluded), 'feature failures;',
          len(replay), 'anchors max difference', max(replay.values()), flush=True)


if __name__=='__main__':
    main()
