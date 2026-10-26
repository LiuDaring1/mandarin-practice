"""Calibrate a frozen head at observed development score boundaries.

The coarse .75/1.0 grid can miss a valid operating interval. This separate
experiment changes no features or weights and never receives evaluation labels.
Zero observed development errors is not a population guarantee.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from fit_nasal_context_probe import policy_observations, grouped
from nasal_feature_probe import LAYERS, feature_view, predict_ridge
from train_nasal_feature_probe import load_features, save_json, summarize


def select_exact_feedback(rows, scores):
    if not rows or any(r['split'] != 'dev' for r in rows):
        raise ValueError('Exact margin calibration requires development rows only')
    scores = np.asarray(scores)
    if scores.shape != (len(rows), 3) or not np.isfinite(scores).all():
        raise ValueError('Invalid development scores')
    ordered = np.sort(scores, axis=1)
    gaps = ordered[:, -1] - ordered[:, -2]
    margins = sorted({0., *(float(np.nextafter(g, np.inf)) for g in gaps)})
    review_table = []; matching_table = []
    for margin in margins:
        observations = policy_observations(rows, scores, margin, None)
        directions = {group: sum(o['candidate_nasal_change'] and o['predicted'] == o['actual']
                                 and o['expected'] == group for o in observations) for group in ('front', 'back')}
        review_table.append({'margin': margin, **summarize(observations), 'directions_by_expected': directions})
        matching_table.append({'margin': margin, **summarize(policy_observations(rows, scores, None, margin))})
    eligible = [r for r in review_table if r['false_nasal_accusations'] == 0 and r['correct_error_directions'] >= 3
                and all(r['directions_by_expected'].values())]
    review = max(eligible, key=lambda r: (r['correct_error_directions'], -r['margin'])) if eligible else None
    eligible = [r for r in matching_table if r['false_reassurances'] == 0 and r['correct_nasal_matches'] >= 5]
    matching = max(eligible, key=lambda r: (r['correct_nasal_matches'], -r['margin'])) if eligible else None
    return review, matching, review_table, matching_table


def main():
    base = Path('data/derived/nasal-acoustic-validation')
    source = base / 'context-training-v4'; output = base / 'context-exact-margin-v5'
    if output.exists():
        raise ValueError('Exact-boundary calibration is frozen')
    features, rows, _, index = load_features(source)
    selection = json.loads((source / 'selection.json').read_text())
    weights = source / 'ridge-model.npz'
    if hashlib.sha256(weights.read_bytes()).hexdigest() != selection['weights_sha256']:
        raise ValueError('Frozen head changed')
    positions = [i for i, r in enumerate(rows) if r['split'] == 'dev']
    dev_rows = [rows[i] for i in positions]
    spec = selection['selected']
    x = feature_view(features[positions], LAYERS.index(spec['layer']), spec['view'])
    with np.load(weights, allow_pickle=False) as stored:
        model = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    review, matching, review_table, matching_table = select_exact_feedback(dev_rows, predict_ridge(model, x))
    selected = {**spec, 'review_margin': review['margin'] if review else None,
                'matching_margin': matching['margin'] if matching else None}
    output.mkdir()
    shutil.copyfile(weights, output / 'ridge-model.npz'); (output / 'ridge-model.npz').chmod(0o600)
    save_json(output / 'selection.json', {**selection, 'selected': selected,
              'selected_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_selection_sha256': hashlib.sha256((source / 'selection.json').read_bytes()).hexdigest(),
              'development_review_table': review_table, 'development_matching_table': matching_table,
              'evaluation_rows_used_for_selection': False,
              'margin_rule': 'Zero observed development risk and both error directions; candidates immediately above every development score gap.',
              'weights_changed': False, 'dataset_sha256': index['dataset_sha256']})
    print(json.dumps({'selected': selected, 'development_review': review, 'development_matching': matching}), flush=True)


def evaluate_context():
    base = Path('data/derived/nasal-acoustic-validation')
    folder = base / 'context-exact-margin-v5'
    output = folder / 'context-evaluation.json'
    if output.exists():
        raise ValueError('Exact-margin context evaluation is frozen')
    selection = json.loads((folder / 'selection.json').read_text())
    features, rows, dataset, index = load_features(base / 'context-training-v4')
    weights = folder / 'ridge-model.npz'
    if selection['dataset_sha256'] != index['dataset_sha256'] or hashlib.sha256(weights.read_bytes()).hexdigest() != selection['weights_sha256']:
        raise ValueError('Frozen dataset or classifier changed')
    with np.load(weights, allow_pickle=False) as stored:
        model = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    spec = selection['selected']
    x = feature_view(features, LAYERS.index(spec['layer']), spec['view'])
    observations = policy_observations(rows, predict_ridge(model, x), spec['review_margin'], spec['matching_margin'])
    report = {'complete': True, 'selected': spec, 'groups': grouped(observations), 'predictions': observations,
              'excluded_targets': len(dataset['excluded']) + len(index['excluded']),
              'limits': ['Context evaluation rows were explored in the prior v3/v4 experiment.',
                         'Exact margins selected on development rows only; independent corpus evaluation separate.']}
    save_json(output, report)
    print(json.dumps(report['groups'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evaluate-context', action='store_true')
    args = parser.parse_args()
    (evaluate_context if args.evaluate_context else main)()
