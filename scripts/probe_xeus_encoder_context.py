"""Train/dev-only comparison of full and restricted Xeus encoder context."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

import numpy as np

import probe_nasal_pairs as engine
import probe_nasal_kernel as previous
from nasal_feature_fusion import feature_source,gate_scores
from nasal_feature_probe import LABELS,fit_ridge,predict_ridge
from nasal_pair_classifier import audit_training
from train_nasal_feature_probe import save_json

FOLDER=engine.BASE/'xeus-encoder-context-v1'
COHORTS=('existing','griffith','restored','noise')


def load_base(cohort):
    if cohort in ('existing','griffith'):
        rows,x,dataset=engine.load(cohort)
        return rows,feature_source(x,'xeus'),engine.present(rows,cohort),dataset
    if cohort=='restored':
        from probe_griffith_restored import FOLDER as restored,load_dataset
        dataset=load_dataset();rows=dataset['rows']
        with np.load(restored/'features.npz',allow_pickle=False) as stored:
            if stored['ids'].tolist()!=[r['id'] for r in rows]: raise ValueError('Restored feature identity changed')
            return rows,stored['features'],stored['present'],dataset
    if cohort=='noise':
        dataset=json.loads((engine.SOURCE/'noise/dataset.json').read_text());rows=dataset['rows']
        evidence=json.loads((engine.SOURCE/'evidence.json').read_text())['cohorts']['noise']
        with np.load(previous.FOLDER/'noise-features.npz',allow_pickle=False) as stored:
            if stored['ids'].tolist()!=[r['id'] for r in rows]: raise ValueError('Background feature identity changed')
            return rows,feature_source(stored['features'],'xeus'),np.array([evidence[r['id']]['present'] for r in rows],dtype=bool),dataset
    raise ValueError('Unknown context cohort')


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Frozen context source changed: '+path)
    return plan


def prepare():
    if FOLDER.exists(): raise ValueError('Encoder context experiment already frozen')
    parent=previous.checked()
    preflight=engine.BASE/'xeus-encoder-context-preflight-v1/report.json'
    test=json.loads(preflight.read_text())
    if not test.get('complete') or max(test['full_encoder_maximum_difference'],test['original_pooled_maximum_difference'])>1e-4:
        raise ValueError('Full-path preflight failed')
    for path,digest in test['sources'].items():
        if engine.sha(path)!=digest: raise ValueError('Preflight source changed')
    rows,_,_,_=load_base('existing');support=audit_training([r for r in rows if r['split']=='train'])
    if support!=parent['support']: raise ValueError('Strong training support changed')
    paths=[Path(p) for p in parent['sources']]
    paths += [previous.FOLDER/name for name in ('plan.json','selection.json','evaluation.json')]
    paths += [engine.BASE/'griffith-restored-v3'/name for name in ('plan.json','implementation-amendment.json','input.json','dataset.json','feature-report.json','features.npz','evaluation.json')]
    paths += [preflight,Path(__file__),Path('scripts/extract_xeus_encoder_context.py'),Path('scripts/xeus_encoder_context.py'),Path('scripts/probe_griffith_restored.py')]
    paths += [engine.BASE/'xeus-v1'/name for name in ('model-source.json','runtime-source.json')]
    counts={}
    for cohort in COHORTS:
        rows,_,_,dataset=load_base(cohort)
        counts[cohort]={'available':len(rows),'unavailable':len(dataset.get('excluded',[]))}
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):engine.sha(p) for p in paths},
        'cohorts':list(COHORTS),'counts':counts,'support':support,'margins_ms':[None,150,450],
        'regularizations':[.01,.1,1.],'layer':19,'view':'trajectory','feature_source':'xeus','calibration_mode':'directional',
        'crop_stage':'after unchanged full-parent frontend and preencoder, before contextual encoder',
        'parent_normalization_unchanged':True,'frame_grid_unchanged':True,'encoder_training':False,'weak_targets_used':False,
        'reference_text_input':False,'gate':'unchanged Silero VAD','api_positive_veto':True,'full_feature_replay_tolerance':1e-4,
        'same_train_dev_membership_required':True,'evaluation_previously_explored':True,
        'ranking':['dev error detections','dev normal matches','full context tie preference','stronger regularization','wider local margin'],
        'evaluate':['primary','best local','best full','full at best local regularization'],
        'production_enablement':False,'api_calls':0,
        'limits':['Local encoder still sees frontend features normalized on its complete parent window.',
            'All external sets already explored; restored set shares speakers and contains only one distinct sentence.',
            'Reference-dependent API bounds remain unchanged.',
            'Existing nonspeech targets cover complete recordings, so their local crops retain the full frame sequence.']}
    FOLDER.mkdir();save_json(FOLDER/'plan.json',plan)
    print('CONTEXT PLAN FROZEN',json.dumps(counts),'9 candidates',flush=True)


def load_features(cohort):
    report=json.loads((FOLDER/'feature-report.json').read_text());path=FOLDER/f'{cohort}-features.npz'
    if (not report.get('complete') or report['plan_sha256']!=engine.sha(FOLDER/'plan.json')
            or report['outputs'][str(path)]!=engine.sha(path)):
        raise ValueError('Incomplete or stale context feature report')
    rows,_,present,dataset=load_base(cohort)
    with np.load(path,allow_pickle=False) as stored:
        if stored['ids'].tolist()!=[r['id'] for r in rows]: raise ValueError('Context feature identity changed')
        features=stored['features'];available=stored['available']
    if features.shape!=(len(rows),3,2048) or available.shape!=(len(rows),3): raise ValueError('Unexpected context feature shape')
    if not np.isfinite(features[available]).all(): raise ValueError('Nonfinite available feature')
    return rows,features,available,present,dataset


def rank(candidate):
    return (-candidate['development']['correct_error_directions'],-candidate['development']['correct_nasal_matches'],
        candidate['margin_ms'] is not None,-candidate['regularization'],-(candidate['margin_ms'] or 0))


def fit():
    from probe_phonetic_xeus import apply,calibrate
    from probe_nasal_boundaries import summarize_denominator
    plan=checked()
    if (FOLDER/'selection.json').exists() or list(FOLDER.glob('*-model.npz')): raise ValueError('Context selection frozen')
    rows,x,available,present,dataset=load_features('existing')
    train=[i for i,r in enumerate(rows) if r['split']=='train'];dev=[i for i,r in enumerate(rows) if r['split']=='dev']
    if not available[train+dev].all(): raise ValueError('Context comparison must keep identical train/dev targets')
    strong=[rows[i] for i in train];development=[rows[i] for i in dev]
    if audit_training(strong)!=plan['support']: raise ValueError('Training support changed')
    denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    labels=np.array([LABELS.index(r['actual_label']) for r in strong]);candidates=[];models={}
    old=json.loads((previous.FOLDER/'selection.json').read_text())['ranking']
    for index,margin in enumerate(plan['margins_ms']):
        for strength in plan['regularizations']:
            model=fit_ridge(x[train,index],labels,strength)
            scores=gate_scores(predict_ridge(model,x[dev,index]),present[dev])
            policy=calibrate(development,scores,plan['calibration_mode'])
            summary=summarize_denominator(denominator,apply(development,scores,policy))
            if margin is None:
                prior=next(c for c in old if c['kind']=='linear' and c['regularization']==strength)
                compared={**policy,'development':summary}
                if json.dumps(compared,sort_keys=True)!=json.dumps({k:prior[k] for k in compared},sort_keys=True):
                    raise ValueError('Original full-context development failed exact replay')
            c={**policy,'development':summary,'margin_ms':margin,'regularization':strength}
            candidates.append(c);models[(margin,strength)]=model
            print('CONTEXT CANDIDATE',margin,strength,summary['correct_error_directions'],summary['correct_nasal_matches'],flush=True)
    candidates.sort(key=rank);local=next(c for c in candidates if c['margin_ms'] is not None)
    selected={'primary':candidates[0],'local':local,'full':next(c for c in candidates if c['margin_ms'] is None),
        'matched_full':next(c for c in candidates if c['margin_ms'] is None and c['regularization']==local['regularization'])}
    hashes={}
    for name,c in selected.items():
        path=FOLDER/f'{name}-model.npz';engine.save_npz(path,**models[(c['margin_ms'],c['regularization'])]);hashes[name]=engine.sha(path)
    save_json(FOLDER/'selection.json',{'plan_sha256':engine.sha(FOLDER/'plan.json'),'feature_report_sha256':engine.sha(FOLDER/'feature-report.json'),
        'selected_at_utc':datetime.now(timezone.utc).isoformat(),'selected':selected,'ranking':candidates,'weights_sha256':hashes,
        'train_targets':len(train),'dev_targets':len(dev),'full_development_exact_replay':3,'evaluation_used_for_selection':False})
    print('CONTEXT SELECTED',json.dumps({n:{k:c[k] for k in ('margin_ms','regularization')} for n,c in selected.items()}),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists(): raise ValueError('Context evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text())
    if selection['plan_sha256']!=engine.sha(FOLDER/'plan.json') or selection['feature_report_sha256']!=engine.sha(FOLDER/'feature-report.json'):
        raise ValueError('Context selection changed')
    previous_reports=json.loads((previous.FOLDER/'evaluation.json').read_text())['comparison']['linear']
    restored_report=json.loads((engine.BASE/'griffith-restored-v3/evaluation.json').read_text())['comparison']['linear']
    comparison={};noise={};replay={}
    for name,c in selection['selected'].items():
        path=FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]: raise ValueError('Context weights changed')
        with np.load(path,allow_pickle=False) as stored:model=dict(stored)
        index=plan['margins_ms'].index(c['margin_ms']);comparison[name]={}
        for cohort in ('existing','griffith','restored'):
            rows,x,available,present,dataset=load_features(cohort)
            indices=[i for i,r in enumerate(rows) if available[i,index] and r['split'] not in ('train','dev') and r['expected_label']!='other']
            observations=apply([rows[i] for i in indices],gate_scores(predict_ridge(model,x[indices,index]),present[indices]),c)
            selected={key:[r for r in dataset[key] if r['expected_label']!='other'] for key in ('rows','excluded')}
            comparison[name][cohort]=cohort_summary(selected,observations)
            if name=='full':
                old=restored_report if cohort=='restored' else previous_reports[cohort]
                if observations!=old['predictions']: raise ValueError('Full context evaluation failed exact replay')
                replay[cohort]={'targets':len(observations),'all_prediction_fields_identical':True}
            d=comparison[name][cohort]['evaluation_only']
            print('CONTEXT EVALUATED',name,cohort,json.dumps({k:d[k] for k in ('correct_error_directions','known_nasal_errors','false_nasal_accusations','correct_nasal_targets','false_reassurances','correct_nasal_matches','uncertain_nasal_targets')}),flush=True)
        rows,x,available,present,_=load_features('noise')
        if not available[:,index].all(): raise ValueError('Background inference incomplete')
        scores=predict_ridge(model,x[:,index]);summaries={}
        for state,values in [('gated',gate_scores(scores,present)),('ungated',scores)]:
            observations=[]
            for final in ['an','ang','en','eng','ian','iang','in','ing','uan','uang']:
                targets=[{**r,'expected_final':final,'expected_label':'back' if final.endswith('ng') else 'front'} for r in rows]
                observations.extend({**p,'noise_source':r['noise_source']} for p,r in zip(apply(targets,values,c),rows))
            summaries[state]={kind:{'conditions':len(part),'false_matches':sum(p['candidate_nasal_match'] for p in part),
                'false_corrections':sum(p['candidate_nasal_change'] for p in part),
                'abstentions':sum(not p['candidate_nasal_match'] and not p['candidate_nasal_change'] for p in part)}
                for kind in ('synthetic','recorded_environment') for part in [[p for p in observations if p['noise_source']==kind]]}
        noise[name]={'recordings':len(rows),'summaries':summaries}
    save_json(output,{'complete':True,'selection_sha256':engine.sha(FOLDER/'selection.json'),'comparison':comparison,
        'noise':noise,'original_full_replay':replay,'limits':plan['limits']+['No noisy speech, omission, repetition or real-device evaluation.']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'fit':fit,'evaluate':evaluate}[args.mode]()
