"""Pre-registered Xeus19/HuBERT18 block fusion with exact endpoint controls."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

import probe_chinese_hubert as previous
from probe_xeus_encoder_context import COHORTS,engine
from nasal_feature_fusion import align_features,gate_scores
from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training
from nasal_weighted_fusion import WEIGHTS,fit_weighted,predict_weighted
from train_nasal_feature_probe import save_json

FOLDER=engine.BASE/'hubert-fusion-v1'


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Frozen fusion source changed: '+path)
    if list(WEIGHTS)!=plan['hubert_weights']: raise ValueError('Fusion weights changed')
    return plan


def load(cohort,weight):
    left,a,ok_a,present,dataset=previous.load_features(cohort,'xeus')
    right,b,ok_b,other_present,other_dataset=previous.load_features(cohort,'hubert_18')
    if not np.array_equal(present,other_present) or dataset!=other_dataset:raise ValueError('Cohort/gate mismatch')
    paired=align_features(left,a,right,b)
    available=ok_a if weight==0 else ok_b if weight==1 else ok_a & ok_b
    return left,paired,available,present,dataset


def prepare():
    if FOLDER.exists():raise ValueError('HuBERT fusion already frozen')
    parent=previous.checked();old=json.loads((previous.FOLDER/'selection.json').read_text())
    if old['selected']['hubert']['view']!='hubert_18' or old['selected']['baseline']['view']!='xeus':
        raise ValueError('Endpoints were not previously selected on development')
    features=json.loads((previous.FOLDER/'feature-report.json').read_text())
    paths=[Path(p) for p in parent['sources']]+[previous.FOLDER/n for n in ('plan.json','selection.json','evaluation.json','feature-report.json')]
    paths += [Path(p) for p in features['outputs']]
    paths += [Path('scripts')/n for n in ('nasal_weighted_fusion.py','probe_hubert_fusion.py')]
    for path,digest in features['outputs'].items():
        if engine.sha(path)!=digest:raise ValueError('Parent acoustic features changed')
    rows,_,available,_,_=load('existing',.5)
    if not available.all():raise ValueError('Cannot change membership for this comparison')
    if audit_training([r for r in rows if r['split']=='train'])!=parent['support']:raise ValueError('Training support changed')
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):engine.sha(p) for p in paths},
        'hubert_weights':list(WEIGHTS),'regularizations':[.01,.1,1.],'cohorts':list(COHORTS),'support':parent['support'],
        'layers':{'xeus':19,'hubert':18},'pooling':'unchanged two vowel half means from frozen parents',
        'block_weight_definition':'class-balanced training-standardized aggregate energy fraction; raw scaling does not substitute',
        'encoder_training':False,'new_extraction':False,'weak_targets_used':False,'same_train_dev_membership_required':True,
        'calibration_mode':'directional','gate':'unchanged fixed Silero VAD','api_positive_veto':True,
        'ranking':['dev correct error directions','dev normal matches','unchanged Xeus tie preference','stronger regularization','lower HuBERT weight'],
        'evaluate':['primary','best fused','best Xeus','best HuBERT','Xeus at fused regularization','HuBERT at fused regularization'],
        'endpoint_development_exact_replay_required':6,'endpoint_prediction_exact_replay_required':672,
        'evaluation_previously_explored':True,'api_calls':0,'production_enablement':False,
        'limits':parent['limits']+['Fused observations are not an independent second test of the existing cohorts.']}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    print('HUBERT FUSION PLAN FROZEN',15,'candidates',flush=True)


def rank(c):
    return (-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches'],
        c['hubert_weight']!=0.,-c['regularization'],c['hubert_weight'])


def fit():
    from probe_phonetic_xeus import apply,calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan=checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')):raise ValueError('Fusion selection frozen')
    old=json.loads((previous.FOLDER/'selection.json').read_text())['ranking'];candidates=[];models={}
    for weight in WEIGHTS:
        rows,paired,available,present,dataset=load('existing',weight)
        train=[i for i,r in enumerate(rows) if r['split']=='train'];dev=[i for i,r in enumerate(rows) if r['split']=='dev']
        if not available[train+dev].all():raise ValueError('Different training/development membership')
        if audit_training([rows[i] for i in train])!=plan['support']:raise ValueError('Training labels changed')
        labels=np.array([LABELS.index(rows[i]['actual_label']) for i in train]);development=[rows[i] for i in dev]
        denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
        for strength in plan['regularizations']:
            model=fit_weighted(paired[train],labels,strength,weight)
            scores=gate_scores(predict_weighted(model,paired[dev],weight),present[dev])
            policy=calibrate(development,scores,plan['calibration_mode'])
            summary=summarize_denominator(denominator,apply(development,scores,policy))
            c={**policy,'development':summary,'hubert_weight':weight,'regularization':strength}
            if weight in (0.,1.):
                view='xeus' if weight==0 else 'hubert_18';prior=next(v for v in old if v['view']==view and v['regularization']==strength)
                if any(json.dumps(c[k],sort_keys=True)!=json.dumps(prior[k],sort_keys=True) for k in c if k!='hubert_weight'):
                    raise ValueError('Endpoint failed exact development replay')
            models[(weight,strength)]=model;candidates.append(c)
            print('FUSION CANDIDATE',weight,strength,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank);fused=next(c for c in candidates if 0<c['hubert_weight']<1)
    selected={'primary':candidates[0],'fused':fused,'xeus':next(c for c in candidates if c['hubert_weight']==0.),
        'hubert':next(c for c in candidates if c['hubert_weight']==1.),
        'matched_xeus':next(c for c in candidates if c['hubert_weight']==0. and c['regularization']==fused['regularization']),
        'matched_hubert':next(c for c in candidates if c['hubert_weight']==1. and c['regularization']==fused['regularization'])}
    hashes={}
    for name,c in selected.items():
        path=FOLDER/f'{name}-model.npz';engine.save_npz(path,**models[(c['hubert_weight'],c['regularization'])]);hashes[name]=engine.sha(path)
    save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'selected':selected,'ranking':candidates,
        'weights_sha256':hashes,'train_targets':len(train),'dev_targets':len(dev),'endpoint_development_exact_replay':6,'evaluation_used_for_selection':False})
    print('FUSION SELECTED',json.dumps({n:{k:c[k] for k in ('hubert_weight','regularization')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists():raise ValueError('Fusion evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json'):raise ValueError('Selection changed')
    prior=json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison'];comparison={};noise={};replay={}
    for name,c in selection['selected'].items():
        path=FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]:raise ValueError('Fusion weights changed')
        with np.load(path,allow_pickle=False) as stored:model=dict(stored)
        comparison[name]={}
        for cohort in ('existing','griffith','restored'):
            rows,x,available,present,dataset=load(cohort,c['hubert_weight'])
            indices=[i for i,r in enumerate(rows) if available[i] and r['split'] not in ('train','dev') and r['expected_label']!='other']
            observations=apply([rows[i] for i in indices],gate_scores(predict_weighted(model,x[indices],c['hubert_weight']),present[indices]),c)
            selected={key:[r for r in dataset[key] if r['expected_label']!='other'] for key in ('rows','excluded')}
            comparison[name][cohort]=cohort_summary(selected,observations)
            if name in ('xeus','hubert'):
                old=prior['baseline' if name=='xeus' else 'hubert'][cohort]['predictions']
                if observations!=old:raise ValueError('Endpoint predictions failed exact replay')
                replay[name+'-'+cohort]={'targets':len(observations),'all_prediction_fields_identical':True}
            d=comparison[name][cohort]['evaluation_only']
            print('FUSION EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','known_nasal_errors','false_nasal_accusations','correct_nasal_targets','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,available,present,_=load('noise',c['hubert_weight'])
        if not available.all():raise ValueError('Background incomplete')
        scores=predict_weighted(model,x,c['hubert_weight']);summaries={}
        for state,values in [('gated',gate_scores(scores,present)),('ungated',scores)]:
            observations=[]
            for final in ['an','ang','en','eng','ian','iang','in','ing','uan','uang']:
                targets=[{**r,'expected_final':final,'expected_label':'back' if final.endswith('ng') else 'front'} for r in rows]
                observations.extend({**p,'noise_source':r['noise_source']} for p,r in zip(apply(targets,values,c),rows))
            summaries[state]={kind:{'conditions':len(part),'false_matches':sum(p['candidate_nasal_match'] for p in part),
                'false_corrections':sum(p['candidate_nasal_change'] for p in part),'abstentions':sum(not p['candidate_nasal_match'] and not p['candidate_nasal_change'] for p in part)}
                for kind in ('synthetic','recorded_environment') for part in [[p for p in observations if p['noise_source']==kind]]}
        noise[name]={'recordings':len(rows),'summaries':summaries}
    save_json(output,{'complete':True,'selection_sha256':engine.sha(FOLDER/'selection.json'),'comparison':comparison,
        'noise':noise,'endpoint_replay':replay,'limits':plan['limits']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
