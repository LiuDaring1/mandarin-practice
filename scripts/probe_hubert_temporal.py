"""Fixed Chinese HuBERT temporal views, with exact shared-model controls."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

import probe_chinese_hubert as previous
from hubert_temporal_features import VIEWS,WIDTHS
from nasal_feature_fusion import gate_scores
from nasal_feature_probe import LABELS,fit_ridge,predict_ridge
from nasal_pair_classifier import audit_training
from train_nasal_feature_probe import save_json

engine = previous.engine
FOLDER = engine.BASE/'hubert-temporal-v1'
ALL_VIEWS = ('xeus',)+VIEWS


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest:raise ValueError('Frozen temporal source changed: '+path)
    if plan['views']!=list(ALL_VIEWS):raise ValueError('Temporal views changed')
    return plan


def prepare():
    if FOLDER.exists():raise ValueError('Chinese temporal experiment already frozen')
    prior=previous.checked();selection=json.loads((previous.FOLDER/'selection.json').read_text())
    if selection['selected']['hubert']['view']!='hubert_18':raise ValueError('Layer was not previously selected on development')
    features=json.loads((previous.FOLDER/'feature-report.json').read_text())
    paths=[Path(p) for p in prior['sources']]+[previous.FOLDER/n for n in ('plan.json','selection.json','evaluation.json','feature-report.json')]
    paths += [Path(p) for p in features['outputs']]
    paths += [Path('scripts')/n for n in ('hubert_temporal_features.py','extract_hubert_temporal.py','probe_hubert_temporal.py')]
    for path,digest in features['outputs'].items():
        if engine.sha(path)!=digest:raise ValueError('Parent feature changed')
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{str(p):engine.sha(p) for p in paths},'views':list(ALL_VIEWS),'regularizations':[.01,.1,1.],
        'cohorts':prior['cohorts'],'support':prior['support'],'model':prior['model'],'layer':18,
        'parent_context':'same original API bounds and <=20-second parent; official per-parent normalization',
        'temporal_queries':'4 or 8 equal-duration bin centers; interpolate observed frames with constant endpoints; no added observations',
        'tail_statistics_ms':[120,60],'baseline_pooling_tolerance':1e-4,'all_views_same_membership_required':True,
        'encoder_training':False,'weak_labels_used':False,'calibration_mode':'directional','gate':'unchanged fixed Silero VAD','api_positive_veto':True,
        'ranking':['dev errors detected','dev normal matches','unchanged Xeus tie preference','stronger regularization','simpler temporal view'],
        'evaluate':['primary','best new temporal','original HuBERT view','Xeus','HuBERT at temporal regularization','Xeus at temporal regularization'],
        'development_exact_replay_required':6,'endpoint_prediction_exact_replay_required':672,
        'evaluation_previously_explored':True,'production_enabled':False,'new_api_calls':0,
        'limits':prior['limits']+['Interpolated points are not additional independent acoustic observations.',
            'Encoder states already contain full-parent context; nominal frame positions are not precise nasal-tail boundaries.']})
    print('CHINESE TEMPORAL PLAN FROZEN',len(ALL_VIEWS)*3,'candidates',flush=True)


def load(cohort,view):
    if view not in ALL_VIEWS:raise ValueError('Unknown temporal feature view')
    rows,baseline,available,present,dataset=previous.load_features(cohort,'xeus')
    report=json.loads((FOLDER/'feature-report.json').read_text());path=FOLDER/f'{cohort}-features.npz'
    if not report['complete'] or report['plan_sha256']!=engine.sha(FOLDER/'plan.json') or report['outputs'][str(path)]!=engine.sha(path):
        raise ValueError('Temporal feature provenance changed')
    with np.load(path,allow_pickle=False) as values:
        if values['ids'].tolist()!=[r['id'] for r in rows]:raise ValueError('Temporal feature identity changed')
        for name in VIEWS:
            if values[name].shape!=(len(rows),WIDTHS[name]*1024) or not np.isfinite(values[name]).all():raise ValueError('Temporal feature shape/values changed')
        x=baseline if view=='xeus' else values[view]
    if not available.all():raise ValueError('Baseline membership changed')
    return rows,x,present,dataset


def rank(c):
    d=c['development']
    return (-d['correct_error_directions'],-d['correct_nasal_matches'],c['view']!='xeus',-c['regularization'],ALL_VIEWS.index(c['view']))


def fit():
    from probe_phonetic_xeus import apply,calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan=checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')):raise ValueError('Temporal selection frozen')
    prior=json.loads((previous.FOLDER/'selection.json').read_text())['ranking'];models={};candidates=[];replay=0
    for view in ALL_VIEWS:
        rows,x,present,dataset=load('existing',view)
        train=[i for i,r in enumerate(rows) if r['split']=='train'];dev=[i for i,r in enumerate(rows) if r['split']=='dev']
        if audit_training([rows[i] for i in train])!=plan['support']:raise ValueError('Training support changed')
        labels=np.array([LABELS.index(rows[i]['actual_label']) for i in train]);development=[rows[i] for i in dev]
        denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
        for strength in plan['regularizations']:
            model=fit_ridge(x[train],labels,strength);scores=gate_scores(predict_ridge(model,x[dev]),present[dev])
            policy=calibrate(development,scores,plan['calibration_mode']);summary=summarize_denominator(denominator,apply(development,scores,policy))
            c={**policy,'view':view,'regularization':strength,'development':summary}
            if view in ('xeus','trajectory2'):
                old=next(v for v in prior if v['view']==('xeus' if view=='xeus' else 'hubert_18') and v['regularization']==strength)
                if any(json.dumps(c[k],sort_keys=True)!=json.dumps(old[k],sort_keys=True) for k in c if k!='view'):
                    raise ValueError('Original development candidate did not replay exactly')
                replay+=1
            candidates.append(c);models[(view,strength)]=model
            print('TEMPORAL CANDIDATE',view,strength,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank);temporal=next(c for c in candidates if c['view'] not in ('xeus','trajectory2'))
    selected={'primary':candidates[0],'temporal':temporal,'hubert':next(c for c in candidates if c['view']=='trajectory2'),
        'xeus':next(c for c in candidates if c['view']=='xeus'),
        'matched_hubert':next(c for c in candidates if c['view']=='trajectory2' and c['regularization']==temporal['regularization']),
        'matched_xeus':next(c for c in candidates if c['view']=='xeus' and c['regularization']==temporal['regularization'])}
    hashes={}
    for name,c in selected.items():
        path=FOLDER/f'{name}-model.npz';engine.save_npz(path,**models[(c['view'],c['regularization'])]);hashes[name]=engine.sha(path)
    checked();save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'feature_report_sha256':engine.sha(FOLDER/'feature-report.json'),
        'selected':selected,'ranking':candidates,'weights_sha256':hashes,'train_targets':len(train),'dev_targets':len(dev),
        'exact_development_replay':replay,'evaluation_used_for_selection':False})
    print('TEMPORAL SELECTED',json.dumps({n:{k:c[k] for k in ('view','regularization')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists():raise ValueError('Temporal evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json') or selection['feature_report_sha256']!=engine.sha(FOLDER/'feature-report.json'):
        raise ValueError('Selection provenance changed')
    prior=json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison'];comparison={};noise={};replay={}
    for name,c in selection['selected'].items():
        path=FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]:raise ValueError('Temporal classifier changed')
        with np.load(path,allow_pickle=False) as values:model=dict(values)
        comparison[name]={}
        for cohort in ('existing','griffith','restored'):
            rows,x,present,dataset=load(cohort,c['view']);indices=[i for i,r in enumerate(rows) if r['split'] not in ('train','dev') and r['expected_label']!='other']
            observations=apply([rows[i] for i in indices],gate_scores(predict_ridge(model,x[indices]),present[indices]),c)
            selected={k:[r for r in dataset[k] if r['expected_label']!='other'] for k in ('rows','excluded')}
            comparison[name][cohort]=cohort_summary(selected,observations)
            if name in ('hubert','xeus'):
                if observations!=prior['hubert' if name=='hubert' else 'baseline'][cohort]['predictions']:raise ValueError('Original evaluation prediction changed')
                replay[name+'-'+cohort]=len(observations)
            d=comparison[name][cohort]['evaluation_only']
            print('TEMPORAL EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','false_nasal_accusations','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,present,_=load('noise',c['view']);scores=predict_ridge(model,x);observations=[]
        for final in ['an','ang','en','eng','ian','iang','in','ing','uan','uang']:
            targets=[{**r,'expected_final':final,'expected_label':'back' if final.endswith('ng') else 'front'} for r in rows]
            for state,values in [('gated',gate_scores(scores,present)),('ungated',scores)]:
                observations.extend({**o,'noise_source':r['noise_source'],'gate':state} for o,r in zip(apply(targets,values,c),rows))
        noise[name]={'recordings':len(rows),'summaries':{state:{kind:{'conditions':len(part),
            'false_matches':sum(p['candidate_nasal_match'] for p in part),'false_corrections':sum(p['candidate_nasal_change'] for p in part),
            'abstentions':sum(not p['candidate_nasal_match'] and not p['candidate_nasal_change'] for p in part)}
            for kind in ('synthetic','recorded_environment') for part in [[p for p in observations if p['noise_source']==kind and p['gate']==state]]}
            for state in ('gated','ungated')}}
    checked();save_json(output,{'complete':True,'selection_sha256':engine.sha(FOLDER/'selection.json'),'comparison':comparison,
        'endpoint_exact_replay':replay,'noise':noise,'limits':plan['limits']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
