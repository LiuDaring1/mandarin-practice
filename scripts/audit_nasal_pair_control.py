"""Post-hoc ablation: same encoders/regularization, disable pair conditioning.

Uses the shared head already saved in the selected pair bundle and its matching
development-only thresholds already frozen among the 27 candidates. No refit,
threshold change or production selection. This is explicitly not a new test set.
"""
from collections import Counter
from datetime import datetime, timezone
import json

import numpy as np

import probe_nasal_pairs as experiment
from nasal_feature_fusion import feature_source, gate_scores
from nasal_pair_classifier import predict_heads, unpack_heads
from probe_phonetic_xeus import apply, cohort_summary
from train_nasal_feature_probe import save_json


def main():
    experiment.checked()
    root = experiment.FOLDER
    selection = json.loads((root/'selection.json').read_text())
    evaluation = json.loads((root/'evaluation.json').read_text())
    if evaluation.get('complete') is not True or evaluation['selection_sha256'] != experiment.sha(root/'selection.json'):
        raise ValueError('Completed parent comparison required')
    parent = selection['selected']['pair']
    controls = [c for c in selection['ranking'] if c['feature_source']==parent['feature_source']
                and c['regularization']==parent['regularization'] and c['specialist_weight']==0]
    if len(controls)!=1 or experiment.sha(root/'pair-heads.npz')!=selection['weights_sha256']['pair']:
        raise ValueError('Matching frozen control/model missing')
    control = controls[0]
    plan_path = root/'matched-control-plan.json'; output = root/'matched-control-diagnostic.json'
    if plan_path.exists() or output.exists():
        raise ValueError('Matched control audit already started')
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'post_hoc_diagnostic': True,
            'code_sha256': experiment.sha(__file__), 'parent_plan_sha256': experiment.sha(root/'plan.json'),
            'selection_sha256': experiment.sha(root/'selection.json'),
            'evaluation_sha256': experiment.sha(root/'evaluation.json'),
            'weights_sha256': selection['weights_sha256']['pair'], 'control': control,
            'refitting': False, 'recalibration': False, 'production_selection': False}
    save_json(plan_path, plan)
    with np.load(root/'pair-heads.npz', allow_pickle=False) as values:
        heads = unpack_heads(dict(values))
    reports = {}
    for cohort in ('existing', 'griffith'):
        rows, features, dataset = experiment.load(cohort)
        positions = [i for i, r in enumerate(rows) if r['split'] not in ('train', 'dev') and r['expected_label']!='other']
        rows = [rows[i] for i in positions]
        scores = predict_heads(heads, feature_source(features[positions], control['feature_source']),
                               [r['expected_final'] for r in rows], 0.)
        observations = apply(rows, gate_scores(scores, experiment.present(rows, cohort)), control)
        selected = {k: [r for r in dataset[k] if r['expected_label']!='other'] for k in ('rows', 'excluded')}
        reports[cohort] = cohort_summary(selected, observations)
        print('MATCHED CONTROL', cohort, json.dumps({k: reports[cohort]['evaluation_only'][k] for k in
            ('correct_error_directions', 'known_nasal_errors', 'false_nasal_accusations', 'correct_nasal_targets',
             'false_reassurances', 'correct_nasal_matches', 'uncertain_nasal_targets')}), flush=True)
    rows, _, _ = experiment.load('existing')
    source_audit = {}
    for subset in ('train', 'dev', 'evaluation'):
        included = [r for r in rows if (r['split']==subset if subset!='evaluation' else r['split'] not in ('train', 'dev'))]
        groups = Counter((r['speaker'].split(':')[0], r['condition'], r['actual_label'], r['expected_label']) for r in included)
        source_audit[subset] = [{'source': source, 'condition': condition, 'actual': actual, 'expected': expected, 'targets': count}
                               for (source, condition, actual, expected), count in sorted(groups.items())]
    save_json(output, {'complete': True, 'plan_sha256': experiment.sha(plan_path), 'control': control,
                       'comparison': reports, 'source_label_audit': source_audit,
                       'interpretation_limits': [
                           'Chosen for mechanism analysis after seeing parent results, not another independent selection.',
                           'Normal/error condition and source are confounded in existing data; observed association is not proof of causation.',
                           'All original thresholds and classifier weights are unchanged.']})


if __name__=='__main__':
    main()
