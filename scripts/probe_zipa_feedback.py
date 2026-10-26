"""Pre-register ZIPA syllable-crop checks and calibrate only on dev speakers."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from calibrate_nasal_exact_margin import select_exact_feedback
from fit_nasal_context_probe import policy_observations
from fit_nasal_local_context import selected_rows
from nasal_feature_probe import LABELS
from probe_nasal_boundaries import summarize_denominator
from train_nasal_feature_probe import save_json
from zipa_nasal import BASE, FOLDER, digest


def confidence_scores(record):
    """Encode a known terminal-phone label plus a ranking signal, not a grade.

    'other' is a sentinel for abstention. It never generates nasal feedback.
    These three values are not class probabilities or model logits.
    """
    observation = record.get('observation', {})
    group = observation.get('group'); confidence = observation.get('confidence', 0.)
    scores = np.zeros(3)
    if group in ('front', 'back') and 0 < confidence <= 1 and np.isfinite(confidence):
        scores[LABELS.index(group)] = confidence
    else:
        scores[2] = 1.
    return scores


def prepare():
    if (FOLDER / 'plan.json').exists():
        raise ValueError('ZIPA feedback plan frozen')
    original = BASE / 'context-training-v4/dataset.json'; external = BASE / 'griffith-external-v2/dataset.json'
    references_path = BASE / 'phoneme-reference-report.json'
    references = json.loads(references_path.read_text())['cells']; inputs = []
    for row in references:
        # The acoustic control manifest already includes the voice suffix.
        audio = Path('data/derived/nasal-validation-v2') / f"{row['audio_id']}.wav"
        inputs.append({'audio': str(audio), 'audio_sha256': digest(audio), 'label': row['label'],
                       'voice': row['voice'], 'actual_label': row['expected_group']})
    sources = [original, external, references_path, FOLDER / 'model/source.json', Path(__file__), Path('scripts/zipa_nasal.py'),
               BASE / 'ise-word-calibration-input.json', BASE / 'feedback-v3-holdout/input.json', BASE / 'context-training-v4/input.json']
    save_json(FOLDER / 'plan.json', {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'sources': {str(p): digest(p) for p in sources}, 'padding_ms': [0, 50],
        'reference_inputs': inputs, 'model_training': False, 'calibration_splits': ['dev'],
        'selection': 'Zero development false accusations, both directions, >=3 errors; positives separately calibrated with API conflict veto.',
        'ranking': ['most dev errors detected', 'most dev normal matched', 'less padding'],
        'reference_controls_used_for_selection': False, 'external_used_for_selection': False,
        'evaluation_previously_explored': True})
    for name, path in [('existing', original), ('griffith', external)]:
        dataset = json.loads(path.read_text())
        recovered = {r['id']: r for r in selected_rows(dataset)} if name == 'existing' else {r['id']: r for r in dataset['rows'] + dataset['excluded']}
        save_json(FOLDER / f'{name}-dataset.json', {
            'rows': [r for r in dataset['rows'] if r['expected_label'] in ('front', 'back')],
            'excluded': [recovered[r['id']] for r in dataset['excluded'] if recovered[r['id']]['expected_label'] in ('front', 'back')],
            'source_sha256': digest(path), 'plan_sha256': digest(FOLDER / 'plan.json')})


def observations(dataset, predictions, padding, review, matching, splits=None):
    lookup = {r['id']: r for r in predictions if r['padding_ms'] == padding and not r.get('unavailable')}
    rows = [r for r in dataset['rows'] if r['id'] in lookup and (splits is None or r['split'] in splits)]
    scores = np.stack([confidence_scores(lookup[r['id']]) for r in rows])
    return rows, scores, policy_observations(rows, scores, review, matching)


def evaluate():
    output = FOLDER / 'evaluation.json'
    if output.exists() or (FOLDER / 'selection.json').exists():
        raise ValueError('ZIPA evaluation/selection already frozen')
    plan = json.loads((FOLDER / 'plan.json').read_text())
    if any(digest(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('Frozen ZIPA sources changed')
    inference = json.loads((FOLDER / 'predictions.json').read_text())
    if inference.get('complete') is not True or inference['plan_sha256'] != digest(FOLDER / 'plan.json'):
        raise ValueError('ZIPA inference incomplete or stale')
    datasets = {name: json.loads((FOLDER / f'{name}-dataset.json').read_text()) for name in ('existing', 'griffith')}
    if any(inference['dataset_sha256'][name] != digest(FOLDER / f'{name}-dataset.json') for name in datasets):
        raise ValueError('ZIPA dataset changed after inference')
    dataset = datasets['existing']; candidates = []
    dev_selected = [r for r in dataset['rows'] + dataset['excluded'] if r['split'] == 'dev']
    for padding in plan['padding_ms']:
        rows, scores, _ = observations(dataset, inference['cohorts']['existing'], padding, None, None, {'dev'})
        review, matching, _, _ = select_exact_feedback(rows, scores)
        review_margin = review['margin'] if review else None
        matching_margin = matching['margin'] if matching else None
        observed = policy_observations(rows, scores, review_margin, matching_margin)
        candidates.append({'padding_ms': padding, 'review_margin': review_margin, 'matching_margin': matching_margin,
            'development': summarize_denominator(dev_selected, observed),
            'directions_by_expected': review['directions_by_expected'] if review else {}})
    candidates.sort(key=lambda c: (-c['development']['correct_error_directions'], -c['development']['correct_nasal_matches'], c['padding_ms']))
    selected = candidates[0]
    save_json(FOLDER / 'selection.json', {'selected_at_utc': datetime.now(timezone.utc).isoformat(), 'selected': selected,
        'ranking': candidates, 'evaluation_rows_used_for_selection': False, 'plan_sha256': digest(FOLDER / 'plan.json')})
    comparison = {}
    for name, dataset in datasets.items():
        _, _, observed = observations(dataset, inference['cohorts'][name], selected['padding_ms'], selected['review_margin'], selected['matching_margin'])
        rows = dataset['rows'] + dataset['excluded']; pure = [r for r in rows if r.get('pure_nasal_pair') is True]
        heldout = [r for r in rows if r['split'] not in ('train', 'dev')]
        comparison[name] = {'evaluation_only': summarize_denominator(heldout, [r for r in observed if r['split'] not in ('train', 'dev')]),
            'groups': {split: summarize_denominator([r for r in rows if r['split'] == split], [r for r in observed if r['split'] == split]) for split in sorted({r['split'] for r in rows})},
            'pure_nasal_pairs': summarize_denominator(pure, [r for r in observed if r['id'] in {v['id'] for v in pure}]),
            'predictions': observed}
    controls = inference['reference_controls']
    report = {'complete': True, 'selected': selected, 'comparison': comparison,
        'reference_controls': {'count': len(controls), 'agreed': sum(r['observation']['group'] == r['actual_label'] for r in controls),
            'unknown': sum(r['observation']['group'] is None for r in controls),
            'wrong': sum(r['observation']['group'] is not None and r['observation']['group'] != r['actual_label'] for r in controls)},
        'evaluation_previously_explored': True, 'selection_sha256': digest(FOLDER / 'selection.json'),
        'limits': ['Terminal-phone posterior is only a ranking signal, not a calibrated correctness probability.',
                   'No nasal terminal is unknown, never evidence of a correct production.',
                   'API crop may omit a nasal or include the next phone.', 'No production, live microphone, noise or new blind test.']}
    save_json(output, report)
    print('SELECTED', json.dumps(selected), flush=True)
    print('CONTROLS', json.dumps(report['reference_controls']), flush=True)
    for name, value in comparison.items():
        print(name, json.dumps(value['evaluation_only']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'evaluate'])
    args = parser.parse_args(); {'prepare': prepare, 'evaluate': evaluate}[args.mode]()
