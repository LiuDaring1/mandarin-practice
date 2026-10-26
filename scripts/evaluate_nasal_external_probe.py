"""Evaluate frozen nasal heads on new speakers from an independent corpus.

Human syllable times are an alignment audit, never an inference input or a
post-hoc way of removing missed errors. Evaluation cannot refit or recalibrate.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from audit_nasal_sentence_timing import compare_intervals
from fit_nasal_context_probe import policy_observations
from nasal_feature_probe import LAYERS, feature_view, predict_ridge
from train_nasal_feature_probe import load_features, save_json, summarize


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_gate(observation, location_state):
    """Uncertain content location vetoes both claims, never supplies a label."""
    return {**observation, 'content_location_state': location_state,
            'candidate_nasal_change': bool(observation['candidate_nasal_change'] and location_state == 'unique_match'),
            'candidate_nasal_match': bool(observation['candidate_nasal_match'] and location_state == 'unique_match')}


def freeze_models(folder, include_exact=False):
    output = folder / ('exact-model-plan.json' if include_exact else 'model-plan.json')
    if output.exists():
        raise ValueError('External evaluation models already frozen')
    models = []
    names = ['feature-feedback-v3', 'context-training-v4']
    if include_exact:
        names.append('context-exact-margin-v5')
    for name in names:
        source = folder.parent / name
        selection = json.loads((source / 'selection.json').read_text())
        weights = source / 'ridge-model.npz'
        if sha(weights) != selection['weights_sha256']:
            raise ValueError('Selected model weights changed')
        models.append({'name': name, 'selection_path': str(source / 'selection.json'),
                       'selection_sha256': sha(source / 'selection.json'),
                       'weights': str(weights), 'weights_sha256': sha(weights)})
    content_path = folder / 'content-audit.json'
    content = json.loads(content_path.read_text())
    if content.get('complete') is not True or content.get('reference_prompt') is not False:
        raise ValueError('Independent free-transcript audit is incomplete')
    save_json(output, {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'models': models,
                       'input_sha256': sha(folder / 'input.json'),
                       'content_audit_sha256': sha(content_path),
                       'policy': 'Frozen acoustic decisions, API conflicts veto positive claims only.',
                       'additional_location_policy': 'Report separately: both claims require a unique free-transcript target location. No acoustic threshold changes.',
                       'human_timing': 'Audit only; never filter errors or supply inference features.',
                       'refitting_or_threshold_selection': False})


def evaluate(folder, include_exact=False):
    output = folder / ('exact-evaluation.json' if include_exact else 'evaluation.json')
    if output.exists():
        raise ValueError('External evaluation already frozen')
    plan = json.loads((folder / ('exact-model-plan.json' if include_exact else 'model-plan.json')).read_text())
    if sha(folder / 'input.json') != plan['input_sha256']:
        raise ValueError('Evaluation selection changed')
    if sha(folder / 'content-audit.json') != plan['content_audit_sha256']:
        raise ValueError('Frozen content audit changed')
    content = {r['id']: r['state'] for r in json.loads((folder / 'content-audit.json').read_text())['rows']}
    features, rows, dataset, index = load_features(folder)
    if not dataset.get('evaluation_only') or any(r['split'] != 'external' for r in rows):
        raise ValueError('External evaluation cannot contain fitting rows')
    if index['model']['repo'] != 'facebook/wav2vec2-xlsr-53-espeak-cv-ft':
        raise ValueError('Wrong feature encoder')
    speakers = {r['speaker'] for r in rows}
    for name in ('feature-classifier-v2-phoneme', 'context-training-v4'):
        fit = json.loads((folder.parent / name / 'dataset.json').read_text())
        if speakers.intersection(r['speaker'] for r in fit['rows']):
            raise ValueError('External speaker also occurs in earlier data')
    reports = {}
    for model in plan['models']:
        selection_path = Path(model['selection_path']); weights = Path(model['weights'])
        if sha(selection_path) != model['selection_sha256'] or sha(weights) != model['weights_sha256']:
            raise ValueError('Frozen model/selection changed')
        selected = json.loads(selection_path.read_text())['selected']
        x = feature_view(features, LAYERS.index(selected['layer']), selected['view'])
        with np.load(weights, allow_pickle=False) as stored:
            head = {k: stored[k] for k in ('mean', 'scale', 'coefficient', 'intercept')}
        observations = policy_observations(rows, predict_ridge(head, x),
                                          selected['review_margin'], selected['matching_margin'])
        for observation, row in zip(observations, rows):
            observation['human_timing_audit'] = compare_intervals(row['bounds']['syllable'], row['human_syllable'])
            observation['pure_nasal_pair'] = row.get('pure_nasal_pair')
        gated = [content_gate(o, content.get(o['id'], 'unavailable')) for o in observations]
        reports[model['name']] = {
            'all': summarize(observations),
            'pure_nasal_pairs': summarize([o for o in observations if o['pure_nasal_pair'] is True]),
            'directions': {label: summarize([o for o in observations if o['expected'] == label]) for label in ('front', 'back')},
            'timing_states': dict(Counter(o['human_timing_audit']['state'] for o in observations)),
            'timing_consistent': summarize([o for o in observations if o['human_timing_audit']['state'] == 'consistent']),
            'with_content_gate': summarize(gated),
            'with_content_gate_pure_pairs': summarize([o for o in gated if o['pure_nasal_pair'] is True]),
            'predictions': observations}
    manifest = json.loads((folder / 'input.json').read_text())
    report = {'complete': True, 'comparison': reports, 'dataset_sha256': index['dataset_sha256'],
              'selected_recordings': len(manifest['records']),
              'selected_targets': sum(len(r['targets']) for r in manifest['records']),
              'unusable_api_targets': len(dataset['excluded']), 'unusable_features': len(index['excluded']),
              'api_exclusions': dict(Counter(r['api_state'] for r in dataset['excluded'])),
              'source_annotation_exclusions': len(manifest['excluded']),
              'limits': manifest['limits'] + [
                  'Human timing consistency does not establish vowel-boundary accuracy.',
                  'Separate broad substitutions from pure n/ng pairs.',
                  'No live microphone or deployment validation.']}
    save_json(output, report)
    for name, result in reports.items():
        print(name, json.dumps({k: v for k, v in result.items() if k != 'predictions'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['freeze-models', 'evaluate'])
    parser.add_argument('--directory', default='data/derived/nasal-acoustic-validation/griffith-external-v2')
    parser.add_argument('--include-exact', action='store_true', help='Freeze/evaluate the separate development-boundary calibration too.')
    args = parser.parse_args()
    (freeze_models if args.mode == 'freeze-models' else evaluate)(Path(args.directory), args.include_exact)
