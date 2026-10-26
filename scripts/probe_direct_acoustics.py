"""Frozen direct spectral/formant comparison; no provider or application writes."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

import probe_xeus_encoder_context as previous
from probe_xeus_encoder_context import load_base,COHORTS,engine
from nasal_direct_acoustics import PARAMETERS,VIEWS,feature_view,fit_blocks,predict_blocks
from nasal_feature_fusion import gate_scores
from nasal_feature_probe import LABELS
from nasal_pair_classifier import audit_training
from train_nasal_feature_probe import save_json

FOLDER=engine.BASE/'direct-acoustics-v1'


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Frozen direct acoustic source changed: '+path)
    if PARAMETERS!=plan['parameters'] or list(VIEWS)!=plan['views']: raise ValueError('Feature definition changed')
    return plan


def prepare():
    if FOLDER.exists(): raise ValueError('Direct acoustic experiment already frozen')
    parent=previous.checked();preflight=engine.BASE/'direct-acoustics-preflight-v1/report.json'
    test=json.loads(preflight.read_text())
    if not test['complete']: raise ValueError('Incomplete direct acoustic preflight')
    for path,digest in test['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Preflight source changed')
    rows,_,_,_=load_base('existing');support=audit_training([r for r in rows if r['split']=='train'])
    if support!=parent['support']: raise ValueError('Strong training support changed')
    paths=[Path(p) for p in parent['sources']]+[previous.FOLDER/n for n in ('plan.json','selection.json','evaluation.json')]
    paths += [Path('scripts')/n for n in ('nasal_direct_acoustics.py','probe_direct_acoustics.py','extract_direct_acoustics.py','nasal_acoustics.py','zipa_context.py')]
    paths += [preflight]+[Path(p) for p in test['sources']]
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):engine.sha(p) for p in paths},
        'parameters':PARAMETERS,'views':list(VIEWS),'regularizations':[.01,.1,1.],
        'cohorts':list(COHORTS),'support':support,'runtime':test['runtime'],
        'calibration_mode':'directional','gate':'unchanged fixed Silero VAD','api_positive_veto':True,
        'imputation':'per-column finite training median; zero only if all training values missing',
        'block_weights':'each named block has equal aggregate standardized weight',
        'pooling':'MFCC/CMN: mean of each vowel third; formants: per-third log-frequency/log-bandwidth medians and missing fractions, both fixed ceilings concatenated',
        'full_baseline_exact_replay_required':True,'same_train_dev_membership_required':True,
        'ranking':['dev error detections','dev normal matches','baseline tie preference','stronger regularization','view order'],
        'evaluate':['primary','best direct','best fused','best baseline','baseline at direct regularization','baseline at fused regularization'],
        'evaluation_previously_explored':True,'weak_targets_used':False,'api_calls':0,'production_enablement':False,
        'limits':['Reference-dependent API bounds remain unchanged.',
            'Normal and erroneous training targets remain confounded with corpus source.',
            'Both formant ceilings apply to every recording, not inferred speaker sex; child-specific ceilings not tested.',
            'Formant poles are noisy acoustic measurements, not verified articulatory locations.',
            'All evaluation cohorts explored; restored cohort shares speakers and one sentence.',
            'Not a reproduction of the landmark paper, and not real-device or noisy-speech acceptance.']}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    print('DIRECT PLAN FROZEN',len(VIEWS)*len(plan['regularizations']),'candidates',flush=True)


def load_features(cohort,view):
    report=json.loads((FOLDER/'feature-report.json').read_text());path=FOLDER/f'{cohort}-features.npz'
    if not report['complete'] or report['plan_sha256']!=engine.sha(FOLDER/'plan.json') or report['outputs'][str(path)]!=engine.sha(path):
        raise ValueError('Incomplete or stale direct acoustic features')
    rows,xeus,present,dataset=load_base(cohort)
    with np.load(path,allow_pickle=False) as stored:
        if stored['ids'].tolist()!=[r['id'] for r in rows]: raise ValueError('Direct feature identity changed')
        if any(stored[k].shape!=(len(rows),d) for k,d in [('mfcc',108),('cmn',108),('formants',54)]): raise ValueError('Direct feature shape mismatch')
        x,blocks=feature_view(xeus,stored['mfcc'],stored['cmn'],stored['formants'],view)
        available=stored['available'] if view!='xeus' else np.ones(len(rows),dtype=bool)
        if available.shape!=(len(rows),) or available.dtype!=np.bool_: raise ValueError('Invalid feature availability')
    return rows,x,blocks,available,present,dataset


def rank(c):
    return (-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches'],
        c['view']!='xeus',-c['regularization'],VIEWS.index(c['view']))


def fit():
    from probe_phonetic_xeus import apply,calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan=checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')): raise ValueError('Direct acoustic selection frozen')
    old=json.loads((previous.FOLDER/'selection.json').read_text())['ranking'];candidates=[];models={}
    for view in VIEWS:
        rows,x,blocks,available,present,dataset=load_features('existing',view)
        train=[i for i,r in enumerate(rows) if r['split']=='train'];dev=[i for i,r in enumerate(rows) if r['split']=='dev']
        if not available[train+dev].all(): raise ValueError('Cannot compare different train/dev membership')
        if audit_training([rows[i] for i in train])!=plan['support']: raise ValueError('Training labels changed')
        labels=np.array([LABELS.index(rows[i]['actual_label']) for i in train]);development=[rows[i] for i in dev]
        denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
        for strength in plan['regularizations']:
            model=fit_blocks(x[train],labels,strength,blocks)
            scores=gate_scores(predict_blocks(model,x[dev]),present[dev])
            policy=calibrate(development,scores,plan['calibration_mode'])
            summary=summarize_denominator(denominator,apply(development,scores,policy))
            c={**policy,'development':summary,'view':view,'regularization':strength,'block_dimensions':blocks}
            if view=='xeus':
                prior=next(v for v in old if v['margin_ms'] is None and v['regularization']==strength)
                compared={**policy,'development':summary}
                if json.dumps(compared,sort_keys=True)!=json.dumps({k:prior[k] for k in compared},sort_keys=True):
                    raise ValueError('Xeus baseline failed exact development replay')
            models[(view,strength)]=model;candidates.append(c)
            print('DIRECT CANDIDATE',view,strength,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank);direct=next(c for c in candidates if 'xeus' not in c['view'])
    fused=next(c for c in candidates if c['view'].startswith('xeus_'))
    selected={'primary':candidates[0],'direct':direct,'fused':fused,'baseline':next(c for c in candidates if c['view']=='xeus'),
        'matched_direct':next(c for c in candidates if c['view']=='xeus' and c['regularization']==direct['regularization']),
        'matched_fused':next(c for c in candidates if c['view']=='xeus' and c['regularization']==fused['regularization'])}
    hashes={}
    for name,c in selected.items():
        path=FOLDER/f'{name}-model.npz';engine.save_npz(path,**models[(c['view'],c['regularization'])]);hashes[name]=engine.sha(path)
    save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'feature_report_sha256':engine.sha(FOLDER/'feature-report.json'),
        'selected_at_utc':datetime.now(timezone.utc).isoformat(),'selected':selected,'ranking':candidates,'weights_sha256':hashes,
        'train_targets':len(train),'dev_targets':len(dev),'baseline_development_exact_replay':3,'evaluation_used_for_selection':False})
    print('DIRECT SELECTED',json.dumps({n:{k:c[k] for k in ('view','regularization')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists(): raise ValueError('Direct acoustic evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json') or selection['feature_report_sha256']!=engine.sha(FOLDER/'feature-report.json'):
        raise ValueError('Direct selection changed')
    previous_reports=json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison']['full']
    comparison={};noise={};replay={}
    for name,c in selection['selected'].items():
        path=FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]: raise ValueError('Direct weights changed')
        with np.load(path,allow_pickle=False) as stored: model=dict(stored)
        comparison[name]={}
        for cohort in ('existing','griffith','restored'):
            rows,x,_,available,present,dataset=load_features(cohort,c['view'])
            indices=[i for i,r in enumerate(rows) if available[i] and r['split'] not in ('train','dev') and r['expected_label']!='other']
            observations=apply([rows[i] for i in indices],gate_scores(predict_blocks(model,x[indices]),present[indices]),c)
            selected={key:[r for r in dataset[key] if r['expected_label']!='other'] for key in ('rows','excluded')}
            comparison[name][cohort]=cohort_summary(selected,observations)
            if name=='baseline':
                if observations!=previous_reports[cohort]['predictions']: raise ValueError('Baseline evaluation failed exact replay')
                replay[cohort]={'targets':len(observations),'all_prediction_fields_identical':True}
            d=comparison[name][cohort]['evaluation_only']
            print('DIRECT EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','known_nasal_errors','false_nasal_accusations','correct_nasal_targets','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,_,available,present,_=load_features('noise',c['view'])
        if not available.all(): raise ValueError('Background extraction incomplete')
        scores=predict_blocks(model,x);summaries={}
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
