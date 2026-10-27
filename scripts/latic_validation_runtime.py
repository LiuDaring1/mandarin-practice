"""Five previously frozen models behind one read-only evaluation adapter.

No fitting, threshold choice or API calls. Unknown/absent targets stay in the
selected denominator. The replay command uses only already explored features.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from nasal_feature_fusion import gate_scores
from nasal_feature_probe import predict_ridge
from nasal_pair_classifier import unpack_heads
from nasal_weighted_fusion import predict_weighted
from nasal_weighted_pairs import predict_heads
from probe_phonetic_xeus import apply
from probe_nasal_boundaries import summarize_denominator
from train_nasal_feature_probe import save_json

BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'latic-runner-v1'
NAMES = ('xeus','hubert','fusion','hubert_pair','hubert_temporal')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def registry():
    source = BASE/'latic-validation-v1';plan = read(source/'plan.json')
    addition = read(source/'model-addition-temporal-v1.json')
    if addition['original_plan_sha256'] != sha(source/'plan.json'):
        raise ValueError('Original LATIC plan changed')
    if (set(plan['models']) != set(NAMES[:4]) or plan['fit_or_recalibration_allowed'] or
        addition['training_or_recalibration_allowed'] or addition['addition']['name'] != NAMES[-1]):
        raise ValueError('Frozen model roster or fitting policy changed')
    if plan['inventory_sha256'] != sha(plan['inventory']):raise ValueError('Target inventory changed')
    for path,digest in addition['sources'].items():
        if sha(path) != digest:raise ValueError('Prospective model addition changed')
    models = {**plan['models'], NAMES[-1]:addition['addition']}
    for name,spec in models.items():
        for key in ('selection','weights'):
            digest = spec.get(key+'_sha256',addition['sources'].get(spec[key]))
            if digest is None or sha(spec[key]) != digest:raise ValueError('Frozen model source changed: '+name)
    return plan,models


def selected_rows():
    plan,_ = registry(); inventory = read(plan['inventory']);rows=[]
    for role,targets in [('error',inventory['errors']),('normal',inventory['controls'])]:
        for t in targets:
            mapping=t['reference_mapping']
            if (mapping is None or mapping['token_position'] != t['token_position'] or
                mapping['expected_pinyin'] != t['expected_pinyin'] or
                (t['expected_label'] != t['actual_label']) != (role=='error')):
                raise ValueError('Frozen target position or role changed')
            rows.append({**t,'role':role,'position':mapping['position'],'split':'external',
                'cohort':'latic','pure_nasal_pair':role=='error',
                'label_source':'published_latic_actual_notation'})
    if (len(rows)!=72 or len({r['id'] for r in rows})!=72 or
        len({r['utterance_id'] for r in rows})!=69):raise ValueError('Frozen LATIC membership changed')
    return rows


def predict(spec,rows,paired,temporal,present):
    """Feature rows must already share one target order; no model fallback."""
    n=len(rows);x=np.asarray(paired);t=np.asarray(temporal);mask=np.asarray(present)
    if (x.shape!=(n,2,2048) or t.shape!=(n,4096) or mask.shape!=(n,) or
        mask.dtype!=np.bool_ or len({r['id'] for r in rows})!=n or
        not np.isfinite(x).all() or not np.isfinite(t).all()):
        raise ValueError('Feature identity/shape/value mismatch')
    with np.load(spec['weights'],allow_pickle=False) as packed:weights=dict(packed)
    policy=spec['policy'];kind=spec['kind']
    if kind=='weighted_shared':scores=predict_weighted(weights,x,policy['hubert_weight'])
    elif kind=='weighted_pairs':
        scores=predict_heads(unpack_heads(weights),x,[r['expected_final'] for r in rows],
            policy['specialist_weight'],policy['hubert_weight'])
    elif kind=='shared_ridge_temporal':scores=predict_ridge(weights,t)
    else:raise ValueError('Unknown frozen model kind')
    return apply(rows,gate_scores(scores,mask),policy)


def summarize_selected(rows,observations):
    if any(r['split']!='external' for r in rows):raise ValueError('LATIC targets cannot enter fitting')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate selected target')
    result={'all':summarize_denominator(rows,observations)}
    for group in ('front','back'):
        result[group]=summarize_denominator([r for r in rows if r['expected_label']==group],
            [r for r in observations if r['expected']==group])
    return result


def prepare():
    if FOLDER.exists():raise ValueError('Runner plan already frozen')
    plan,models=registry();rows=selected_rows()
    paths=[BASE/'latic-validation-v1'/n for n in ('plan.json','model-addition-temporal-v1.json')]
    paths += [Path(plan['inventory']),Path(__file__),Path('scripts/import_latic_validation.py')]
    paths += [Path('scripts')/n for n in ('nasal_feature_probe.py','nasal_feature_fusion.py','nasal_weighted_fusion.py',
        'nasal_weighted_pairs.py','nasal_pair_classifier.py','probe_phonetic_xeus.py','probe_nasal_boundaries.py',
        'nasal_directional_calibration.py','fit_nasal_context_probe.py','train_nasal_feature_probe.py')]
    for spec in models.values():paths.extend(Path(spec[k]) for k in ('selection','weights'))
    for name in ('hubert-fusion-v1','hubert-pairs-v1','hubert-temporal-v1'):
        paths += [BASE/name/n for n in ('plan.json','evaluation.json')]
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):sha(p) for p in paths},'models':models,'model_names':list(NAMES),
        'selected_target_ids':[r['id'] for r in rows], 'selected_targets':72,'selected_recordings':69,
        'replay_cohorts':['existing','griffith','restored'],'exact_prediction_replay_required':True,
        'corpus_audio_seen':False,'new_api_calls':0,'fitting_allowed':False,'production_enabled':False,
        'import_rules':'Exact WAV stem; same archive contains four official annotation tables; selected text/token identity must agree before conversion; failures remain in denominator.',
        'readiness_limit':'Importer and scoring adapter only; new-audio alignment/extraction/API orchestration still required.'})
    print('LATIC RUNNER FROZEN 5 models / 72 targets / 69 recordings',flush=True)


def checked():
    plan=read(FOLDER/'plan.json');registry()
    for path,digest in plan['sources'].items():
        if sha(path)!=digest:raise ValueError('Runner source changed: '+path)
    if [r['id'] for r in selected_rows()]!=plan['selected_target_ids']:raise ValueError('Target selection changed')
    return plan


def replay():
    import probe_hubert_fusion as fusion
    import probe_hubert_temporal as temporal
    plan=checked();output=FOLDER/'replay.json'
    if output.exists():raise ValueError('Runner replay already frozen')
    references={name:read(BASE/folder/'evaluation.json')['comparison'][key]
        for name,folder,key in [('xeus','hubert-fusion-v1','xeus'),('hubert','hubert-fusion-v1','hubert'),
            ('fusion','hubert-fusion-v1','fused'),('hubert_pair','hubert-pairs-v1','chinese_pair'),
            ('hubert_temporal','hubert-temporal-v1','primary')]}
    result={}
    for cohort in plan['replay_cohorts']:
        rows,x,available,present,dataset=fusion.load(cohort,.25)
        other,t,other_present,other_dataset=temporal.load(cohort,'resampled4')
        if rows!=other or dataset!=other_dataset or not available.all() or not np.array_equal(present,other_present):
            raise ValueError('Replay target/order/availability mismatch')
        indices=[i for i,r in enumerate(rows) if r['split'] not in ('train','dev') and r['expected_label']!='other']
        targets=[rows[i] for i in indices];result[cohort]={}
        for name,spec in plan['models'].items():
            predictions=predict(spec,targets,x[indices],t[indices],present[indices])
            if predictions!=references[name][cohort]['predictions']:
                raise ValueError('Original predictions changed for '+name+'/'+cohort)
            result[cohort][name]={'targets':len(predictions),'all_prediction_fields_identical':True}
            print('LATIC RUNNER REPLAY',cohort,name,len(predictions),'exact',flush=True)
    checked();save_json(output,{'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),'replay':result,
        'prediction_rows':sum(x['targets'] for c in result.values() for x in c.values()),
        'latic_audio_or_model_outputs_seen':False,'new_accuracy_evidence':False,'new_api_calls':0})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','replay']);args=parser.parse_args()
    {'prepare':prepare,'replay':replay}[args.mode]()
