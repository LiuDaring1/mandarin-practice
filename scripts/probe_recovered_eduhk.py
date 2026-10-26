"""Frozen-head evaluation of recovered word errors and synthetic non-speech.

No refitting, threshold selection, or production enablement occurs here.
Recovered words are not an independent speaker test; splits remain explicit.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from eduhk_word_inventory import BASE, OUTPUT, digest
from nasal_feature_probe import feature_view, pool_regions, predict_ridge
from phonetic_xeus import XeusModel
from train_nasal_feature_probe import save_json
from xeus_stress import synthetic
from zipa_context import context_interval

FOLDER = OUTPUT / 'probe'
HEAD = BASE / 'xeus-features-v2'
OLD = BASE / 'local-context-training-v8'


def prepare():
    from opencc import OpenCC
    if FOLDER.exists():
        raise ValueError('Recovery probe plan already frozen')
    converter = OpenCC('tw2s')
    inputs = json.loads((OUTPUT/'recovered-input.json').read_text())
    cases = []
    for row in inputs['cases']:
        reference = converter.convert(row['reference'])
        if len(reference) != len(row['reference']) or reference[row['position']] != converter.convert(row['annotation']['character']):
            raise ValueError('Conversion changed character positions')
        cases.append({**row, 'source_reference': row['reference'], 'reference': reference})
    sources = [OUTPUT/'inventory.json', OUTPUT/'recovered-input.json', Path(__file__),
               HEAD/'selection.json', HEAD/'ridge-model.npz', OLD/'selection.json', OLD/'ridge-model.npz',
               BASE/'xeus-v1/runtime-source.json', BASE/'xeus-v1/nonspeech/plan.json']
    sources += [Path('scripts')/name for name in ['phonetic_xeus.py', 'nasal_feature_probe.py',
                'probe_phonetic_xeus.py', 'nasal_directional_calibration.py', 'xeus_stress.py',
                'extract_nasal_features.py', 'ise_probe.py', 'run_ise_calibration.py', 'fit_nasal_context_probe.py']]
    count = len(json.loads(Path('data/derived/ise-validation/requests.json').read_text()))
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': {str(p): digest(p) for p in sources},
            'ledger_before': count, 'maximum_new_requests': len(cases), 'maximum_total_requests': count+len(cases),
            'threshold_selection_allowed': False, 'model_training_allowed': False,
            'new_blind_validation': False, 'preserve_speaker_partitions': True,
            'synthetic_only_noise_check': True, 'noise_policy': 'Test the acoustic head with no credit for API rejection.'}
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json', plan)
    save_json(FOLDER/'ise-input.json', {'cases': cases})
    print('Prepared', len(cases), 'targets; cumulative request ceiling', count+len(cases), flush=True)


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    if any(digest(p) != sha for p, sha in plan['sources'].items()):
        raise ValueError('Recovery probe source changed')
    return plan


def freeze():
    from prepare_nasal_feature_data import interval
    from probe_eduhk_nasal import model_final
    checked()
    if (FOLDER/'dataset.json').exists():
        raise ValueError('Recovery dataset already frozen')
    inputs = json.loads((FOLDER/'ise-input.json').read_text())['cases']
    results = json.loads((FOLDER/'ise-results.json').read_text())
    if results.get('complete') is not True:
        raise ValueError('ISE recovery batch incomplete')
    by_id = {r['id']: r for r in results['cases']}
    if set(by_id) != {r['id'] for r in inputs}:
        raise ValueError('Incomplete recovered target inventory')
    rows, excluded = [], []
    for source in inputs:
        observation = by_id[source['id']]['ise_observation']
        expected = 'back' if source['annotation']['expected_plain'].endswith('ng') else 'front'
        row = {**source, 'expected_final': model_final(source['annotation']['expected_plain']),
               'expected_label': expected, 'actual_label': source['annotation']['actual_group'],
               'api_state': observation['state'], 'cohort': 'recovered_word', 'condition': 'word_error',
               'label_source': 'explicit_nasal_substitution_at_html_highlight'}
        bounds = interval(observation, source['audio'])
        if bounds is None:
            excluded.append({**row, 'reason': 'unusable_ise_interval'})
        else:
            rows.append({**row, 'bounds': bounds})
    save_json(FOLDER/'dataset.json', {'rows': rows, 'excluded': excluded, 'plan_sha256': digest(FOLDER/'plan.json')})
    print('Frozen', len(rows), 'usable and', len(excluded), 'unavailable targets', flush=True)


def infer():
    import torch
    from nasal_acoustics import read_audio
    checked()
    if (FOLDER/'xeus-features.npz').exists():
        raise ValueError('Recovery Xeus features already frozen')
    model = XeusModel()
    dataset = json.loads((FOLDER/'dataset.json').read_text())
    noise = json.loads((BASE/'xeus-v1/nonspeech/plan.json').read_text())['signals']
    values, ids, rejected = [], [], []

    def extract(uid, samples, bounds):
        start, end = context_interval(len(samples), bounds['syllable'])
        waveform = samples[start:end]
        speech = torch.from_numpy(waveform.copy()).unsqueeze(0).to('mps')
        lengths = torch.tensor([len(waveform)], dtype=torch.long, device='mps')
        model.conditioning_calls = 0
        model.conditioning_norms = []
        with torch.inference_mode():
            encoded, output_lengths = model.model.encode(speech, lengths)
            final, intermediate = encoded
            if model.conditioning_calls != 3 or [i for i, _ in intermediate] != [4, 8, 12]:
                raise RuntimeError('Xeus conditioning path changed')
            if int(output_lengths[0]) != (len(waveform)-model.field)//model.stride+1:
                raise RuntimeError('Xeus frame geometry changed')
            features = final[0].float().cpu().numpy()
        local = {key: [t-start/16000 for t in pair] for key, pair in bounds.items()}
        try:
            pooled = pool_regions(features, local, sample_count=len(waveform),
                                  stride=model.stride, receptive_field=model.field)
        except ValueError as error:
            rejected.append({'id': uid, 'reason': str(error)})
            return
        if not np.isfinite(pooled).all():
            raise RuntimeError('Non-finite acoustic features')
        ids.append(uid)
        values.append(pooled)
        torch.mps.empty_cache()

    if json.loads((HEAD/'selection.json').read_text())['selected']['layer'] != 19:
        raise ValueError('This prospective transfer probe fixes the selected final layer')
    for row in dataset['rows']:
        if digest(row['audio']) != row['audio_sha256']:
            raise ValueError('Recovered crop changed')
        extract(row['id'], read_audio(Path(row['audio'])), row['bounds'])
        print('RECOVERY XEUS', len(ids), flush=True)
    for row in noise:
        samples = synthetic(row['kind'], row['duration'], row['seed'])
        if hashlib.sha256(samples.tobytes()).hexdigest() != row['audio_sha256']:
            raise ValueError('Frozen non-speech waveform changed')
        extract(f"noise-{row['kind']}-{row['duration']}", samples,
                {'syllable': [0., row['duration']], 'vowel': [0., row['duration']]})
    path = FOLDER/'xeus-features.npz'
    np.savez_compressed(path, features=np.stack(values), ids=np.array(ids, dtype=str))
    path.chmod(0o600)
    save_json(FOLDER/'xeus-feature-index.json', {'complete': True, 'dataset_sha256': digest(FOLDER/'dataset.json'),
              'plan_sha256': digest(FOLDER/'plan.json'), 'model': model.identity,
              'feature_sha256': digest(path), 'ids': ids, 'excluded': rejected})
    print('COMPLETE recovery and synthetic signals', len(ids), flush=True)


def evaluate():
    from fit_nasal_context_probe import policy_observations
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply
    from train_nasal_feature_probe import load_features
    from nasal_feature_probe import LAYERS
    checked()
    if (FOLDER/'evaluation.json').exists():
        raise ValueError('Recovery evaluation frozen')
    dataset = json.loads((FOLDER/'dataset.json').read_text())
    index = json.loads((FOLDER/'xeus-feature-index.json').read_text())
    if (index.get('complete') is not True or index['dataset_sha256'] != digest(FOLDER/'dataset.json')
        or index['feature_sha256'] != digest(FOLDER/'xeus-features.npz')):
        raise ValueError('Incomplete or stale Xeus features')
    selected = json.loads((HEAD/'selection.json').read_text())['selected']
    with np.load(HEAD/'ridge-model.npz', allow_pickle=False) as stored:
        model = {key: stored[key] for key in stored.files}
    with np.load(FOLDER/'xeus-features.npz', allow_pickle=False) as stored:
        ids = stored['ids'].tolist()
        scores = predict_ridge(model, feature_view(stored['features'][:, None], 0, selected['view']))
    by_id = {uid: score for uid, score in zip(ids, scores)}
    rows = [row for row in dataset['rows'] if row['id'] in by_id]
    xeus = apply(rows, np.stack([by_id[row['id']] for row in rows]), selected)
    noise = []
    for uid, score in by_id.items():
        if not uid.startswith('noise-'):
            continue
        for expected in ('front', 'back'):
            row = {'id': uid+'-'+expected, 'speaker': 'synthetic', 'condition': 'no_speech',
                   'split': 'stress', 'actual_label': 'other', 'expected_label': expected, 'api_state': 'not_flagged'}
            noise.extend(apply([row], score[None], selected))
    features, old_rows, _, old_index = load_features(FOLDER)
    old = json.loads((OLD/'selection.json').read_text())['selected']
    if old_index['context_ms'] != old['context_ms']:
        raise ValueError('Baseline context changed')
    with np.load(OLD/'ridge-model.npz', allow_pickle=False) as stored:
        old_model = {key: stored[key] for key in stored.files}
    old_scores = predict_ridge(old_model, feature_view(features, LAYERS.index(old['layer']), old['view']))
    baseline = policy_observations(old_rows, old_scores, old['review_margin'], old['matching_margin'])
    denominator = dataset['rows']+dataset['excluded']
    summaries = {}
    for name, predictions in [('xeus', xeus), ('baseline_v8', baseline)]:
        summaries[name] = {'all_recovered': summarize_denominator(denominator, predictions),
            'by_split': {split: summarize_denominator([r for r in denominator if r['split']==split],
                        [r for r in predictions if r['split']==split]) for split in sorted({r['split'] for r in denominator})},
            'predictions': predictions}
    results = json.loads((FOLDER/'ise-results.json').read_text())
    report = {'complete': True, 'comparison': summaries,
              'ise_states': dict(Counter(row['ise_observation']['state'] for row in results['cases'])),
              'synthetic': {'cases': len(noise), 'false_matches': sum(r['candidate_nasal_match'] for r in noise),
                            'false_corrections': sum(r['candidate_nasal_change'] for r in noise),
                            'abstentions': sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in noise),
                            'predictions': noise},
              'plan_sha256': digest(FOLDER/'plan.json'), 'new_blind_validation': False,
              'limits': ['All recovered targets are errors: no new normal controls or specificity estimate.',
                         'Same speaker partitions, no fitting or threshold tuning on recovered results.',
                         'Synthetic non-speech is not a real-device or speech-in-noise check.']}
    save_json(FOLDER/'evaluation.json', report)
    for name, result in summaries.items():
        print(name, json.dumps(result['all_recovered']), flush=True)
    print('SYNTHETIC', json.dumps({k:v for k,v in report['synthetic'].items() if k!='predictions'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'freeze', 'infer', 'evaluate'])
    args = parser.parse_args()
    {'prepare': prepare, 'freeze': freeze, 'infer': infer, 'evaluate': evaluate}[args.mode]()
