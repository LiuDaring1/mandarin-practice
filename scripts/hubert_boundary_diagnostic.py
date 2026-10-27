"""Frozen-head timing sensitivity; manual bounds are diagnostic, never runtime."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import numpy as np

import probe_hubert_fusion as parent
from probe_xeus_encoder_context import engine
from nasal_weighted_fusion import predict_weighted
from nasal_feature_fusion import gate_scores
from train_nasal_feature_probe import save_json

FOLDER=engine.BASE/'hubert-boundaries-v1'
SOURCE=engine.BASE/'boundary-probe-v6'
CONDITIONS=('api','human_clip','automatic_clip','human_rescale','automatic_rescale')


def condition_bounds(current,dataset):
    """Join only identities whose audio, labels and target position still agree."""
    lookup={r['id']:r for r in dataset['rows']};excluded={r['id']:r for r in dataset['excluded']}
    current_ids=[r['id'] for r in current]
    if (len(set(current_ids))!=len(current_ids) or len(lookup)!=len(dataset['rows']) or
            len(excluded)!=len(dataset['excluded']) or set(lookup)&set(excluded) or set(current_ids)!=set(lookup)|set(excluded)):
        raise ValueError('Boundary target membership mismatch')
    result={}
    for row in current:
        uid=row['id'];other=lookup.get(uid,excluded.get(uid))
        for key in ('speaker','position','actual_label','expected_label','audio_sha256'):
            if row.get(key)!=other.get(key):raise ValueError('Boundary identity/label conflict: '+key)
        if uid in lookup:result[uid]=other['bounds']
    return result


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    for path,digest in plan['sources'].items():
        if engine.sha(path)!=digest:raise ValueError('Frozen boundary source changed: '+path)
    return plan


def prepare():
    if FOLDER.exists():raise ValueError('HuBERT boundary diagnostic already frozen')
    base=parent.checked();rows,_,_,_,dataset=parent.load('griffith',.25)
    paths=[Path(p) for p in base['sources']]+[parent.FOLDER/n for n in ('plan.json','selection.json','evaluation.json')]
    paths += [parent.FOLDER/f'{name}-model.npz' for name in ('xeus','hubert','fused')]
    paths += [SOURCE/c/'dataset.json' for c in CONDITIONS]
    paths += [Path(__file__),Path('scripts/xeus_encoder_context.py'),Path('scripts/chinese_hubert_features.py')]
    availability={}
    for condition in CONDITIONS:
        other=json.loads((SOURCE/condition/'dataset.json').read_text())
        bounds=condition_bounds(dataset['rows']+dataset['excluded'],other)
        if condition=='api' and any(bounds[r['id']]!=r['bounds'] for r in rows):raise ValueError('API baseline bounds changed')
        availability[condition]=sum(r['id'] in bounds for r in rows)
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):engine.sha(p) for p in paths},
        'conditions':list(CONDITIONS),'models':['xeus','hubert','fused'],'geometry_available':availability,
        'parent_context':'always chosen using original API target; waveform, normalization, encoder and head unchanged',
        'baseline_pooling_tolerance':1e-4,'baseline_predictions_exact_replay_required':True,
        'posthoc_diagnostic':True,'retuning':False,'new_api_calls':0,'production_enabled':False,
        'limits':['Manual syllable boundaries are unavailable at runtime and are not exact vowel boundaries.',
            'Frozen heads were trained on API bounds; alternate pooling can shift the feature distribution.',
            'Previously explored external cohort only; no condition is selected as a winning deployable system.']})
    print('BOUNDARY PLAN FROZEN',json.dumps(availability),flush=True)


def extract():
    import torch
    from chinese_hubert_features import ChineseHubert,pool_halves
    from phonetic_xeus import XeusModel
    from xeus_encoder_context import preprocess,encode_frames,pool_trajectory
    from nasal_acoustics import read_audio
    from zipa_context import context_interval
    plan=checked();output=FOLDER/'feature-report.json'
    if output.exists():raise ValueError('Boundary features frozen')
    rows,baseline,_,_,dataset=parent.load('griffith',.25)
    conditions={c:condition_bounds(dataset['rows']+dataset['excluded'],json.loads((SOURCE/c/'dataset.json').read_text())) for c in CONDITIONS}
    groups=defaultdict(list)
    for row in rows:groups[row['audio']].append(row)
    originals={r['id']:baseline[i] for i,r in enumerate(rows)}
    hubert=ChineseHubert();xeus=XeusModel();cache=FOLDER/'cache';cache.mkdir(exist_ok=True)
    sources={};vectors={};availability={};failures=[];differences=[];windows=0;plan_sha=engine.sha(FOLDER/'plan.json')
    for audio,members in groups.items():
        digest=engine.sha(audio)
        if any(r['audio_sha256']!=digest for r in members):raise ValueError('Audio identity changed')
        samples=read_audio(Path(audio),max_seconds=180);parents=defaultdict(list)
        for row in members:parents[context_interval(len(samples),row['bounds']['syllable'])].append(row)
        for (a,b),targets in parents.items():
            identity={'plan_sha256':plan_sha,'audio_sha256':digest,'window':[a,b],'ids':[r['id'] for r in targets],
                'hubert':hubert.identity,'xeus':xeus.identity}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();path=cache/(key+'.npz');meta=cache/(key+'.json')
            if not(path.exists() and meta.exists()):
                h=hubert.infer(samples[a:b]);pre=preprocess(xeus,samples[a:b]);x=encode_frames(xeus,pre)
                values=[];validity=[];bad=[];delta=[]
                for row in targets:
                    uid=row['id'];values_for_row=[];valid_for_row=[]
                    for condition in CONDITIONS:
                        try:
                            if uid not in conditions[condition]:raise ValueError('Replacement interval unavailable')
                            bounds=conditions[condition][uid]
                            # HuBERT validates the shared parent envelope before either representation is accepted.
                            hv=pool_halves(h,bounds,a,b-a)[2]
                            xv=pool_trajectory(x,bounds,a,stride=xeus.stride,field=xeus.field)
                            value=np.stack([xv,hv])
                            if condition=='api':
                                difference=float(np.max(np.abs(value-originals[uid])));delta.append(difference)
                                if difference>plan['baseline_pooling_tolerance']:raise RuntimeError('Original boundary feature replay changed')
                                value=originals[uid].copy()
                            values_for_row.append(value);valid_for_row.append(True)
                        except ValueError as error:
                            if condition=='api':raise
                            values_for_row.append(np.zeros((2,2048),dtype=np.float32));valid_for_row.append(False)
                            bad.append({'id':uid,'condition':condition,'reason':str(error)})
                    values.append(np.stack(values_for_row));validity.append(valid_for_row)
                tmp=path.with_suffix('.tmp.npz');engine.save_npz(tmp,ids=np.array([r['id'] for r in targets]),features=np.stack(values),available=np.array(validity,dtype=bool));tmp.replace(path)
                save_json(meta,{'identity':identity,'features_sha256':engine.sha(path),'failures':bad,'maximum_baseline_difference':max(delta)})
                del h,x,pre;torch.mps.empty_cache()
            information=json.loads(meta.read_text())
            if information['identity']!=identity or information['features_sha256']!=engine.sha(path):raise ValueError('Boundary cache changed')
            with np.load(path,allow_pickle=False) as stored:
                if stored['ids'].tolist()!=[r['id'] for r in targets]:raise ValueError('Boundary cache identities changed')
                for uid,value,valid in zip(stored['ids'].tolist(),stored['features'],stored['available']):
                    if uid in vectors:raise ValueError('Duplicate boundary features')
                    vectors[uid]=value;availability[uid]=valid
            failures.extend(information['failures']);differences.append(information['maximum_baseline_difference'])
            sources[str(path)]=engine.sha(path);sources[str(meta)]=engine.sha(meta);windows+=1
        print('BOUNDARY FEATURES',len(vectors),'/',len(rows),'targets',flush=True)
    ids=[r['id'] for r in rows]
    if set(ids)!=set(vectors):raise ValueError('Lost boundary targets')
    features=np.stack([vectors[i] for i in ids]);available=np.stack([availability[i] for i in ids])
    if not np.array_equal(features[:,0],baseline):raise ValueError('Original features changed')
    path=FOLDER/'features.npz';engine.save_npz(path,ids=np.array(ids),features=features,available=available)
    checked();save_json(output,{'complete':True,'plan_sha256':plan_sha,'outputs':{str(path):engine.sha(path)},'cache_sources':sources,
        'parent_windows':windows,'targets':len(ids),'available_by_condition':dict(zip(CONDITIONS,available.sum(axis=0).tolist())),
        'maximum_baseline_feature_difference':max(differences),'failures':failures})


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    from probe_nasal_boundaries import summarize_denominator
    plan=checked();output=FOLDER/'evaluation.json'
    if output.exists():raise ValueError('Boundary evaluation frozen')
    report=json.loads((FOLDER/'feature-report.json').read_text());path=FOLDER/'features.npz'
    if not report['complete'] or report['plan_sha256']!=engine.sha(FOLDER/'plan.json') or report['outputs'][str(path)]!=engine.sha(path):
        raise ValueError('Invalid boundary feature provenance')
    rows,_,_,present,dataset=parent.load('griffith',.25)
    with np.load(path,allow_pickle=False) as stored:
        if stored['ids'].tolist()!=[r['id'] for r in rows]:raise ValueError('Boundary feature IDs changed')
        features=stored['features'];available=stored['available']
    if features.shape!=(len(rows),5,2,2048) or available.shape!=(len(rows),5) or not np.isfinite(features).all():raise ValueError('Invalid boundary feature shape')
    prior=json.loads((parent.FOLDER/'evaluation.json').read_text())['comparison'];selection=json.loads((parent.FOLDER/'selection.json').read_text())
    comparison={}
    for name in plan['models']:
        spec=selection['selected'][name];path=parent.FOLDER/f'{name}-model.npz'
        if engine.sha(path)!=selection['weights_sha256'][name]:raise ValueError('Frozen classifier changed')
        with np.load(path,allow_pickle=False) as stored:model=dict(stored)
        comparison[name]={}
        for ci,condition in enumerate(CONDITIONS):
            indices=np.flatnonzero(available[:,ci]);targets=[rows[i] for i in indices]
            scores=predict_weighted(model,features[indices,ci],spec['hubert_weight'])
            observations=apply(targets,gate_scores(scores,present[indices]),spec)
            if condition=='api' and observations!=prior[name]['griffith']['predictions']:raise ValueError('Unchanged baseline prediction replay failed')
            values=cohort_summary(dataset,observations);ids={r['id'] for r in observations}
            common=[r for r in dataset['rows'] if r['id'] in ids]
            values['common_baseline']=summarize_denominator(common,[p for p in prior[name]['griffith']['predictions'] if p['id'] in ids])
            values['common_condition']=summarize_denominator(common,observations)
            comparison[name][condition]=values
            result=values['evaluation_only']
            print('BOUNDARY EVALUATED',name,condition,json.dumps({k:result[k] for k in ('correct_error_directions','false_nasal_accusations','false_reassurances','correct_nasal_matches','selected_targets','scored_targets')}),flush=True)
    save_json(output,{'complete':True,'posthoc_diagnostic':True,'plan_sha256':engine.sha(FOLDER/'plan.json'),
        'feature_report_sha256':engine.sha(FOLDER/'feature-report.json'),'comparison':comparison,'retuning':False,'limits':plan['limits']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','extract','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'extract':extract,'evaluate':evaluate}[args.mode]()
