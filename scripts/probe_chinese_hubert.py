"""Frozen Mandarin encoder versus Xeus; train/dev selection, held-out comparison."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

from chinese_hubert_features import LAYERS,VIEWS,feature_view
import probe_direct_acoustics as previous
from probe_xeus_encoder_context import load_base,COHORTS,engine
from nasal_feature_fusion import gate_scores
from nasal_feature_probe import LABELS,fit_ridge,predict_ridge
from nasal_pair_classifier import audit_training
from train_nasal_feature_probe import save_json

FOLDER=engine.BASE/'chinese-hubert-v1'


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Frozen HuBERT source changed: '+path)
    if list(LAYERS)!=plan['layers'] or list(VIEWS)!=plan['views']: raise ValueError('Feature definition changed')
    return plan


def prepare():
    if FOLDER.exists(): raise ValueError('HuBERT experiment already frozen')
    parent=previous.checked();preflight=engine.BASE/'chinese-hubert-preflight-v1/report.json'
    test=json.loads(preflight.read_text())
    if not test['complete']: raise ValueError('Incomplete HuBERT preflight')
    for path,digest in test['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Preflight source changed')
    rows,_,_,_=load_base('existing');support=audit_training([r for r in rows if r['split']=='train'])
    if support!=parent['support']: raise ValueError('Strong training support changed')
    paths=[Path(p) for p in parent['sources']]+[previous.FOLDER/n for n in ('plan.json','selection.json','evaluation.json')]
    paths += [Path('scripts')/n for n in ('chinese_hubert_features.py','probe_chinese_hubert.py','extract_chinese_hubert.py')]
    paths += [preflight]+[Path(p) for p in test['sources']]
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):engine.sha(p) for p in paths},
        'layers':list(LAYERS),'views':list(VIEWS),'regularizations':[.01,.1,1.],
        'cohorts':list(COHORTS),'support':support,'model':test['model'],
        'calibration_mode':'directional','gate':'unchanged fixed Silero VAD','api_positive_veto':True,
        'pooling':'two mean vowel halves; nominal 400-sample field and 320-sample stride; no neighboring fallback',
        'preprocessing':'official extractor normalizes each fixed <=20s parent; full audio context, no reference text',
        'baseline_exact_replay_required':True,'same_train_dev_membership_required':True,
        'ranking':['dev error detections','dev normal matches','baseline tie preference','stronger regularization','earlier layer'],
        'evaluate':['primary','best HuBERT','best baseline','baseline at best HuBERT regularization'],
        'evaluation_previously_explored':True,'weak_targets_used':False,'api_calls':0,'production_enablement':False,
        'limits':['Reference-dependent API bounds remain unchanged.',
            'Normal and erroneous training targets remain confounded with corpus source.',
            'All evaluation cohorts explored; restored cohort shares speakers and one sentence.',
            'Pretraining corpus overlap cannot be independently excluded.',
            'Not real-device, noisy-speech, omission or repetition acceptance.']}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    print('HUBERT PLAN FROZEN',len(VIEWS)*len(plan['regularizations']),'candidates',flush=True)


def load_features(cohort,view):
    report=json.loads((FOLDER/'feature-report.json').read_text());path=FOLDER/f'{cohort}-features.npz'
    if not report['complete'] or report['plan_sha256']!=engine.sha(FOLDER/'plan.json') or report['outputs'][str(path)]!=engine.sha(path):
        raise ValueError('Incomplete or stale HuBERT features')
    rows,baseline,present,dataset=load_base(cohort)
    with np.load(path,allow_pickle=False) as stored:
        if stored['ids'].tolist()!=[r['id'] for r in rows]: raise ValueError('HuBERT feature identity changed')
        if stored['features'].shape!=(len(rows),4,2048): raise ValueError('HuBERT feature shape mismatch')
        available=stored['available'] if view!='xeus' else np.ones(len(rows),dtype=bool)
        if available.shape!=(len(rows),) or available.dtype!=np.bool_: raise ValueError('Invalid availability')
        x=feature_view(baseline,stored['features'],view)
        if not np.isfinite(x[available]).all(): raise ValueError('Nonfinite available features')
    return rows,x,available,present,dataset


def rank(c):
    return (-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches'],
        c['view']!='xeus',-c['regularization'],VIEWS.index(c['view']))


def fit():
    from probe_phonetic_xeus import apply,calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan=checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')): raise ValueError('HuBERT selection frozen')
    old=json.loads((previous.FOLDER/'selection.json').read_text())['ranking'];candidates=[];models={}
    for view in VIEWS:
        rows,x,available,present,dataset=load_features('existing',view)
        train=[i for i,r in enumerate(rows) if r['split']=='train'];dev=[i for i,r in enumerate(rows) if r['split']=='dev']
        if not available[train+dev].all(): raise ValueError('Cannot compare different train/dev membership')
        if audit_training([rows[i] for i in train])!=plan['support']: raise ValueError('Training labels changed')
        labels=np.array([LABELS.index(rows[i]['actual_label']) for i in train]);development=[rows[i] for i in dev]
        denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
        for strength in plan['regularizations']:
            model=fit_ridge(x[train],labels,strength)
            scores=gate_scores(predict_ridge(model,x[dev]),present[dev])
            policy=calibrate(development,scores,plan['calibration_mode'])
            summary=summarize_denominator(denominator,apply(development,scores,policy))
            c={**policy,'development':summary,'view':view,'regularization':strength}
            if view=='xeus':
                prior=next(v for v in old if v['view']=='xeus' and v['regularization']==strength)
                if any(json.dumps(c[k],sort_keys=True)!=json.dumps(prior[k],sort_keys=True) for k in c):
                    raise ValueError('Xeus baseline failed exact development replay')
            models[(view,strength)]=model;candidates.append(c)
            print('HUBERT CANDIDATE',view,strength,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank);hubert=next(c for c in candidates if c['view']!='xeus')
    selected={'primary':candidates[0],'hubert':hubert,'baseline':next(c for c in candidates if c['view']=='xeus'),
        'matched_baseline':next(c for c in candidates if c['view']=='xeus' and c['regularization']==hubert['regularization'])}
    hashes={}
    for name,c in selected.items():
        path=FOLDER/f'{name}-model.npz';engine.save_npz(path,**models[(c['view'],c['regularization'])]);hashes[name]=engine.sha(path)
    save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'feature_report_sha256':engine.sha(FOLDER/'feature-report.json'),
        'selected_at_utc':datetime.now(timezone.utc).isoformat(),'selected':selected,'ranking':candidates,'weights_sha256':hashes,
        'train_targets':len(train),'dev_targets':len(dev),'baseline_development_exact_replay':3,'evaluation_used_for_selection':False})
    print('HUBERT SELECTED',json.dumps({n:{k:c[k] for k in ('view','regularization')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists(): raise ValueError('HuBERT evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json') or selection['feature_report_sha256']!=engine.sha(FOLDER/'feature-report.json'):
        raise ValueError('HuBERT selection changed')
    prior=json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison']['baseline']
    comparison={};noise={};replay={}
    for name,c in selection['selected'].items():
        path=FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]: raise ValueError('HuBERT weights changed')
        with np.load(path,allow_pickle=False) as stored: model=dict(stored)
        comparison[name]={}
        for cohort in ('existing','griffith','restored'):
            rows,x,available,present,dataset=load_features(cohort,c['view'])
            indices=[i for i,r in enumerate(rows) if available[i] and r['split'] not in ('train','dev') and r['expected_label']!='other']
            observations=apply([rows[i] for i in indices],gate_scores(predict_ridge(model,x[indices]),present[indices]),c)
            selected={key:[r for r in dataset[key] if r['expected_label']!='other'] for key in ('rows','excluded')}
            comparison[name][cohort]=cohort_summary(selected,observations)
            if name=='baseline':
                if observations!=prior[cohort]['predictions']: raise ValueError('Baseline evaluation failed exact replay')
                replay[cohort]={'targets':len(observations),'all_prediction_fields_identical':True}
            d=comparison[name][cohort]['evaluation_only']
            print('HUBERT EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','known_nasal_errors','false_nasal_accusations','correct_nasal_targets','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,available,present,_=load_features('noise',c['view'])
        if not available.all(): raise ValueError('Background extraction incomplete')
        scores=predict_ridge(model,x);summaries={}
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
        'noise':noise,'original_baseline_replay':replay,'limits':plan['limits']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
