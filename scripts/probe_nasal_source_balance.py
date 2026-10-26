"""Controlled source-balancing experiment over the frozen pair-head grid.

Reuse the prior loader, evaluator and gates without editing frozen scripts.
Training weights are the only experimental change. Matching controls are
selected prospectively, before any held-out score is calculated.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

import probe_nasal_pairs as engine
from nasal_feature_fusion import feature_source, gate_scores
from nasal_pair_classifier import fit_heads, pack_heads, predict_heads
from nasal_source_balance import fit_source_heads, source_weights, training_labels
from train_nasal_feature_probe import save_json

PREVIOUS = engine.FOLDER
FOLDER = engine.BASE/'source-balanced-v1'


@contextmanager
def experiment_root():
    previous = engine.FOLDER
    engine.FOLDER = FOLDER
    try:
        yield
    finally:
        engine.FOLDER = previous


def prepare():
    if FOLDER.exists():
        raise ValueError('Source balance experiment already frozen')
    prior = engine.checked()
    rows, _, _ = engine.load('existing')
    train_rows = [r for r in rows if r['split']=='train']
    audit = {key: source_weights(train_rows, y)[1] for key, y in training_labels(train_rows, prior['support']).items()}
    paths = [Path(path) for path in prior['sources']]
    paths += [PREVIOUS/name for name in ('plan.json', 'selection.json', 'evaluation.json', 'implementation-amendment.json')]
    paths += [Path(__file__), Path('scripts/nasal_source_balance.py')]
    hashes = {str(path): engine.sha(path) for path in paths}
    FOLDER.mkdir()
    shutil.copyfile(PREVIOUS/'noise-features.npz', FOLDER/'noise-features.npz')
    (FOLDER/'noise-features.npz').chmod(0o600)
    hashes[str(FOLDER/'noise-features.npz')] = engine.sha(FOLDER/'noise-features.npz')
    plan = {key: prior[key] for key in ('support', 'feature_sources', 'regularizations', 'specialist_weights',
                                       'calibration_mode', 'gate', 'api_positive_veto')}
    plan.update(frozen_at_utc=datetime.now(timezone.utc).isoformat(), sources=hashes,
        weighting=['class_only', 'source_class'], training_weight_audit=audit,
        weighting_rule='Each class gets N/3; each represented source within that class gets equal mass.',
        missing_cells='Remain missing; no synthetic labels or source-specific prediction input.',
        ranking=['dev correct error directions', 'dev correct normal matches', 'stronger regularization',
                 'smaller specialist weight', 'class-only tie preference', 'simpler feature source'],
        evaluate=['best overall', 'best source-balanced', 'best class-only',
                  'class-only at the best source-balanced feature/regularization/specialist weight'],
        selection_splits=['train', 'dev'], evaluation_previously_explored=True,
        source_is_prediction_input=False, production_enablement=False, noise_used_for_selection=False)
    save_json(FOLDER/'plan.json', plan)
    print('SOURCE PLAN FROZEN', len(train_rows), 'training targets', flush=True)
    print('WEIGHT AUDIT', json.dumps(audit), flush=True)


def checked():
    with experiment_root():
        return engine.checked()


def rank(candidate, plan):
    dev = candidate['development']
    return (-dev['correct_error_directions'], -dev['correct_nasal_matches'], -candidate['regularization'],
            candidate['specialist_weight'], plan['weighting'].index(candidate['weighting']),
            plan['feature_sources'].index(candidate['feature_source']))


def fit():
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply, calibrate
    plan = checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-heads.npz')):
        raise ValueError('Source-balanced selection already frozen')
    rows, x, dataset = engine.load('existing')
    positions = [i for i, r in enumerate(rows) if r['split'] in ('train', 'dev')]
    rows = [rows[i] for i in positions]; x = x[positions]
    training = np.array([r['split']=='train' for r in rows]); dev = ~training
    train_rows = [r for r in rows if r['split']=='train']; dev_rows = [r for r in rows if r['split']=='dev']
    denominator = [r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    acceptance = engine.present(dev_rows, 'existing')
    candidates = []; models = {}
    previous = json.loads((PREVIOUS/'selection.json').read_text())['ranking']
    for weighting in plan['weighting']:
        fitter = fit_heads if weighting=='class_only' else fit_source_heads
        for source in plan['feature_sources']:
            values = feature_source(x, source)
            for strength in plan['regularizations']:
                heads = fitter(values[training], train_rows, strength, plan['support'])
                models[(weighting, source, strength)] = heads
                for weight in plan['specialist_weights']:
                    scores = predict_heads(heads, values[dev], [r['expected_final'] for r in dev_rows], weight)
                    scores = gate_scores(scores, acceptance)
                    policy = calibrate(dev_rows, scores, plan['calibration_mode'])
                    candidate = {**policy, 'feature_source': source, 'regularization': strength,
                                 'specialist_weight': weight,
                                 'development': summarize_denominator(denominator, apply(dev_rows, scores, policy))}
                    if weighting=='class_only':
                        old = next(c for c in previous if c['feature_source']==source and c['regularization']==strength
                                   and c['specialist_weight']==weight)
                        if json.dumps(candidate, sort_keys=True)!=json.dumps(old, sort_keys=True):
                            raise ValueError('Unchanged class-only grid failed exact development replay')
                    candidate['weighting'] = weighting
                    candidates.append(candidate)
                    d = candidate['development']
                    print('CANDIDATE', weighting, source, strength, weight,
                          d['correct_error_directions'], d['correct_nasal_matches'], flush=True)
    candidates.sort(key=lambda c: rank(c, plan))
    best_balanced = next(c for c in candidates if c['weighting']=='source_class')
    control = next(c for c in candidates if c['weighting']=='class_only' and
                   all(c[k]==best_balanced[k] for k in ('feature_source', 'regularization', 'specialist_weight')))
    selected = {'primary': candidates[0], 'balanced': best_balanced,
                'shared_grid_control': next(c for c in candidates if c['weighting']=='class_only'),
                'matched_control': control}
    weights = {}
    for name, candidate in selected.items():
        path = FOLDER/f'{name}-heads.npz'
        engine.save_npz(path, **pack_heads(models[(candidate['weighting'], candidate['feature_source'], candidate['regularization'])]))
        weights[name] = engine.sha(path)
    save_json(FOLDER/'selection.json', {'selected': selected, 'ranking': candidates,
        'plan_sha256': engine.sha(FOLDER/'plan.json'), 'weights_sha256': weights,
        'selected_at_utc': datetime.now(timezone.utc).isoformat(),
        'train_ids': [r['id'] for r in train_rows], 'dev_ids': [r['id'] for r in dev_rows],
        'class_only_development_exact_replay': 27, 'evaluation_rows_used_for_selection': False,
        'noise_used_for_selection': False})
    print('SELECTED', json.dumps({name: {k: c[k] for k in ('weighting', 'feature_source', 'regularization', 'specialist_weight')}
                                 for name, c in selected.items()}), flush=True)


def evaluate():
    checked()
    with experiment_root():
        engine.evaluate()


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'fit', 'evaluate'])
    args = parser.parse_args()
    {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.mode]()
