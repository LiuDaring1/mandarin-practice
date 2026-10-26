"""Controlled boundary sensitivity of a frozen nasal classifier.

All conditions keep the waveform, encoder, head, labels and margins fixed.
Human boundaries are a post-hoc diagnostic, not a deployable inference input.
No excluded target disappears from the selected-target denominator.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from audit_nasal_sentence_timing import character_interval
from evaluate_nasal_external_probe import content_gate
from fit_nasal_context_probe import policy_observations
from nasal_feature_probe import LAYERS, feature_view, predict_ridge
from train_nasal_feature_probe import load_features, save_json, summarize


BASE = Path('data/derived/nasal-acoustic-validation')
SOURCE = BASE / 'griffith-external-v2'
FOLDER = BASE / 'boundary-probe-v6'
CONDITIONS = ('api', 'human_clip', 'automatic_clip', 'human_rescale', 'automatic_rescale')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_bounds(original, syllable, method):
    """Use only geometry, never expected/actual nasal labels or model scores."""
    if syllable is None:
        return None
    a, b = original['syllable']; v, w = original['vowel']; s, e = syllable
    if not np.isfinite([a, b, v, w, s, e]).all() or not 0 <= a <= v < w <= b or not 0 <= s < e:
        raise ValueError('Invalid interval geometry')
    if method == 'clip':
        left, right = max(v, s), min(w, e)
    elif method == 'rescale':
        left, right = s + (v - a) / (b - a) * (e - s), s + (w - a) / (b - a) * (e - s)
    else:
        raise ValueError('Unknown boundary method')
    if not left < right:
        return None  # No fabricated padding or fallback to a different condition.
    return {'syllable': [s, e], 'vowel': [left, right]}


def summarize_denominator(all_rows, observations):
    lookup = {r['id']: r for r in all_rows}
    observed_ids = [r['id'] for r in observations]
    if len(set(observed_ids)) != len(observed_ids) or not set(observed_ids) <= set(lookup):
        raise ValueError('Duplicate or unselected prediction')
    result = summarize(observations)
    missing = [r for r in all_rows if r['id'] not in set(observed_ids)]
    errors = [r for r in all_rows if r['expected_label'] != r['actual_label']]
    normal = [r for r in all_rows if r['expected_label'] == r['actual_label']]
    result.update(selected_targets=len(all_rows), scored_targets=len(observations),
                  unavailable_targets=len(missing), selected_errors=len(errors), selected_normal=len(normal),
                  unavailable_errors=sum(r['expected_label'] != r['actual_label'] for r in missing),
                  unavailable_normal=sum(r['expected_label'] == r['actual_label'] for r in missing),
                  missed_selected_errors=len(errors) - result['correct_error_directions'],
                  unknown_selected_targets=result['uncertain_nasal_targets'] + len(missing))
    return result


def freeze_plan():
    path = FOLDER / 'plan.json'
    if path.exists():
        raise ValueError('Boundary experiment plan is frozen')
    model = BASE / 'context-exact-margin-v5'
    selection = json.loads((model / 'selection.json').read_text())
    if sha(model / 'ridge-model.npz') != selection['weights_sha256']:
        raise ValueError('Frozen head changed')
    save_json(path, {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'post_hoc_diagnostic': True, 'conditions': CONDITIONS,
        'source_dataset_sha256': sha(SOURCE / 'dataset.json'), 'source_input_sha256': sha(SOURCE / 'input.json'),
        'source_evaluation_sha256': sha(SOURCE / 'exact-evaluation.json'),
        'source_content_sha256': sha(SOURCE / 'content-audit.json'),
        'model': str(model), 'selection_sha256': sha(model / 'selection.json'),
        'weights_sha256': sha(model / 'ridge-model.npz'), 'selected': selection['selected'],
        'clip_rule': 'Intersect the existing API vowel with the replacement syllable; empty intersection is unknown.',
        'rescale_rule': 'Preserve API vowel fractional position within its syllable, mapped affinely into replacement syllable.',
        'automatic_rule': 'Pinned Qwen forced aligner; exact full-character sequence and existing .08-2 s interval validity.',
        'retuning': False, 'waveform_or_labels_changed': False,
        'reporting': 'All five conditions, total selected denominator, common-target comparisons; no best-condition claim.'})


def checked_plan():
    plan = json.loads((FOLDER / 'plan.json').read_text())
    for path, key in [(SOURCE / 'dataset.json', 'source_dataset_sha256'), (SOURCE / 'input.json', 'source_input_sha256'),
                      (SOURCE / 'exact-evaluation.json', 'source_evaluation_sha256'), (SOURCE / 'content-audit.json', 'source_content_sha256'),
                      (Path(plan['model']) / 'selection.json', 'selection_sha256'), (Path(plan['model']) / 'ridge-model.npz', 'weights_sha256')]:
        if sha(path) != plan[key]:
            raise ValueError('Frozen source/model changed')
    return plan


def prepare():
    checked_plan()
    dataset = json.loads((SOURCE / 'dataset.json').read_text())
    manifest = json.loads((SOURCE / 'input.json').read_text())
    index = json.loads((FOLDER / 'independent-alignment-index.json').read_text())
    if index.get('complete') is not True:
        raise ValueError('Automatic alignment incomplete')
    alignment = {r['uid']: json.loads(Path(r['cache']).read_text()) for r in index['records']}
    records = {r['uid']: r for r in manifest['records']}
    for condition in CONDITIONS:
        folder = FOLDER / condition
        if folder.exists():
            raise ValueError('Prepared boundary condition already exists')
        folder.mkdir()
        rows = []; excluded = list(dataset['excluded'])
        for row in dataset['rows']:
            if condition == 'api':
                bounds = row['bounds']
            else:
                source, method = condition.split('_')
                if source == 'human':
                    interval = row['human_syllable']
                else:
                    uid = row['id'].rsplit('-pos', 1)[0]
                    stored = alignment[uid]; record = records[uid]
                    if sha(Path(row['audio'])) != stored['audio_sha256']:
                        raise ValueError('Audio changed after automatic alignment')
                    interval = character_interval(stored['items'], row['reference'], row['position'], record['duration'])
                bounds = replace_bounds(row['bounds'], interval, method)
            if bounds is None:
                excluded.append({**row, 'reason': 'replacement_interval_unavailable_or_disjoint'})
            else:
                rows.append({**row, 'bounds': bounds, 'original_bounds': row['bounds'], 'boundary_condition': condition})
        if len(rows) + len(excluded) != 140:
            raise ValueError('Selected target denominator changed')
        save_json(folder / 'dataset.json', {**dataset, 'rows': rows, 'excluded': excluded,
                  'boundary_condition': condition, 'boundary_plan_sha256': sha(FOLDER / 'plan.json'),
                  'post_hoc_diagnostic': True, 'human_timing_used': condition.startswith('human')})
        print(condition, 'available geometry', len(rows), 'excluded', len(excluded), flush=True)


def evaluate():
    plan = checked_plan(); output = FOLDER / 'evaluation.json'
    if output.exists():
        raise ValueError('Boundary evaluation is frozen')
    dataset = json.loads((SOURCE / 'dataset.json').read_text())
    all_rows = dataset['rows'] + dataset['excluded']
    content = {r['id']: r['state'] for r in json.loads((SOURCE / 'content-audit.json').read_text())['rows']}
    original_eval = json.loads((SOURCE / 'exact-evaluation.json').read_text())['comparison']['context-exact-margin-v5']['predictions']
    original = {r['id']: r for r in original_eval}
    with np.load(Path(plan['model']) / 'ridge-model.npz', allow_pickle=False) as stored:
        model = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
    spec = plan['selected']; reports = {}
    for condition in CONDITIONS:
        features, rows, prepared, index = load_features(FOLDER / condition)
        if prepared['boundary_plan_sha256'] != sha(FOLDER / 'plan.json'):
            raise ValueError('Prepared condition bound to a different plan')
        if index['model']['repo'] != 'facebook/wav2vec2-xlsr-53-espeak-cv-ft':
            raise ValueError('Wrong encoder for frozen head')
        x = feature_view(features, LAYERS.index(spec['layer']), spec['view'])
        observations = policy_observations(rows, predict_ridge(model, x), spec['review_margin'], spec['matching_margin'])
        if condition == 'api':
            for obs in observations:
                if obs['predicted'] != original[obs['id']]['predicted'] or not np.allclose(obs['scores'], original[obs['id']]['scores'], rtol=0, atol=1e-9):
                    raise ValueError('Unchanged API-boundary replay differs from baseline')
        ids = {r['id'] for r in observations}
        common = [r for r in all_rows if r['id'] in ids and r['id'] in original]
        pure = [r for r in all_rows if r.get('pure_nasal_pair') is True]
        gated = [content_gate(r, content.get(r['id'], 'unavailable')) for r in observations]
        reports[condition] = {'all': summarize_denominator(all_rows, observations),
            'pure_nasal_pairs': summarize_denominator(pure, [o for o in observations if o['id'] in {r['id'] for r in pure}]),
            'with_content_gate': summarize_denominator(all_rows, gated),
            'common_targets': {'baseline': summarize_denominator(common, [original[r['id']] for r in common]),
                               'condition': summarize_denominator(common, [r for r in observations if r['id'] in {v['id'] for v in common}])},
            'geometry_exclusions': dict(Counter(r['reason'] for r in prepared['excluded'])),
            'pooling_exclusions': index['excluded'], 'predictions': observations,
            'prior_false_reassurance': [r for r in observations if original.get(r['id'], {}).get('candidate_nasal_match') and original[r['id']]['actual'] != original[r['id']]['expected']]}
    report = {'complete': True, 'post_hoc_diagnostic': True, 'plan_sha256': sha(FOLDER / 'plan.json'),
              'comparison': reports, 'limits': ['No new blind test or deployed feedback.',
              'Human bounds are not available at runtime and are not perfect phoneme boundaries.',
              'Rescaling/clipping may change the feature distribution; no retraining or threshold adjustment.']}
    save_json(output, report)
    for condition, report in reports.items():
        print(condition, json.dumps(report['all'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['plan', 'prepare', 'evaluate'])
    args = parser.parse_args()
    {'plan': freeze_plan, 'prepare': prepare, 'evaluate': evaluate}[args.mode]()
