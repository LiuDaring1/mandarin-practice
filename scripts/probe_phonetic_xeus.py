"""Pre-register and evaluate a new phone recognizer and directional calibration."""
import argparse
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path

import numpy as np

from calibrate_nasal_exact_margin import select_exact_feedback
from fit_nasal_context_probe import policy_observations
from nasal_directional_calibration import directional_observations, select_directional_feedback
from probe_nasal_boundaries import summarize_denominator
from train_nasal_feature_probe import save_json
from phonetic_xeus import FOLDER, REVISION, sha256

BASE = FOLDER.parent


def checked_plan():
    plan = json.loads((FOLDER / 'plan.json').read_text())
    if any(sha256(Path(p)) != expected for p, expected in plan['sources'].items()):
        raise ValueError('Frozen Xeus experiment source changed')
    return plan


def prepare():
    output = FOLDER / 'plan.json'
    if output.exists():
        raise ValueError('Xeus plan already frozen')
    sources = [BASE / 'zipa-v1' / f'{c}-dataset.json' for c in ('existing', 'griffith')]
    sources += [FOLDER / name for name in ('model-source.json', 'runtime-source.json', 'smoke.json', 'device-parity.json')]
    sources += [BASE / 'zipa-v1/plan.json', BASE / 'local-context-training-v8/evaluation.json',
                BASE / 'local-context-training-v8/selection.json']
    sources += [Path('scripts') / name for name in ('phonetic_xeus.py', 'xeus_nasal_evidence.py',
                'nasal_directional_calibration.py', 'infer_phonetic_xeus.py', 'probe_phonetic_xeus.py',
                'nasal_acoustics.py', 'nasal_window.py', 'zipa_context.py', 'calibrate_nasal_exact_margin.py',
                'fetch_phonetic_xeus.py', 'fit_nasal_context_probe.py', 'train_nasal_feature_probe.py',
                'audit_nasal_feedback_conflicts.py', 'probe_nasal_boundaries.py', 'nasal_feature_probe.py')]
    plan = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': {str(p): sha256(p) for p in sources}, 'model_revision': REVISION,
            'policies': [{'region': r, 'extension_ms': e, 'method': m}
                         for r,e,m in product(('vowel','syllable'), (0,80), ('terminal','peak'))],
            'calibration_modes': ['global','directional'], 'selection_splits': ['dev'], 'model_training': False,
            'ranking': ['dev correct error directions', 'dev correct nasal matches', 'original candidate order'],
            'directional_review_requirement': 'Per expected category: >=20 normal dev controls, zero observed false accusations, >=2 detected errors.',
            'directional_matching_requirement': 'Per expected category: zero observed false reassurance, >=5 normal matches; API conflict veto.',
            'partial_direction_coverage_is_not_full_success': True,
            'baseline': 'Frozen local-context-v8, with both old margins and directional dev calibration.',
            'controls_used_for_selection': False, 'evaluation_previously_explored': True,
            'maximum_context_seconds':20, 'production_change':False}
    save_json(output, plan)


def apply(rows, scores, spec):
    if spec['calibration_mode'] == 'global':
        return policy_observations(rows,scores,spec['review_margin'],spec['matching_margin'])
    return directional_observations(rows,scores,spec['review_margins'],spec['matching_margins'])


def calibrate(rows, scores, mode):
    if mode == 'global':
        review, matching, _, _ = select_exact_feedback(rows,scores)
        return {'calibration_mode':mode,'review_margin':review['margin'] if review else None,
                'matching_margin':matching['margin'] if matching else None}
    review, matching, details = select_directional_feedback(rows,scores)
    return {'calibration_mode':mode,'review_margins':review,'matching_margins':matching,'directional_development':details}


def model_rows(dataset,predictions,policy,splits=None):
    lookup={r['id']:r for r in predictions if r['policy']==policy and not r.get('unavailable')}
    rows=[r for r in dataset['rows'] if r['id'] in lookup and (splits is None or r['split'] in splits)]
    scores=np.array([lookup[r['id']]['scores'] for r in rows],dtype=float).reshape(-1,3)
    return rows,scores


