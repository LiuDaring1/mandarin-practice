"""Freeze, fit, then evaluate symmetric pair heads against a shared control.

No API requests or application writes. All evaluation speech has previously
been explored, so this is a controlled method comparison, not blind acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_feature_fusion import align_features, feature_source, gate_scores
from nasal_feature_probe import assert_speaker_partition, feature_view
from nasal_pair_classifier import audit_training, fit_heads, pack_heads, pair_key, predict_heads, unpack_heads
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
SOURCE = BASE/'fusion-vad-v2'
FOLDER = BASE/'pair-classifier-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_npz(path, **values):
    np.savez_compressed(path, **values)
    path.chmod(0o600)


def load(cohort):
    dataset = json.loads((SOURCE/f'{cohort}-dataset.json').read_text())
    rows = dataset['rows']
    assert_speaker_partition(rows+dataset['excluded'])
    if len({r['id'] for r in rows+dataset['excluded']}) != len(rows+dataset['excluded']):
        raise ValueError('Duplicate selected target')
    with np.load(SOURCE/f'{cohort}-features.npz', allow_pickle=False) as values:
        if values['ids'].tolist() != [r['id'] for r in rows]:
            raise ValueError('Feature/target identity mismatch')
        return rows, values['features'], dataset


def present(rows, cohort):
    evidence = json.loads((SOURCE/'evidence.json').read_text())
    if evidence.get('complete') is not True or evidence['plan_sha256'] != sha(SOURCE/'plan.json'):
        raise ValueError('Stale VAD evidence')
    return np.array([True if r['expected_label']=='other' else evidence['cohorts'][cohort][r['id']]['present']
                     for r in rows], dtype=bool)


def prepare():
    from probe_nasal_fusion import old_features
    import probe_nasal_vad_fusion
    if FOLDER.exists():
        raise ValueError('Pair experiment already frozen')
    probe_nasal_vad_fusion.checked()
    rows, _, _ = load('existing')
    support = audit_training([r for r in rows if r['split']=='train'])
    # Label-free alignment of cached background features, before any head fit.
    noise_rows, left, _ = old_features(SOURCE/'noise')
    with np.load(SOURCE/'noise/xeus-features.npz', allow_pickle=False) as values:
        lookup = {str(uid): i for i, uid in enumerate(values['ids'])}
        right = feature_view(np.stack([values['features'][lookup[r['id']]] for r in noise_rows])[:, None], 0, 'trajectory')
    noise = align_features(noise_rows, left, noise_rows, right)
    files = [SOURCE/name for name in ('plan.json', 'evidence.json', 'selection.json', 'ridge-model.npz',
             'existing-dataset.json', 'existing-features.npz', 'griffith-dataset.json', 'griffith-features.npz',
             'noise/dataset.json', 'noise/feature-index.json', 'noise/xeus-features.npz')]
    files += [Path('scripts')/name for name in ('probe_nasal_pairs.py', 'nasal_pair_classifier.py',
              'nasal_feature_fusion.py', 'nasal_feature_probe.py', 'nasal_directional_calibration.py',
              'probe_phonetic_xeus.py', 'train_nasal_feature_probe.py', 'probe_nasal_boundaries.py',
              'fit_nasal_context_probe.py', 'audit_nasal_feedback_conflicts.py',
              'select_nasal_feedback_probe.py', 'calibrate_nasal_exact_margin.py')]
    hashes = {str(path): sha(path) for path in files}
    FOLDER.mkdir()
    save_npz(FOLDER/'noise-features.npz', features=noise, ids=np.array([r['id'] for r in noise_rows]))
    hashes[str(FOLDER/'noise-features.npz')] = sha(FOLDER/'noise-features.npz')
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': hashes,
            'support': support, 'feature_sources': ['local_phoneme', 'xeus', 'concatenated'],
            'regularizations': [.01, .1, 1.], 'specialist_weights': [0., .5, 1.],
            'specialist_other_class': 'all nonnasal and outside-pair training speech',
            'shared_fallback_for_sparse_pairs': True, 'calibration_mode': 'directional',
            'ranking': ['dev error detections', 'dev normal matches', 'stronger regularization',
                        'smaller specialist weight', 'simpler feature source'],
            'evaluate': ['best overall', 'best nonzero specialist weight', 'best shared-only control'],
            'gate': 'unchanged fixed Silero VAD', 'api_positive_veto': True,
            'expected_direction_enters_classifier': False, 'selection_splits': ['train', 'dev'],
            'evaluation_previously_explored': True, 'noise_used_for_selection': False,
            'production_enablement': False}
    save_json(FOLDER/'plan.json', plan)
    print('PLAN FROZEN', json.dumps(support), flush=True)


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    amendment = FOLDER/'implementation-amendment.json'
    repairs = json.loads(amendment.read_text())['repairs'] if amendment.exists() else {}
    for path, digest in plan['sources'].items():
        if sha(path) != digest and repairs.get(path) != {'before': digest, 'after': sha(path)}:
            raise ValueError(f'Frozen source changed: {path}')
    return plan


def rank(candidate, plan):
    dev = candidate['development']
    return (-dev['correct_error_directions'], -dev['correct_nasal_matches'],
            -candidate['regularization'], candidate['specialist_weight'],
            plan['feature_sources'].index(candidate['feature_source']))


def fit():
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply, calibrate
    plan = checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-heads.npz')):
        raise ValueError('Pair selection already frozen')
    rows, x, dataset = load('existing')
    positions = [i for i, r in enumerate(rows) if r['split'] in ('train', 'dev')]
    rows = [rows[i] for i in positions]; x = x[positions]
    training = np.array([r['split']=='train' for r in rows]); dev = ~training
    train_rows = [r for r in rows if r['split']=='train']; dev_rows = [r for r in rows if r['split']=='dev']
    denominator = [r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    acceptance = present(dev_rows, 'existing'); candidates = []
    models = {}
    for source in plan['feature_sources']:
        values = feature_source(x, source)
        for strength in plan['regularizations']:
            heads = fit_heads(values[training], train_rows, strength, plan['support'])
            models[(source, strength)] = heads
            for weight in plan['specialist_weights']:
                scores = predict_heads(heads, values[dev], [r['expected_final'] for r in dev_rows], weight)
                scores = gate_scores(scores, acceptance)
                policy = calibrate(dev_rows, scores, plan['calibration_mode'])
                candidate = {**policy, 'feature_source': source, 'regularization': strength,
                             'specialist_weight': weight,
                             'development': summarize_denominator(denominator, apply(dev_rows, scores, policy))}
                candidates.append(candidate)
                d = candidate['development']
                print('CANDIDATE', source, strength, weight, d['correct_error_directions'], d['correct_nasal_matches'], flush=True)
    candidates.sort(key=lambda c: rank(c, plan))
    selected = {'primary': candidates[0],
                'pair': next(c for c in candidates if c['specialist_weight']>0),
                'shared': next(c for c in candidates if c['specialist_weight']==0)}
    weights = {}
    for name, candidate in selected.items():
        path = FOLDER/f'{name}-heads.npz'
        save_npz(path, **pack_heads(models[(candidate['feature_source'], candidate['regularization'])]))
        weights[name] = sha(path)
    save_json(FOLDER/'selection.json', {'selected': selected, 'ranking': candidates,
              'plan_sha256': sha(FOLDER/'plan.json'), 'weights_sha256': weights,
              'selected_at_utc': datetime.now(timezone.utc).isoformat(),
              'train_ids': [r['id'] for r in train_rows], 'dev_ids': [r['id'] for r in dev_rows],
              'evaluation_rows_used_for_selection': False, 'noise_used_for_selection': False})
    print('SELECTED', json.dumps({name: {k: c[k] for k in ('feature_source', 'regularization', 'specialist_weight')}
                                 for name, c in selected.items()}), flush=True)


def summarize_pairs(dataset, observations, specialized):
    from probe_nasal_boundaries import summarize_denominator
    selected = [r for r in dataset['rows']+dataset['excluded'] if r['split'] not in ('train', 'dev')]
    summaries = {}
    # Older excluded targets retain nasal direction but lack a recoverable final.
    # Keep them in an explicit unknown bucket instead of dropping the denominator.
    def group(row):
        return pair_key(row.get('expected_final', '')) or 'unavailable_final'
    for key in sorted({group(r) for r in selected}):
        members = [r for r in selected if group(r)==key]
        ids = {r['id'] for r in members}
        route = 'unknown' if key=='unavailable_final' else ('specialist' if key in specialized else 'shared')
        summaries[key] = {'route': route,
                          **summarize_denominator(members, [o for o in observations if o['id'] in ids])}
    return summaries


def evaluate():
    from probe_phonetic_xeus import apply, cohort_summary
    plan = checked()
    if (FOLDER/'evaluation.json').exists():
        raise ValueError('Pair evaluation already frozen')
    selection = json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256'] != sha(FOLDER/'plan.json'):
        raise ValueError('Selection plan changed')
    reports = {}; invariance = {}; noise = {}
    for name, candidate in selection['selected'].items():
        path = FOLDER/f'{name}-heads.npz'
        if sha(path) != selection['weights_sha256'][name]:
            raise ValueError('Classifier weights changed')
        with np.load(path, allow_pickle=False) as stored:
            heads = unpack_heads(dict(stored))
        reports[name] = {}; invariance[name] = {}
        for cohort in ('existing', 'griffith'):
            rows, x, dataset = load(cohort)
            positions = [i for i, r in enumerate(rows) if r['split'] not in ('train', 'dev') and r['expected_label'] != 'other']
            rows = [rows[i] for i in positions]; x = feature_source(x[positions], candidate['feature_source'])
            finals = [r['expected_final'] for r in rows]
            scores = predict_heads(heads, x, finals, candidate['specialist_weight'])
            # Intentionally swap every expected nasal; reuse identical audio and time bounds.
            opposite = [pair_key(f) if f.endswith('ng') else pair_key(f)+'g' for f in finals]
            alternate = predict_heads(heads, x, opposite, candidate['specialist_weight'])
            difference = float(np.max(np.abs(scores-alternate)))
            if difference != 0:
                raise ValueError('Expected-direction leakage in acoustic prediction')
            invariance[name][cohort] = {'targets': len(rows), 'maximum_score_difference': difference,
                                       'features_and_bounds_unchanged': True}
            scores = gate_scores(scores, present(rows, cohort))
            observed = apply(rows, scores, candidate)
            selected = {k: [r for r in dataset[k] if r['expected_label'] != 'other'] for k in ('rows', 'excluded')}
            summary = cohort_summary(selected, observed)
            active = plan['support']['eligible_pairs'] if candidate['specialist_weight'] else []
            summary['pairs'] = summarize_pairs(selected, observed, active)
            reports[name][cohort] = summary
            d = summary['evaluation_only']
            print('EVALUATED', name, cohort, json.dumps({k: d[k] for k in ('correct_error_directions',
                  'known_nasal_errors', 'false_nasal_accusations', 'correct_nasal_targets', 'false_reassurances',
                  'correct_nasal_matches', 'uncertain_nasal_targets')}), flush=True)
        noise_rows = json.loads((SOURCE/'noise/dataset.json').read_text())['rows']
        with np.load(FOLDER/'noise-features.npz', allow_pickle=False) as values:
            if values['ids'].tolist() != [r['id'] for r in noise_rows]:
                raise ValueError('Noise identity mismatch')
            x = feature_source(values['features'], candidate['feature_source'])
        # Probe each supported pair and one sparse shared route in both directions.
        finals = [f for key in plan['support']['eligible_pairs']+['uan'] for f in (key, key+'g')]
        evidence = json.loads((SOURCE/'evidence.json').read_text())['cohorts']['noise']
        accept = np.array([evidence[r['id']]['present'] for r in noise_rows], dtype=bool)
        observations = []
        for final in finals:
            scores = predict_heads(heads, x, [final]*len(x), candidate['specialist_weight'])
            targets = [{**r, 'expected_final': final, 'expected_label': 'back' if final.endswith('ng') else 'front'} for r in noise_rows]
            for state, values in [('gated', gate_scores(scores, accept)), ('ungated', scores)]:
                for obs, row in zip(apply(targets, values, candidate), noise_rows):
                    observations.append({**obs, 'gate': state, 'expected_final': final, 'noise_source': row['noise_source']})
        noise[name] = {'recordings': len(noise_rows), 'tested_reference_finals': finals,
            'summaries': {kind: {state: {'conditions': len(part),
                'false_matches': sum(r['candidate_nasal_match'] for r in part),
                'false_corrections': sum(r['candidate_nasal_change'] for r in part),
                'abstentions': sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in part)}
                for state in ('gated', 'ungated') for part in [[r for r in observations if r['noise_source']==kind and r['gate']==state]]}
                for kind in ('synthetic', 'recorded_environment')}, 'predictions': observations}
    report = {'complete': True, 'selection_sha256': sha(FOLDER/'selection.json'),
              'selected': selection['selected'], 'comparison': reports, 'counterfactual_invariance': invariance,
              'noise': noise, 'limits': ['Existing speech/backgrounds are explored comparison sets, not fresh blind tests.',
              'Counterfactual check covers classifier conditioning, not reference-dependent API alignment.',
              'Outside-pair class cannot diagnose a particular nonnasal error.',
              'No speech-in-noise, omission, repetition or real microphone validation.',
              'Sparse pairs use a shared head, not validated pair specialists.']}
    save_json(FOLDER/'evaluation.json', report)
    print('EVALUATION COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'fit', 'evaluate'])
    args = parser.parse_args()
    {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.mode]()
