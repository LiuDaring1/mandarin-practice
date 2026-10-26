"""Frozen-head context ablation; never a new blind evaluation or a diagnosis.

Original recording normalization and convolution grid are preserved. All
conditions and margins are registered before extracting the local features.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from fit_nasal_context_probe import policy_observations
from nasal_acoustics import MODELS
from nasal_feature_probe import LAYERS, feature_view, predict_ridge
from probe_nasal_boundaries import BASE, FOLDER as BOUNDARY, SOURCE, sha, summarize_denominator
from train_nasal_feature_probe import load_features, save_json


FOLDER = BASE / 'context-ablation-v7'
CONDITIONS = {f'{boundary}_local{margin}': {'boundary': boundary, 'context_ms': margin}
              for boundary in ('api', 'human_clip') for margin in (150, 500)}


def prepare():
    if FOLDER.exists():
        raise ValueError('Context plan already exists; do not silently retune')
    model = BASE / 'context-exact-margin-v5'
    selection = json.loads((model / 'selection.json').read_text())
    sources = [SOURCE / 'dataset.json', BOUNDARY / 'evaluation.json',
               model / 'selection.json', model / 'ridge-model.npz',
               Path(__file__), Path('scripts/extract_nasal_features.py'), Path('scripts/nasal_feature_probe.py')]
    sources += [BOUNDARY / boundary / 'dataset.json' for boundary in ('api', 'human_clip')]
    FOLDER.mkdir()
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': {str(path): sha(path) for path in sources}, 'conditions': CONDITIONS,
            'model': str(model), 'selected': selection['selected'], 'encoder': MODELS['phoneme'],
            'retuning': False, 'post_hoc_diagnostic': True,
            'normalization': 'Original parent waveform, then crop normalized tensor without renormalization.',
            'frame_grid': 'Outward-rounded crop starts at an original convolution-stride boundary.',
            'inference_input': 'Acoustic waveform and geometry only; no labels or reference text.',
            'interpretation': 'Context sensitivity does not by itself prove semantic correction; fixed head may not transfer.'}
    save_json(FOLDER / 'plan.json', plan)
    for name, condition in CONDITIONS.items():
        dataset = json.loads((BOUNDARY / condition['boundary'] / 'dataset.json').read_text())
        folder = FOLDER / name; folder.mkdir()
        save_json(folder / 'dataset.json', {**dataset, 'context_condition': name,
                  'context_plan_sha256': sha(FOLDER / 'plan.json')})


def checked_plan():
    plan = json.loads((FOLDER / 'plan.json').read_text())
    if any(sha(Path(path)) != expected for path, expected in plan['sources'].items()):
        raise ValueError('Frozen source or extractor changed')
    return plan


def evaluate():
    plan = checked_plan()
    output = FOLDER / 'evaluation.json'
    if output.exists():
        raise ValueError('Context evaluation is frozen')
    source = json.loads((SOURCE / 'dataset.json').read_text())
    all_rows = source['rows'] + source['excluded']
    baseline = json.loads((BOUNDARY / 'evaluation.json').read_text())['comparison']
    with np.load(Path(plan['model']) / 'ridge-model.npz', allow_pickle=False) as stored:
        model = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    spec = plan['selected']; reports = {}
    for name, condition in plan['conditions'].items():
        features, rows, dataset, index = load_features(FOLDER / name)
        if dataset['context_plan_sha256'] != sha(FOLDER / 'plan.json'):
            raise ValueError('Dataset was prepared against a different plan')
        if index['model'] != plan['encoder'] or index['context_ms'] != condition['context_ms']:
            raise ValueError('Wrong model/context')
        if index['preprocessing'] != 'parent-normalization-grid-preserved-local-context-v1':
            raise ValueError('Normalization/frame-grid confound')
        observations = policy_observations(rows,
            predict_ridge(model, feature_view(features, LAYERS.index(spec['layer']), spec['view'])),
            spec['review_margin'], spec['matching_margin'])
        previous = {r['id']: r for r in baseline[condition['boundary']]['predictions']}
        common_ids = {r['id'] for r in observations} & set(previous)
        common_rows = [r for r in all_rows if r['id'] in common_ids]
        pure_rows = [r for r in all_rows if r.get('pure_nasal_pair') is True]
        reports[name] = {'all': summarize_denominator(all_rows, observations),
            'pure_nasal_pairs': summarize_denominator(pure_rows, [r for r in observations if r['id'] in {v['id'] for v in pure_rows}]),
            'common_targets': {'baseline': summarize_denominator(common_rows, [previous[i] for i in common_ids]),
                               'condition': summarize_denominator(common_rows, [r for r in observations if r['id'] in common_ids])},
            'pooling_exclusions': index['excluded'], 'predictions': observations,
            'prior_false_reassurance': [r for r in observations if previous.get(r['id'], {}).get('candidate_nasal_match') and previous[r['id']]['actual'] != previous[r['id']]['expected']]}
    save_json(output, {'complete': True, 'post_hoc_diagnostic': True,
                      'plan_sha256': sha(FOLDER / 'plan.json'), 'comparison': reports})
    for name, report in reports.items():
        print(name, json.dumps(report['all']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'evaluate'])
    args = parser.parse_args()
    {'prepare': prepare, 'evaluate': evaluate}[args.mode]()