def cohort_summary(dataset,observations):
    rows=dataset['rows']+dataset['excluded']
    heldout=[r for r in rows if r['split'] not in ('train','dev')]
    observed=[r for r in observations if r['split'] not in ('train','dev')]
    pure=[r for r in heldout if r.get('pure_nasal_pair') is True]
    return {'evaluation_only':summarize_denominator(heldout,observed),
            'directions':{group:summarize_denominator([r for r in heldout if r['expected_label']==group],
                          [r for r in observed if r['expected']==group]) for group in ('front','back')},
            'pure_nasal_pairs':summarize_denominator(pure,[r for r in observed if r['id'] in {x['id'] for x in pure}]),
            'predictions':observations}


def evaluate():
    plan=checked_plan(); output=FOLDER/'evaluation.json'
    if output.exists() or (FOLDER/'selection.json').exists():
        raise ValueError('Xeus selection/evaluation frozen')
    inference=json.loads((FOLDER/'predictions.json').read_text())
    if inference.get('complete') is not True or inference['plan_sha256']!=sha256(FOLDER/'plan.json'):
        raise ValueError('Inference incomplete or stale')
    datasets={name:json.loads((BASE/'zipa-v1'/f'{name}-dataset.json').read_text()) for name in ('existing','griffith')}
    dev=[r for r in datasets['existing']['rows']+datasets['existing']['excluded'] if r['split']=='dev']
    candidates=[]
    for policy in plan['policies']:
        rows,scores=model_rows(datasets['existing'],inference['cohorts']['existing'],policy,{'dev'})
        for mode in plan['calibration_modes']:
            spec=calibrate(rows,scores,mode)
            candidates.append({**spec,'policy':policy,'development':summarize_denominator(dev,apply(rows,scores,spec))})
    candidates.sort(key=lambda c:(-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches']))
    chosen=candidates[0]
    baseline=json.loads((BASE/'local-context-training-v8/evaluation.json').read_text())
    baseline_spec=baseline['selected']
    original={'calibration_mode':'global','review_margin':baseline_spec['review_margin'],'matching_margin':baseline_spec['matching_margin']}
    baseline_inputs={}
    for name,dataset in datasets.items():
        lookup={r['id']:r for r in baseline['comparison'][name]['predictions']}
        rows=[r for r in dataset['rows'] if r['id'] in lookup]
        scores=np.array([lookup[r['id']]['scores'] for r in rows])
        baseline_inputs[name]=(rows,scores)
    rows,scores=baseline_inputs['existing']; positions=[i for i,r in enumerate(rows) if r['split']=='dev']
    baseline_directional=calibrate([rows[i] for i in positions],scores[positions],'directional')
    # Save every choice before computing held-out outcomes.
    save_json(FOLDER/'selection.json',{'selected_at_utc':datetime.now(timezone.utc).isoformat(),
        'selected':chosen,'ranking':candidates,'baseline_original':original,'baseline_directional':baseline_directional,
        'evaluation_rows_used_for_selection':False,'plan_sha256':sha256(FOLDER/'plan.json'),
        'predictions_sha256':sha256(FOLDER/'predictions.json')})
    comparison={}; controls=inference['reference_controls']
    for name,dataset in datasets.items():
        rows,scores=model_rows(dataset,inference['cohorts'][name],chosen['policy'])
        b_rows,b_scores=baseline_inputs[name]
        comparison[name]={'xeus':cohort_summary(dataset,apply(rows,scores,chosen)),
            'baseline_original':cohort_summary(dataset,apply(b_rows,b_scores,original)),
            'baseline_directional':cohort_summary(dataset,apply(b_rows,b_scores,baseline_directional))}
    report={'complete':True,'selected':chosen,'comparison':comparison,
            'reference_controls':{'count':len(controls),'agreed':sum(r['predicted']==r['actual_label'] for r in controls),
                'unknown':sum(r['predicted']=='other' for r in controls),
                'wrong':sum(r['predicted']!='other' and r['predicted']!=r['actual_label'] for r in controls)},
            'selection_sha256':sha256(FOLDER/'selection.json'),'evaluation_previously_explored':True,
            'limits':['No new blind data, microphone or noise validation.',
                      'Directional calibration is a policy change; the frozen v8 control isolates that change.',
                      'Model license restricts commercial use; this is private research, not app distribution.',
                      'API timing and CTC emission centers are approximate, not human phone boundaries.']}
    save_json(output,report)
    print('SELECTED',json.dumps(chosen),flush=True)
    print('CONTROLS',json.dumps(report['reference_controls']),flush=True)
    for name,methods in comparison.items():
        for method,value in methods.items(): print(name,method,json.dumps(value['evaluation_only']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'evaluate':evaluate}[args.mode]()
