"""Frozen LATIC alignment, encoder features, and five-model evaluation.

Preparation and real-audio preflight are API-cache-only. LATIC requests require
an imported archive and a separate exact budget, with internal disk mirroring.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime,timezone
import gc
import hashlib
import json
from pathlib import Path

import numpy as np

import latic_validation_runtime as runtime
from audit_latic_nasal_annotations import canonical
from ise_probe import public_result
from nasal_validation_execution import MirroredIseProbe,align_target,durable_json,model_membership,pool_features,xeus_states
from probe_ise_pinyin_pairs import PROVIDER,cache_key,check_ledger
from probe_same_tail_specificity import stage_budget
from resume_ise_pinyin_pairs import input_failure
from probe_nasal_pairs import save_npz

BASE=runtime.BASE
FOLDER=BASE/'latic-pipeline-v1'
MIRROR=Path.home()/'.cache/nasal-api-recovery/latic-pipeline-v1'
BLOCKS=('xeus','hubert','temporal')


def require_new(name):
    if (FOLDER/name).exists() or (MIRROR/name).exists():
        raise ValueError('Output already frozen locally or on internal mirror: '+name)


def save(name,value):
    MIRROR.mkdir(parents=True,exist_ok=True);MIRROR.chmod(0o700)
    durable_json(MIRROR/name,value);durable_json(FOLDER/name,value)


def checked():
    plan=runtime.read(FOLDER/'plan.json');runtime.checked()
    for p,d in plan['sources'].items():
        if runtime.sha(p)!=d:raise ValueError('Frozen pipeline source changed: '+p)
    return plan


def prepare():
    if FOLDER.exists() or (MIRROR/'plan.json').exists():raise ValueError('Pipeline plan already frozen')
    parent=runtime.checked()
    replay=runtime.read(runtime.FOLDER/'replay.json')
    if not replay['complete'] or replay['prediction_rows']!=1680:raise ValueError('Model adapter replay incomplete')
    import probe_hubert_fusion as fusion
    import probe_hubert_temporal as temporal
    rows,x,available,present,_=fusion.load('griffith',.25)
    other,t,other_present,_=temporal.load('griffith','resampled4')
    if rows!=other or not available.all() or not np.array_equal(present,other_present):raise ValueError('Anchor sources disagree')
    selected=[];audios=set();cache_sources={}
    for i in sorted(range(len(rows)),key=lambda i:rows[i]['id']):
        r=rows[i]
        if r['audio'] in audios:continue
        path=PROVIDER/'cache'/(cache_key(r['audio'],r['reference'],r['core'])+'.json')
        result=public_result(runtime.read(path));row={**r,'expected_pinyin':canonical(r['nominal_pinyin'])}
        aligned,ok=align_target(row,result)
        if not ok or aligned['bounds']!=r['bounds'] or aligned['api_state']!=r['api_state']:continue
        selected.append((i,row));audios.add(r['audio']);cache_sources[str(path)]=runtime.sha(path)
        if len(selected)==3:break
    if len(selected)!=3:raise ValueError('Missing three protocol-compatible replay anchors')
    indices=[i for i,_ in selected];anchors=[r for _,r in selected]
    FOLDER.mkdir();save_npz(FOLDER/'anchor-features.npz',paired=x[indices],temporal=t[indices],present=present[indices])
    predictions={name:runtime.predict(spec,anchors,x[indices],t[indices],present[indices]) for name,spec in parent['models'].items()}
    save('anchor-predictions.json',predictions)
    paths=[Path(p) for p in parent['sources']]
    paths += [runtime.FOLDER/n for n in ('plan.json','replay.json')]
    paths += [Path(__file__),Path('scripts/nasal_validation_execution.py'),FOLDER/'anchor-features.npz',FOLDER/'anchor-predictions.json']
    paths += [BASE/n for n in ('xeus-features-v2/griffith-feature-index.json','hubert-temporal-v1/plan.json',
        'silero-vad-v1/parity.json','silero-vad-v1/source.json','silero-vad-v1/silero_vad.onnx')]
    paths += [Path('scripts')/n for n in ('ise_probe.py','suntone_probe.py','probe_ise_pinyin_pairs.py','probe_same_tail_specificity.py',
        'prepare_nasal_feature_data.py','chinese_hubert_features.py','hubert_temporal_features.py','phonetic_xeus.py',
        'nasal_acoustics.py','zipa_context.py','silero_nasal_gate.py','resume_ise_pinyin_pairs.py')]
    paths += [Path(r['audio']) for r in anchors]
    save('plan.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'sources':{**{str(p):runtime.sha(p) for p in paths},**cache_sources},'anchors':anchors,
        'models':parent['models'],'xeus_identity':runtime.read(BASE/'xeus-features-v2/griffith-feature-index.json')['model'],
        'hubert_identity':runtime.read(BASE/'hubert-temporal-v1/plan.json')['model'],
        'vad_identity':runtime.read(BASE/'silero-vad-v1/parity.json')['model'],
        'layers':{'xeus':19,'hubert':18},'feature_tolerance':1e-4,'score_gap_tolerance':1e-5,'all_other_prediction_fields_exact':True,
        'selected_targets':72,'selected_recordings':69,'human_bounds_used_for_inference':False,
        'alignment':'Complete character sequence, expected pinyin agreement, unchanged valid API intervals.',
        'feature_failure':'Independent availability per encoder/view and model; no common-case denominator reduction.',
        'request_policy':'Freeze exact keys and current ledger after import; at most 69 new, never retry; unknown failures stop.',
        'model_or_threshold_changes':False,'api_calls_at_preparation':0,'production_enabled':False})
    print('LATIC PIPELINE FROZEN; 3 old-audio anchors; no new calls',flush=True)


def extract_rows(rows,folder,plan):
    """Resumable encoder-window caches; the target list never selects a model."""
    from nasal_acoustics import read_audio
    from silero_nasal_gate import SileroGate,target_speech
    from zipa_context import context_interval
    gate=SileroGate()
    if gate.identity!=plan['vad_identity']:raise ValueError('VAD runtime changed')
    folder.mkdir(parents=True,exist_ok=True);groups=defaultdict(list);present={};sources={};failures=[];vectors={k:{} for k in BLOCKS}
    for row in rows:
        if runtime.sha(row['audio'])!=row['audio_sha256']:raise ValueError('Inference audio changed')
        groups[row['audio']].append(row)
    # Compute the unchanged gate once, without reference text or target labels.
    for audio,targets in groups.items():
        samples=read_audio(Path(audio),max_seconds=180);vad=gate.score(samples)
        for row in targets:present[row['id']]=target_speech(vad,len(samples),row['bounds'])
    for kind in ('xeus','hubert'):
        if not rows:break
        if kind=='xeus':
            from phonetic_xeus import XeusModel
            model=XeusModel()
        else:
            from chinese_hubert_features import ChineseHubert
            model=ChineseHubert()
        if model.identity!=plan[kind+'_identity']:raise ValueError('Encoder runtime changed: '+kind)
        for audio,targets in groups.items():
            samples=read_audio(Path(audio),max_seconds=180);parents=defaultdict(list)
            for row in targets:
                try:parents[context_interval(len(samples),row['bounds']['syllable'])].append(row)
                except ValueError as error:failures.append({'id':row['id'],'encoder':kind,'reason':str(error)})
            for (a,b),members in parents.items():
                identity={'pipeline_sha256':runtime.sha(FOLDER/'plan.json'),'kind':kind,'model':model.identity,
                    'audio_sha256':runtime.sha(audio),'window':[a,b],'targets':[[r['id'],r['bounds']] for r in members]}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();path=folder/(key+'.npz');meta=folder/(key+'.json')
                if not(path.exists() and meta.exists()):
                    states=xeus_states(model,samples[a:b]) if kind=='xeus' else model.infer(samples[a:b])[model.identity['layers'].index(plan['layers']['hubert'])]
                    values={};bad=[]
                    for j,row in enumerate(members):
                        pooled,errors=pool_features(kind,states,row,a,b-a,model.stride,model.field)
                        for name,value in pooled.items():values[name+'_'+str(j)]=value
                        for name,reason in errors.items():bad.append({'id':row['id'],'block':name,'reason':reason})
                    save_npz(path,**values);durable_json(meta,{'identity':identity,'sha256':runtime.sha(path),'failures':bad})
                    del states
                info=runtime.read(meta)
                if info['identity']!=identity or info['sha256']!=runtime.sha(path):raise ValueError('Encoder cache changed')
                with np.load(path,allow_pickle=False) as data:
                    for j,row in enumerate(members):
                        for name in BLOCKS:
                            k=name+'_'+str(j)
                            if k in data:vectors[name][row['id']]=data[k]
                failures.extend(info['failures']);sources[str(path)]=runtime.sha(path);sources[str(meta)]=runtime.sha(meta)
            print('LATIC FEATURES',kind,len(vectors[kind]),'/',len(rows),flush=True)
        del model;gc.collect()
        import torch
        if torch.backends.mps.is_available():torch.mps.empty_cache()
    ids=[r['id'] for r in rows];n=len(ids)
    paired=np.zeros((n,2,2048),dtype=np.float32);temporal=np.zeros((n,4096),dtype=np.float32);available=np.zeros((n,3),dtype=bool)
    for i,uid in enumerate(ids):
        for j,name in enumerate(BLOCKS):
            if uid in vectors[name]:
                (paired[:,j] if j<2 else temporal)[i]=vectors[name][uid];available[i,j]=True
    return {'ids':np.array(ids,dtype=str),'paired':paired,'temporal':temporal,'available':available,
        'present':np.array([present[uid] for uid in ids],dtype=bool)}, {'sources':sources,'failures':failures}


def compare_prediction(actual,expected,tolerance):
    if set(actual)!=set(expected):raise ValueError('Prediction fields changed')
    for key in actual:
        if key in ('scores','gap'):
            if not np.allclose(actual[key],expected[key],atol=tolerance,rtol=0):raise ValueError('Prediction numeric replay changed')
        elif actual[key]!=expected[key]:raise ValueError('Prediction decision/identity changed')


def preflight():
    plan=checked();require_new('preflight.json')
    rows=plan['anchors'];aligned=[]
    for row in rows:
        key=cache_key(row['audio'],row['reference'],row['core'])
        result=public_result(runtime.read(PROVIDER/'cache'/(key+'.json')));new,ok=align_target(row,result)
        if not ok or new['bounds']!=row['bounds']:raise ValueError('Cached alignment did not replay')
        aligned.append(new)
    values,details=extract_rows(aligned,FOLDER/'preflight-cache',plan)
    if not values['available'].all():raise ValueError('Preflight feature unavailable')
    with np.load(FOLDER/'anchor-features.npz',allow_pickle=False) as previous:
        deltas={k:float(np.max(np.abs(values[k]-previous[k]))) for k in ('paired','temporal')}
        if any(d>plan['feature_tolerance'] for d in deltas.values()) or not np.array_equal(values['present'],previous['present']):
            raise ValueError('Feature/VAD preflight failed')
    expected=runtime.read(FOLDER/'anchor-predictions.json');score_delta=0.;gap_delta=0.
    for name,spec in plan['models'].items():
        observed=runtime.predict(spec,aligned,values['paired'],values['temporal'],values['present'])
        for a,b in zip(observed,expected[name]):
            compare_prediction(a,b,plan['score_gap_tolerance'])
            score_delta=max(score_delta,float(np.max(np.abs(np.array(a['scores'])-b['scores']))));gap_delta=max(gap_delta,abs(a['gap']-b['gap']))
    checked();save('preflight.json',{'complete':True,'plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'targets':len(rows),'alignment_exact':True,'feature_max_differences':deltas,'vad_exact':True,
        'prediction_rows':15,'all_nonnumeric_prediction_fields_exact':True,'maximum_score_difference':score_delta,
        'maximum_gap_difference':gap_delta,'cache_sources':details['sources'],'new_api_calls':0,
        'latic_audio_used':False,'new_accuracy_evidence':False})
    print('LATIC AUDIO PREFLIGHT PASSED',deltas,'score delta',score_delta,flush=True)


def import_checked():
    checked();folder=runtime.FOLDER/'audio-import';manifest=runtime.read(folder/'manifest.json');plan=runtime.read(folder/'plan.json')
    if not manifest['complete'] or manifest['plan_sha256']!=runtime.sha(folder/'plan.json') or plan['runner_plan_sha256']!=runtime.sha(runtime.FOLDER/'plan.json'):
        raise ValueError('Imported audio provenance changed')
    if runtime.sha(plan['archive'])!=plan['archive_sha256']:raise ValueError('Official archive changed')
    expected={r['id']:r for r in runtime.selected_rows()};seen=[]
    for record in manifest['records']+manifest['excluded']:
        for target in record['targets']:
            if expected.get(target['id'])!=target:raise ValueError('Imported target labels/positions changed')
            seen.append(target['id'])
    if len(seen)!=72 or set(seen)!=set(expected):raise ValueError('Imported denominator changed')
    for record in manifest['records']:
        if runtime.sha(record['audio'])!=record['audio_sha256']:raise ValueError('Imported audio changed')
    return manifest


def budget():
    checked();manifest=import_checked();require_new('api-plan.json')
    pre=runtime.read(FOLDER/'preflight.json')
    if not pre['complete'] or pre['plan_sha256']!=runtime.sha(FOLDER/'plan.json'):raise ValueError('Live audio preflight required')
    requests=[{'audio':r['audio'],'reference':r['reference'],'core':r['core'],
        'key':cache_key(r['audio'],r['reference'],r['core'])} for r in manifest['records']]
    plan=stage_budget(requests,runtime.read(PROVIDER/'requests.json'),PROVIDER/'cache')
    if len(plan['new_request_keys'])>69:raise ValueError('LATIC allowance exceeded')
    save('api-plan.json',{**plan,'pipeline_plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'import_manifest_sha256':runtime.sha(runtime.FOLDER/'audio-import/manifest.json'),
        'historical_ledger_contains_one_possibly_sent_call':True})
    print('LATIC API BUDGET',len(plan['new_request_keys']),'new; cap',plan['maximum_total_attempts'],flush=True)


def api_checked():
    import_checked();plan=runtime.read(FOLDER/'api-plan.json')
    if (plan['pipeline_plan_sha256']!=runtime.sha(FOLDER/'plan.json') or
        plan['import_manifest_sha256']!=runtime.sha(runtime.FOLDER/'audio-import/manifest.json')):
        raise ValueError('API plan source changed')
    for p,d in plan['existing_caches'].items():
        if runtime.sha(p)!=d:raise ValueError('Cached result changed')
    for row in plan['requests']:
        if cache_key(row['audio'],row['reference'],row['core'])!=row['key']:raise ValueError('Request changed')
    return plan


async def api(allow_paid=False):
    plan=api_checked();require_new('api-result.json')
    check_ledger(plan['ledger_prefix'],runtime.read(PROVIDER/'requests.json'),plan['new_request_keys'])
    probe=MirroredIseProbe(PROVIDER,mirror=MIRROR/'provider',allow_paid=allow_paid,max_calls=plan['maximum_total_attempts']);results={}
    for i,row in enumerate(plan['requests']):
        result=public_result(await probe.call(row['audio'],row['reference'],core=row['core']))
        results[row['key']]={'result':result,'cache_sha256':runtime.sha(PROVIDER/'cache'/(row['key']+'.json'))}
        save('api-progress.json',{'results':results})
        if result['status']!='ok' and not input_failure(result):raise RuntimeError('Unclassified API failure; inspect, never automatically retry')
        print('LATIC API',i+1,'/',len(plan['requests']),result['status'],flush=True)
    added=check_ledger(plan['ledger_prefix'],runtime.read(PROVIDER/'requests.json'),plan['new_request_keys'])
    save('api-result.json',{'complete':True,'api_plan_sha256':runtime.sha(FOLDER/'api-plan.json'),
        'results':results,'new_calls':added,'cumulative_reservations':len(runtime.read(PROVIDER/'requests.json'))})


def align():
    api_checked();manifest=import_checked();result=runtime.read(FOLDER/'api-result.json')
    require_new('dataset.json')
    if not result['complete'] or result['api_plan_sha256']!=runtime.sha(FOLDER/'api-plan.json'):raise ValueError('API results changed')
    for key,value in result['results'].items():
        if runtime.sha(PROVIDER/'cache'/(key+'.json'))!=value['cache_sha256']:raise ValueError('API response changed')
    rows=[];excluded=[]
    for record in manifest['excluded']:
        excluded.extend({**t,'reason':'import:'+record['reason']} for t in record['targets'])
    for record in manifest['records']:
        key=cache_key(record['audio'],record['reference'],record['core'])
        for target in record['targets']:
            row={**target,**{k:record[k] for k in ('audio','audio_sha256','reference','core')},
                'condition':'sentence_error' if target['role']=='error' else 'normal_notation'}
            item,ok=align_target(row,result['results'][key]['result']);(rows if ok else excluded).append(item)
    if len(rows)+len(excluded)!=72:raise ValueError('Alignment lost targets')
    save('dataset.json',{'rows':rows,'excluded':excluded,'api_result_sha256':runtime.sha(FOLDER/'api-result.json'),
        'selected_targets':72,'training_allowed':False})
    print('LATIC ALIGNED',len(rows),'available',len(excluded),'unknown',flush=True)


def features():
    plan=checked();api_checked();data=runtime.read(FOLDER/'dataset.json')
    if data['api_result_sha256']!=runtime.sha(FOLDER/'api-result.json'):raise ValueError('Alignment provenance changed')
    require_new('feature-report.json')
    values,details=extract_rows(data['rows'],FOLDER/'feature-cache',plan)
    save_npz(FOLDER/'features.npz',**values)
    save('feature-report.json',{'complete':True,'pipeline_plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'dataset_sha256':runtime.sha(FOLDER/'dataset.json'),'features_sha256':runtime.sha(FOLDER/'features.npz'),
        **details,'available_by_block':dict(zip(BLOCKS,values['available'].sum(axis=0).tolist()))})


def evaluate():
    plan=checked();api_checked();data=runtime.read(FOLDER/'dataset.json');report=runtime.read(FOLDER/'feature-report.json')
    require_new('evaluation.json')
    if (not report['complete'] or report['pipeline_plan_sha256']!=runtime.sha(FOLDER/'plan.json') or
        report['dataset_sha256']!=runtime.sha(FOLDER/'dataset.json') or report['features_sha256']!=runtime.sha(FOLDER/'features.npz')):
        raise ValueError('Feature provenance changed')
    for p,d in report['sources'].items():
        if runtime.sha(p)!=d:raise ValueError('Feature cache changed')
    comparisons={}
    with np.load(FOLDER/'features.npz',allow_pickle=False) as values:
        if values['ids'].tolist()!=[r['id'] for r in data['rows']]:raise ValueError('Feature identity changed')
        for name,spec in plan['models'].items():
            mask=model_membership(name,values['available']);indices=np.flatnonzero(mask);rows=[data['rows'][i] for i in indices]
            observed=runtime.predict(spec,rows,values['paired'][mask],values['temporal'][mask],values['present'][mask])
            comparisons[name]={'summary':runtime.summarize_selected(runtime.selected_rows(),observed),'predictions':observed}
    save('evaluation.json',{'complete':True,'pipeline_plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'feature_report_sha256':runtime.sha(FOLDER/'feature-report.json'),'comparisons':comparisons,
        'new_fit_or_threshold_selection':False,'production_enabled':False})
    print('LATIC FIVE-MODEL EVALUATION COMPLETE; no automatic production activation',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','preflight','budget','api','align','features','evaluate'])
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='api':asyncio.run(api(args.allow_paid))
    else:{'prepare':prepare,'preflight':preflight,'budget':budget,'align':align,'features':features,'evaluate':evaluate}[args.mode]()
