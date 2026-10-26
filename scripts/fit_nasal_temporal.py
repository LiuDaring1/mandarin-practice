"""Select a temporal acoustic representation using train/dev speakers only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from calibrate_nasal_exact_margin import select_exact_feedback
from fit_nasal_context_probe import policy_observations
from fit_nasal_local_context import selected_rows
from nasal_acoustics import MODELS
from nasal_feature_probe import LABELS, assert_speaker_partition, fit_ridge, predict_ridge
from nasal_temporal_features import VIEWS
from probe_nasal_boundaries import BASE, sha, summarize_denominator
from train_nasal_feature_probe import save_json, summarize


FOLDER = BASE / 'temporal-training-v9'
ORIGINAL = BASE / 'context-training-v4'
EXTERNAL = BASE / 'griffith-external-v2'
BASELINE = BASE / 'local-context-training-v8'


def prepare():
    if FOLDER.exists():
        raise ValueError('Temporal plan already frozen')
    baseline = json.loads((BASELINE / 'selection.json').read_text())
    if (baseline['selected']['context_ms'], baseline['selected']['layer']) != (150, 12):
        raise ValueError('Unexpected v8 architecture')
    sources = [ORIGINAL / 'dataset.json', EXTERNAL / 'dataset.json',
        BASELINE / 'selection.json', BASELINE / 'ridge-model.npz', BASELINE / 'evaluation.json',
        BASELINE / 'local150/feature-index.json', BASE / 'context-ablation-v7/api_local150/feature-index.json',
        BASE / 'ise-word-calibration-input.json', BASE / 'feedback-v3-holdout/input.json', ORIGINAL / 'input.json',
        Path(__file__), Path('scripts/nasal_temporal_features.py'), Path('scripts/extract_nasal_temporal.py'),
        Path('scripts/nasal_feature_probe.py'), Path('scripts/calibrate_nasal_exact_margin.py')]
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': {str(p): sha(p) for p in sources},
        'encoder': MODELS['phoneme'], 'context_ms': 150, 'layer': 12, 'views': VIEWS,
        'regularizations': [.001, .01, .1, 1.], 'selection_splits': ['train', 'dev'],
        'baseline_replay': 'All available features and the trajectory2/0.1 fitted scores must match v8.',
        'ranking': ['zero observed development risk, both error directions, highest error detection',
                    'highest correctly matched normal count without false reassurance', 'balanced label accuracy',
                    'stronger regularization', 'simpler predeclared representation order'],
        'evaluation_previously_explored': True, 'external_used_for_selection': False}
    FOLDER.mkdir(); save_json(FOLDER / 'plan.json', plan)
    for name, source, baseline_folder in [('existing', ORIGINAL, BASELINE / 'local150'),
                                         ('griffith', EXTERNAL, BASE / 'context-ablation-v7/api_local150')]:
        dataset = json.loads((source / 'dataset.json').read_text())
        if name == 'existing':
            recovered = {r['id']: r for r in selected_rows(dataset)}
            dataset['excluded'] = [recovered[r['id']] for r in dataset['excluded']]
        folder = FOLDER / name; folder.mkdir()
        save_json(folder / 'dataset.json', {**dataset, 'baseline_folder': str(baseline_folder),
                  'temporal_plan_sha256': sha(FOLDER / 'plan.json')})


def checked_plan():
    plan = json.loads((FOLDER / 'plan.json').read_text())
    if any(sha(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('Frozen temporal source changed')
    return plan


def load(folder):
    dataset = json.loads((folder / 'dataset.json').read_text())
    index = json.loads((folder / 'feature-index.json').read_text())
    if index.get('complete') is not True or index['dataset_sha256'] != sha(folder / 'dataset.json'):
        raise ValueError('Incomplete or stale temporal index')
    plan = checked_plan()
    if index['model'] != plan['encoder'] or (index['layer'], index['context_ms']) != (plan['layer'], plan['context_ms']):
        raise ValueError('Mismatched temporal encoder')
    if dataset['temporal_plan_sha256'] != sha(FOLDER / 'plan.json'):
        raise ValueError('Dataset plan mismatch')
    lookup = {r['id']: r for r in dataset['rows']}
    rows = []; features = {v: [] for v in VIEWS}
    for record in index['rows']:
        with np.load(record['cache'], allow_pickle=False) as stored:
            if str(stored['ids'][record['index']]) != record['id']:
                raise ValueError('Temporal feature identity mismatch')
            for view in VIEWS:
                features[view].append(stored[view][record['index']])
            rows.append(lookup[record['id']])
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate temporal feature')
    assert_speaker_partition(rows)
    return {v: np.stack(items) for v, items in features.items()}, rows, dataset, index


def fit():
    plan = checked_plan(); output = FOLDER / 'selection.json'
    if output.exists() or (FOLDER / 'ridge-model.npz').exists():
        raise ValueError('Temporal head already frozen')
    features, rows, dataset, index = load(FOLDER / 'existing')
    positions = [i for i, r in enumerate(rows) if r['split'] in ('train', 'dev')]
    subset = [rows[i] for i in positions]; assert_speaker_partition(subset)
    training = np.array([r['split'] == 'train' for r in subset]); dev = ~training
    labels = np.array([LABELS.index(r['actual_label']) for r in subset])
    dev_rows = [r for r in subset if r['split'] == 'dev']
    denominator = [r for r in dataset['rows'] + dataset['excluded'] if r['split'] == 'dev']
    baseline = json.loads((BASELINE / 'evaluation.json').read_text())['comparison']['existing']['predictions']
    baseline_dev = {r['id']: r for r in baseline if r['split'] == 'dev'}
    candidates = []; baseline_difference = None
    for view in plan['views']:
        x = features[view][positions]
        for strength in plan['regularizations']:
            model = fit_ridge(x[training], labels[training], strength)
            scores = predict_ridge(model, x[dev])
            if view == 'trajectory2' and strength == .1:
                reference = np.array([baseline_dev[r['id']]['scores'] for r in dev_rows])
                baseline_difference = float(np.max(np.abs(scores-reference)))
                if baseline_difference > 1e-9:
                    raise ValueError('Unchanged fitted baseline differs from v8')
            review, matching, _, _ = select_exact_feedback(dev_rows, scores)
            review_margin = review['margin'] if review else None
            matching_margin = matching['margin'] if matching else None
            observations = policy_observations(dev_rows, scores, review_margin, matching_margin)
            candidate = {'view': view, 'regularization': strength, 'review_margin': review_margin,
                'matching_margin': matching_margin, 'development': summarize_denominator(denominator, observations),
                'directions_by_expected': review['directions_by_expected'] if review else {}, 'api_positive_veto': True}
            candidates.append(candidate)
            print('CANDIDATE', view, strength, candidate['development']['correct_error_directions'],
                  candidate['development']['correct_nasal_matches'], flush=True)
    candidates.sort(key=lambda c: (-c['development']['correct_error_directions'],
        -c['development']['correct_nasal_matches'], -c['development']['balanced_label_accuracy'],
        -c['regularization'], plan['views'].index(c['view'])))
    best = candidates[0]; x = features[best['view']][positions]
    model = fit_ridge(x[training], labels[training], best['regularization'])
    weights = FOLDER / 'ridge-model.npz'; np.savez_compressed(weights, **model); weights.chmod(0o600)
    save_json(output, {'selected_at_utc': datetime.now(timezone.utc).isoformat(), 'selected': best,
        'ranking': candidates, 'weights_sha256': sha(weights), 'plan_sha256': sha(FOLDER / 'plan.json'),
        'feature_index_sha256': sha(FOLDER / 'existing/feature-index.json'),
        'baseline_max_score_difference': baseline_difference, 'evaluation_rows_used_for_selection': False,
        'train_ids': [r['id'] for r in subset if r['split'] == 'train'], 'dev_ids': [r['id'] for r in dev_rows]})
    print('SELECTED', json.dumps(best), flush=True)


def evaluate():
    checked_plan(); output = FOLDER / 'evaluation.json'
    if output.exists():
        raise ValueError('Temporal evaluation already frozen')
    selection = json.loads((FOLDER / 'selection.json').read_text()); spec = selection['selected']
    if selection['plan_sha256'] != sha(FOLDER / 'plan.json') or selection['weights_sha256'] != sha(FOLDER / 'ridge-model.npz'):
        raise ValueError('Frozen temporal selection changed')
    with np.load(FOLDER / 'ridge-model.npz', allow_pickle=False) as stored:
        model = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    comparison = {}
    for name in ('existing', 'griffith'):
        folder = FOLDER / name; features, rows, dataset, index = load(folder)
        if name == 'existing' and selection['feature_index_sha256'] != sha(folder / 'feature-index.json'):
            raise ValueError('Temporal training features changed')
        observations = policy_observations(rows, predict_ridge(model, features[spec['view']]), spec['review_margin'], spec['matching_margin'])
        selected = dataset['rows'] + dataset['excluded']
        pure = [r for r in selected if r.get('pure_nasal_pair') is True]
        heldout = [r for r in selected if r['split'] not in ('train', 'dev')]
        comparison[name] = {'groups': {split: summarize_denominator([r for r in selected if r['split'] == split],
            [r for r in observations if r['split'] == split]) for split in sorted({r['split'] for r in selected})},
            'evaluation_only': summarize_denominator(heldout, [r for r in observations if r['split'] not in ('train', 'dev')]),
            'pure_nasal_pairs': summarize_denominator(pure, [r for r in observations if r['id'] in {v['id'] for v in pure}]),
            'predictions': observations, 'feature_index_sha256': sha(folder / 'feature-index.json')}
        print(name, json.dumps(comparison[name]['evaluation_only']), flush=True)
    save_json(output, {'complete': True, 'selected': spec, 'comparison': comparison,
        'selection_sha256': sha(FOLDER / 'selection.json'), 'evaluation_previously_explored': True,
        'limits': ['No new blind test; selected only on existing development speakers.',
                   'Interpolated positions are not independent acoustic observations.',
                   'No deployment, live microphone or noise validation.']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'fit', 'evaluate'])
    args = parser.parse_args(); {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.mode]()
