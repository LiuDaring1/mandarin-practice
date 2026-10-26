"""Freeze, calibrate on dev only, then evaluate ZIPA contextual phone evidence."""
import argparse
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path

import numpy as np

from calibrate_nasal_exact_margin import select_exact_feedback
from fit_nasal_context_probe import policy_observations
from probe_nasal_boundaries import summarize_denominator
from train_nasal_feature_probe import save_json
from zipa_context import BASE, FOLDER, digest


def prepare():
    if FOLDER.exists():
        raise ValueError('ZIPA context plan exists')
    sources = [BASE / 'zipa-v1' / f'{c}-dataset.json' for c in ('existing', 'griffith')]
    sources += [Path(__file__), Path('scripts/zipa_context.py'), Path('scripts/zipa_nasal.py'),
                Path('scripts/nasal_acoustics.py'), Path('scripts/calibrate_nasal_exact_margin.py'),
                BASE / 'zipa-v1/model/source.json']
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': {str(p): digest(p) for p in sources},
            'policies': [{'region': r, 'extension_ms': e, 'method': m}
                         for r, e, m in product(('vowel', 'syllable'), (0, 80), ('terminal', 'peak'))],
            'selection_splits': ['dev'], 'model_training': False, 'maximum_context_seconds': 20,
            'ranking': ['dev error detections with zero observed false accusations and both directions',
                        'dev normal matches with zero false reassurance', 'original policy order'],
            'grid_source_commit': '21e9e8aa4cc6c130cb05d836a1979886f9245302',
            'verified_output_lengths': [[100, 46], [200, 96], [500, 246]],
            'nominal_grid': {'first_center_seconds': .045, 'stride_seconds': .02},
            'preflight_failure_archive': 'zipa-context-v2-preflight-failed',
            'grid_source_urls': ['https://github.com/lingjzhu/zipa/blob/21e9e8aa4cc6c130cb05d836a1979886f9245302/zipformer_crctc/subsampling.py',
                                 'https://github.com/lingjzhu/zipa/blob/21e9e8aa4cc6c130cb05d836a1979886f9245302/zipformer_crctc/zipformer.py'],
            'evaluation_previously_explored': True, 'production_change': False}
    FOLDER.mkdir(); save_json(FOLDER / 'plan.json', plan)


def observe(dataset, predictions, policy, review, matching, splits=None):
    lookup = {r['id']: r for r in predictions if r['policy'] == policy and not r.get('unavailable')}
    rows = [r for r in dataset['rows'] if r['id'] in lookup and (splits is None or r['split'] in splits)]
    scores = np.array([lookup[r['id']]['scores'] for r in rows], dtype=float).reshape(-1, 3)
    return rows, scores, policy_observations(rows, scores, review, matching)


def evaluate():
    output = FOLDER / 'evaluation.json'
    if output.exists() or (FOLDER / 'selection.json').exists():
        raise ValueError('Context selection/evaluation frozen')
    plan = json.loads((FOLDER / 'plan.json').read_text())
    if any(digest(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('Frozen sources changed')
    inference = json.loads((FOLDER / 'predictions.json').read_text())
    if inference.get('complete') is not True or inference['plan_sha256'] != digest(FOLDER / 'plan.json'):
        raise ValueError('Incomplete or stale inference')
    datasets = {c: json.loads((BASE / 'zipa-v1' / f'{c}-dataset.json').read_text()) for c in ('existing', 'griffith')}
    dev = [r for r in datasets['existing']['rows'] + datasets['existing']['excluded'] if r['split'] == 'dev']
    candidates = []
    for policy in plan['policies']:
        rows, scores, _ = observe(datasets['existing'], inference['cohorts']['existing'], policy, None, None, {'dev'})
        review, matching, _, _ = select_exact_feedback(rows, scores)
        r = review['margin'] if review else None; m = matching['margin'] if matching else None
        candidates.append({'policy': policy, 'review_margin': r, 'matching_margin': m,
                           'development': summarize_denominator(dev, policy_observations(rows, scores, r, m))})
    candidates.sort(key=lambda c: (-c['development']['correct_error_directions'], -c['development']['correct_nasal_matches']))
    chosen = candidates[0]
    save_json(FOLDER / 'selection.json', {'selected_at_utc': datetime.now(timezone.utc).isoformat(),
              'selected': chosen, 'ranking': candidates, 'evaluation_rows_used_for_selection': False,
              'plan_sha256': digest(FOLDER / 'plan.json'), 'predictions_sha256': digest(FOLDER / 'predictions.json')})
    comparison = {}
    for name, dataset in datasets.items():
        _, _, observed = observe(dataset, inference['cohorts'][name], chosen['policy'], chosen['review_margin'], chosen['matching_margin'])
        rows = dataset['rows'] + dataset['excluded']; heldout = [r for r in rows if r['split'] not in ('train', 'dev')]
        pure = [r for r in rows if r.get('pure_nasal_pair') is True]
        comparison[name] = {'evaluation_only': summarize_denominator(heldout, [r for r in observed if r['split'] not in ('train', 'dev')]),
                            'pure_nasal_pairs': summarize_denominator(pure, [r for r in observed if r['id'] in {p['id'] for p in pure}]),
                            'predictions': observed}
    report = {'complete': True, 'selected': chosen, 'comparison': comparison,
              'evaluation_previously_explored': True, 'selection_sha256': digest(FOLDER / 'selection.json'),
              'limits': ['Approximate output grid and API target geometry, not human phone boundaries.',
                         'No new blind data, live device or noise validation.',
                         'Peaks are acoustic ranking signals, not pronunciation correctness probabilities.']}
    save_json(output, report)
    print('SELECTED', json.dumps(chosen), flush=True)
    for name, values in comparison.items():
        print(name, json.dumps(values['evaluation_only']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'evaluate'])
    args = parser.parse_args(); {'prepare': prepare, 'evaluate': evaluate}[args.mode]()
