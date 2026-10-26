"""Train a local-context head using existing speaker partitions only.

Context length, layer and regularization use development evidence; the already
explored Griffith corpus can only evaluate the locked choice, never select it.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from calibrate_nasal_exact_margin import select_exact_feedback
from fit_nasal_context_probe import policy_observations
from nasal_acoustics import MODELS, nasal_group
from nasal_feature_probe import LABELS, LAYERS, assert_speaker_partition, feature_view, fit_ridge, predict_ridge
from probe_nasal_boundaries import BASE, SOURCE as EXTERNAL, sha, summarize_denominator
from train_nasal_feature_probe import load_features, save_json


SOURCE = BASE / 'context-training-v4'
FOLDER = BASE / 'local-context-training-v8'


def prepare():
    if FOLDER.exists():
        raise ValueError('Local-context training plan already frozen')
    FOLDER.mkdir()
    sources = [SOURCE / 'dataset.json', Path(__file__), Path('scripts/extract_nasal_features.py'),
               Path('scripts/nasal_feature_probe.py'), Path('scripts/calibrate_nasal_exact_margin.py')]
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': {str(p): sha(p) for p in sources}, 'encoder': MODELS['phoneme'],
            'contexts_ms': [150, 500], 'layers': [12, 24], 'regularizations': [.001, .01, .1],
            'view': 'trajectory', 'normalization': 'original parent; convolution grid preserved',
            'selection_splits': ['train', 'dev'], 'evaluation_previously_explored': True,
            'ranking': ['development error detections (zero accusations, both directions)',
                        'development correct matches (zero false reassurance)',
                        'balanced label accuracy', 'stronger regularization', 'earlier layer', 'shorter context'],
            'external_corpus_used_for_selection': False}
    save_json(FOLDER / 'plan.json', plan)
    dataset = json.loads((SOURCE / 'dataset.json').read_text())
    for context in plan['contexts_ms']:
        folder = FOLDER / f'local{context}'; folder.mkdir()
        save_json(folder / 'dataset.json', {**dataset, 'context_ms': context,
                  'local_plan_sha256': sha(FOLDER / 'plan.json')})


def checked_plan():
    plan = json.loads((FOLDER / 'plan.json').read_text())
    amendment_path = FOLDER / 'implementation-amendment.json'
    amendment = json.loads(amendment_path.read_text()) if amendment_path.exists() else None
    for p, expected in plan['sources'].items():
        if sha(Path(p)) != expected:
            repair = amendment['repairs'].get(p) if amendment else None
            if repair != {'before': expected, 'after': sha(Path(p))}:
                raise ValueError('Frozen source/implementation changed')
    if amendment and any(sha(Path(p)) != expected for p, expected in amendment['label_sources'].items()):
        raise ValueError('Recovered exclusion label sources changed')
    return plan


def selected_rows(dataset):
    """Recover labels omitted from old exclusion summaries, never drop them.

    Native/teacher rows were selected as correct by the original preparation
    script. Explicit error labels come from the original target manifests.
    """
    labels = {}
    word = json.loads((BASE / 'ise-word-calibration-input.json').read_text())
    for row in word['cases']:
        labels[row['id']] = {'expected_label': nasal_group(row['local']['final']) or 'other'}
    for path, key in [(BASE / 'feedback-v3-holdout/input.json', 'recordings'),
                      (SOURCE / 'input.json', 'records')]:
        for record in json.loads(path.read_text())[key]:
            for target in record['targets']:
                labels[f"{record['uid']}-pos{target['position']}"] = {
                    name: target[name] for name in ('expected_label', 'actual_label')}
    result = list(dataset['rows'])
    for row in dataset['excluded']:
        if row.get('condition') in ('native_reference', 'teacher_correct'):
            restored = {'expected_label': row['actual_label']}
        else:
            restored = labels.get(row['id'])
            if not restored:
                raise ValueError('Excluded target has no auditable label source')
        if 'actual_label' in row and 'actual_label' in restored and row['actual_label'] != restored['actual_label']:
            raise ValueError('Excluded label disagrees with original manifest')
        result.append({**row, **restored})
    if len({r['id'] for r in result}) != len(result):
        raise ValueError('Duplicate selected target')
    return result


def rank(candidates):
    return sorted(candidates, key=lambda c: (-c['development']['correct_error_directions'],
        -c['development']['correct_nasal_matches'], -c['development']['balanced_label_accuracy'],
        -c['regularization'], c['layer'], c['context_ms']))


def fit():
    plan = checked_plan(); path = FOLDER / 'selection.json'
    if path.exists() or (FOLDER / 'ridge-model.npz').exists():
        raise ValueError('Selection already frozen')
    candidates = []; inputs = {}; all_dev_ids = None
    for context in plan['contexts_ms']:
        features, rows, dataset, index = load_features(FOLDER / f'local{context}')
        if index['model'] != plan['encoder'] or index['context_ms'] != context:
            raise ValueError('Wrong encoder or context')
        if dataset['local_plan_sha256'] != sha(FOLDER / 'plan.json'):
            raise ValueError('Dataset bound to a different plan')
        positions = [i for i, r in enumerate(rows) if r['split'] in ('train', 'dev')]
        subset = [rows[i] for i in positions]; values = features[positions]
        assert_speaker_partition(subset)
        train = np.array([r['split'] == 'train' for r in subset]); dev = ~train
        labels = np.array([LABELS.index(r['actual_label']) for r in subset])
        dev_rows = [r for r in subset if r['split'] == 'dev']
        denominator = [r for r in selected_rows(dataset) if r['split'] == 'dev']
        if all_dev_ids is not None and all_dev_ids != {r['id'] for r in denominator}:
            raise ValueError('Context conditions changed the selected development population')
        all_dev_ids = {r['id'] for r in denominator}
        inputs[context] = (values, subset)
        for layer in plan['layers']:
            x = feature_view(values, LAYERS.index(layer), plan['view'])
            for strength in plan['regularizations']:
                model = fit_ridge(x[train], labels[train], strength)
                scores = predict_ridge(model, x[dev])
                review, matching, _, _ = select_exact_feedback(dev_rows, scores)
                review_margin = review['margin'] if review else None
                matching_margin = matching['margin'] if matching else None
                observations = policy_observations(dev_rows, scores, review_margin, matching_margin)
                candidate = {'context_ms': context, 'layer': layer, 'view': plan['view'],
                    'regularization': strength, 'review_margin': review_margin, 'matching_margin': matching_margin,
                    'development': summarize_denominator(denominator, observations),
                    'directions_by_expected': review['directions_by_expected'] if review else {},
                    'api_positive_veto': True}
                candidates.append(candidate)
                print('CANDIDATE', context, layer, strength, candidate['development']['correct_error_directions'],
                      candidate['development']['correct_nasal_matches'], flush=True)
    ranking = rank(candidates); best = ranking[0]
    features, rows = inputs[best['context_ms']]
    training = np.array([r['split'] == 'train' for r in rows])
    labels = np.array([LABELS.index(r['actual_label']) for r in rows])
    x = feature_view(features, LAYERS.index(best['layer']), best['view'])
    model = fit_ridge(x[training], labels[training], best['regularization'])
    weights = FOLDER / 'ridge-model.npz'
    np.savez_compressed(weights, **model); weights.chmod(0o600)
    save_json(path, {'selected_at_utc': datetime.now(timezone.utc).isoformat(), 'selected': best,
        'ranking': ranking, 'weights_sha256': sha(weights), 'plan_sha256': sha(FOLDER / 'plan.json'),
        'feature_index_sha256': {str(c): sha(FOLDER / f'local{c}' / 'feature-index.json') for c in plan['contexts_ms']},
        'train_ids': [r['id'] for r in rows if r['split'] == 'train'],
        'dev_ids': [r['id'] for r in rows if r['split'] == 'dev'],
        'evaluation_rows_used_for_selection': False})
    print('SELECTED', json.dumps(best), flush=True)


def evaluate():
    plan = checked_plan(); output = FOLDER / 'evaluation.json'
    if output.exists():
        raise ValueError('Local-context evaluation frozen')
    selection = json.loads((FOLDER / 'selection.json').read_text()); spec = selection['selected']
    if selection['plan_sha256'] != sha(FOLDER / 'plan.json') or selection['weights_sha256'] != sha(FOLDER / 'ridge-model.npz'):
        raise ValueError('Frozen selection/weights changed')
    with np.load(FOLDER / 'ridge-model.npz', allow_pickle=False) as data:
        model = {k: data[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    reports = {}
    for name, folder in [('existing', FOLDER / f"local{spec['context_ms']}"),
                         ('griffith', BASE / 'context-ablation-v7' / f"api_local{spec['context_ms']}")]:
        features, rows, dataset, index = load_features(folder)
        if index['model'] != plan['encoder'] or index['context_ms'] != spec['context_ms']:
            raise ValueError('Mismatched feature policy')
        if name == 'existing' and selection['feature_index_sha256'][str(spec['context_ms'])] != sha(folder / 'feature-index.json'):
            raise ValueError('Selected training features changed')
        observations = policy_observations(rows, predict_ridge(model,
            feature_view(features, LAYERS.index(spec['layer']), spec['view'])), spec['review_margin'], spec['matching_margin'])
        all_rows = selected_rows(dataset) if name == 'existing' else dataset['rows'] + dataset['excluded']
        groups = {split: summarize_denominator([r for r in all_rows if r['split'] == split],
                  [r for r in observations if r['split'] == split]) for split in sorted({r['split'] for r in all_rows})}
        pure = [r for r in all_rows if r.get('pure_nasal_pair') is True]
        reports[name] = {'all': summarize_denominator(all_rows, observations), 'groups': groups,
            'pure_nasal_pairs': summarize_denominator(pure, [r for r in observations if r['id'] in {v['id'] for v in pure}]),
            'predictions': observations, 'feature_index_sha256': sha(folder / 'feature-index.json')}
        print(name, json.dumps(groups), flush=True)
    save_json(output, {'complete': True, 'selected': spec, 'comparison': reports,
        'selection_sha256': sha(FOLDER / 'selection.json'), 'evaluation_previously_explored': True,
        'limits': ['Development set is small and repeatedly explored.', 'No new blind test, live microphone or deployment evidence.',
                   'Changing context does not establish the cause of any misclassification.']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'fit', 'evaluate'])
    args = parser.parse_args(); {'prepare': prepare, 'fit': fit, 'evaluate': evaluate}[args.mode]()
