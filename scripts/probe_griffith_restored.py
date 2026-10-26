"""Prospective evaluation of spelling-restored targets with already frozen heads.

Shares speakers with the explored Griffith corpus; not a new-speaker blind set.
API is used only by the separately invoked bounded calibration runner. Nothing
here trains, recalibrates, assigns new human labels or writes app progress.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import wave
from zipfile import ZipFile

import numpy as np

from audit_griffith_nominal import BASE, FOLDER as AUDIT, sha
from probe_nasal_kernel import FOLDER as KERNEL, checked as kernel_checked, predict
from train_nasal_feature_probe import save_json

FOLDER = BASE/'griffith-restored-v3'


def checked():
    plan = json.loads((FOLDER/'plan.json').read_text())
    amendment_path = FOLDER/'implementation-amendment.json'
    amendment = json.loads(amendment_path.read_text()) if amendment_path.exists() else None
    for path,digest in plan['sources'].items():
        if sha(path)==digest: continue
        if (amendment and Path(path).resolve()==Path(__file__).resolve()
                and Path(amendment['path']).resolve()==Path(path).resolve() and amendment['before_sha256']==digest
                and sha(amendment['backup'])==digest and sha(path)==amendment['after_sha256']):
            continue
        raise ValueError('Restored evaluation source changed: '+path)
    return plan


def prepare():
    if FOLDER.exists(): raise ValueError('Restored evaluation already prepared')
    kernel_checked()
    inventory = json.loads((AUDIT/'inventory.json').read_text())
    if inventory.get('complete') is not True or inventory['plan_sha256']!=sha(AUDIT/'plan.json'):
        raise ValueError('Stale restored inventory')
    for path,digest in json.loads((AUDIT/'plan.json').read_text())['sources'].items():
        if sha(path)!=digest: raise ValueError('Restored inventory source changed')
    archive = BASE/'griffith/10072-395757_Tsurutani.zip'
    if sha(archive)!=json.loads((BASE/'griffith/source.json').read_text())['sha256']:
        raise ValueError('Original corpus archive changed')
    FOLDER.mkdir();audio_dir=FOLDER/'audio';audio_dir.mkdir()
    records=[]
    with ZipFile(archive) as bundle:
        for rec in inventory['records']:
            import hashlib
            uid='griffith-restored-'+hashlib.sha256(rec['member'].encode()).hexdigest()[:16]
            audio=audio_dir/(uid+'.wav');raw=bundle.read(rec['audio_member'])
            subprocess.run(['ffmpeg','-v','error','-nostdin','-f','wav','-i','pipe:0','-ac','1','-ar','16000',
                '-c:a','pcm_s16le',str(audio)],input=raw,check=True,capture_output=True)
            audio.chmod(0o600)
            with wave.open(str(audio),'rb') as wav: duration=wav.getnframes()/wav.getframerate()
            if not .1<duration<60 or any(not 0<=t['human_syllable'][0]<t['human_syllable'][1]<=duration+.01 for t in rec['targets']):
                raise ValueError('Restored target outside source recording')
            records.append({**rec,'uid':uid,'speaker':'griffith:'+rec['speaker'],'split':'external',
                'core':'read_sentence','audio':str(audio),'duration':duration,'source_sha256':hashlib.sha256(raw).hexdigest()})
    cases=[{'id':r['uid'],'audio':r['audio'],'reference':r['reference'],'core':r['core'],
            'position':r['targets'][0]['position'],'condition':'restored_sentence_carrier'} for r in records if r['targets']]
    limits=['Same speakers as previously explored Griffith corpus; not an independent-speaker acceptance set.',
        'Reference spelling normalization is not pronunciation correction.',
        'Human time bounds are diagnostic only; API bounds still supply inference intervals.']
    save_json(FOLDER/'input.json',{'records':records,'cases':cases,'limits':limits,'evaluation_only':True,
        'inventory_sha256':sha(AUDIT/'inventory.json'),'selection_used_predictions':False})
    paths=[AUDIT/'plan.json',AUDIT/'inventory.json',FOLDER/'input.json',Path(__file__),
        Path('scripts/audit_griffith_nominal.py'),Path('scripts/prepare_griffith_nasal_probe.py'),
        Path('scripts/ise_probe.py'),Path('scripts/suntone_probe.py'),Path('scripts/run_ise_calibration.py'),
        Path('scripts/prepare_nasal_feature_data.py'),Path('scripts/extract_weak_xeus.py'),
        Path('scripts/phonetic_xeus.py'),Path('scripts/nasal_feature_probe.py'),Path('scripts/zipa_context.py'),
        Path('scripts/silero_nasal_gate.py'),Path('scripts/nasal_acoustics.py'),
        Path('scripts/probe_nasal_kernel.py'),Path('scripts/nasal_kernel_classifier.py'),
        Path('scripts/probe_phonetic_xeus.py'),Path('scripts/probe_nasal_boundaries.py')]
    paths += [KERNEL/name for name in ('plan.json','selection.json','kernel-model.npz','linear-model.npz')]
    paths += [BASE/'xeus-v1'/name for name in ('model-source.json','runtime-source.json')]
    paths += [BASE/'silero-vad-v1'/name for name in ('source.json','silero_vad.onnx')]
    paths += [Path(r['audio']) for r in records]
    ledger=Path('data/derived/ise-validation/requests.json');count=len(json.loads(ledger.read_text()))
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):sha(p) for p in paths},
        'models':['kernel','linear'],'layer':19,'view':'trajectory','selected_recordings':len(records),
        'selected_targets':sum(len(r['targets']) for r in records),'ledger_before':count,
        'max_total_calls':count+len(cases),'max_added_calls':len(cases),
        'failure_policy':'No retry; preserve failures. Existing cached results reused.',
        'gate':'Unchanged fixed Silero VAD','training':False,'threshold_selection':False,
        'human_bounds_used_for_inference':False,'production_enabled':False,'limits':limits}
    save_json(FOLDER/'plan.json',plan)
    print('RESTORED PREPARED',len(records),'recordings;',plan['selected_targets'],'targets; ledger',count,'ceiling',plan['max_total_calls'],flush=True)


def validate_dataset(manifest,dataset):
    expected={r['uid']+'-pos'+str(t['position']):{**t,**{k:r[k] for k in ('audio','speaker','split','reference','core')}}
              for r in manifest['records'] for t in r['targets']}
    rows=dataset['rows']+dataset['excluded']
    if len(rows)!=len(expected) or len({r['id'] for r in rows})!=len(rows) or {r['id'] for r in rows}!=set(expected):
        raise ValueError('Restored target denominator or identity changed')
    for row in rows:
        if row['split']!='external': raise ValueError('Restored targets cannot enter fitting partitions')
        for key in ('actual_label','expected_label','expected_final','position','human_syllable','audio','speaker','reference','core'):
            if row[key]!=expected[row['id']][key]: raise ValueError('Restored target metadata changed: '+key)


def load_dataset():
    checked();manifest=json.loads((FOLDER/'input.json').read_text());dataset=json.loads((FOLDER/'dataset.json').read_text())
    validate_dataset(manifest,dataset)
    return dataset


async def align_cached(manifest,probe):
    from ise_probe import public_result,target_at
    from prepare_nasal_feature_data import interval
    rows=[];excluded=[]
    for rec in manifest['records']:
        # An inventory recording can legitimately contain zero eligible targets.
        # It remains in the inventory but needs no alignment request or cache.
        if not rec['targets']: continue
        result=public_result(await probe.call(rec['audio'],rec['reference'],core=rec['core']))
        for target in rec['targets']:
            row={**target,**{k:rec[k] for k in ('speaker','split','audio','reference','core')},
                'id':rec['uid']+'-pos'+str(target['position']),'cohort':'external_griffith',
                'condition':'sentence_error' if target['state']=='nasal_substitution' else 'consensus_control'}
            observation=target_at(result,rec['reference'],target['position'])
            bounds=interval(observation,rec['audio']);row['api_state']=observation['state']
            if bounds is None: excluded.append({**row,'reason':'unusable_cached_interval'})
            else: rows.append({**row,'bounds':bounds,'audio_sha256':sha(rec['audio'])})
    dataset={'rows':rows,'excluded':excluded,'evaluation_only':True,
        'selection_used_predictions':False,'limits':manifest['limits']}
    validate_dataset(manifest,dataset)
    return dataset


def align():
    checked()
    from ise_probe import IseProbe
    output=FOLDER/'dataset.json'
    if output.exists(): raise ValueError('Restored dataset is frozen')
    manifest=json.loads((FOLDER/'input.json').read_text())
    ledger=Path('data/derived/ise-validation/requests.json');before=ledger.read_bytes()
    try:
        dataset=asyncio.run(align_cached(manifest,IseProbe(ledger.parent,allow_paid=False)))
    finally:
        if ledger.read_bytes()!=before: raise ValueError('Cache-only alignment changed the ledger')
    save_json(output,dataset)
    print('RESTORED ALIGNED',len(dataset['rows']),'usable;',len(dataset['excluded']),'unavailable',flush=True)


def extract():
    import torch
    from extract_weak_xeus import trajectory
    from phonetic_xeus import XeusModel
    from nasal_acoustics import read_audio
    from silero_nasal_gate import SileroGate,target_speech
    from zipa_context import context_interval
    from probe_nasal_pairs import save_npz
    plan=checked();dataset=load_dataset()
    if (FOLDER/'feature-report.json').exists(): raise ValueError('Restored features frozen')
    groups=defaultdict(list)
    for row in dataset['rows']: groups[row['audio']].append(row)
    model=XeusModel();gate=SileroGate();cache=FOLDER/'features';cache.mkdir(exist_ok=True)
    vectors={};presence={};excluded=[];sources={}
    for audio,rows in groups.items():
        if any(sha(audio)!=r['audio_sha256'] for r in rows): raise ValueError('Restored audio changed')
        # All source utterances are below 20 seconds in this prospective batch.
        samples=read_audio(Path(audio),max_seconds=60);windows=defaultdict(list)
        for row in rows:
            try: windows[context_interval(len(samples),row['bounds']['syllable'])].append(row)
            except ValueError as error: excluded.append({'id':row['id'],'reason':str(error)})
        vad=gate.score(samples)
        for (a,b),targets in windows.items():
            import hashlib
            identity={'audio_sha256':sha(audio),'window':[a,b],'model':model.identity,
                'targets':[(r['id'],r['bounds']) for r in targets],'layer':19,'view':'trajectory'}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            path=cache/(key+'.npz');meta=cache/(key+'.json')
            if not(path.exists() and meta.exists()):
                speech=torch.from_numpy(samples[a:b].copy()).unsqueeze(0).to(model.device)
                lengths=torch.tensor([b-a],dtype=torch.long,device=model.device)
                model.conditioning_calls=0;model.conditioning_norms=[]
                with torch.inference_mode():
                    encoded,output_lengths=model.model.encode(speech,lengths)
                    final,intermediate=encoded;states=final[0].float().cpu().numpy().copy()
                if (int(output_lengths[0])!=(b-a-model.field)//model.stride+1 or [i for i,_ in intermediate]!=[4,8,12]
                        or model.conditioning_calls!=3 or not all(np.isfinite(v) and v>0 for v in model.conditioning_norms)):
                    raise ValueError('Restored inference changed model path')
                ids=[];values=[];bad=[]
                for row in targets:
                    try: value=trajectory(states,row['bounds'],a,b,model.stride,model.field)
                    except ValueError as error: bad.append({'id':row['id'],'reason':str(error)});continue
                    ids.append(row['id']);values.append(value)
                temporary=path.with_suffix('.tmp.npz')
                save_npz(temporary,ids=np.array(ids,dtype=str),features=np.stack(values) if values else np.empty((0,2048)))
                temporary.replace(path);save_json(meta,{'identity':identity,'features_sha256':sha(path),'excluded':bad})
                del speech,lengths,encoded,final,intermediate,states
                torch.mps.empty_cache()
            info=json.loads(meta.read_text())
            if info['identity']!=json.loads(json.dumps(identity)) or info['features_sha256']!=sha(path):
                raise ValueError('Restored feature cache changed')
            with np.load(path,allow_pickle=False) as stored:
                for uid,value in zip(stored['ids'].tolist(),stored['features']):
                    if uid in vectors: raise ValueError('Duplicate restored feature')
                    vectors[uid]=value
            for row in targets: presence[row['id']]=target_speech(vad,len(samples),row['bounds'])
            excluded.extend(info['excluded']);sources[str(path)]=sha(path);sources[str(meta)]=sha(meta)
        print('RESTORED FEATURES',len(vectors),'targets',flush=True)
    ids=[r['id'] for r in dataset['rows'] if r['id'] in vectors]
    if len(ids)+len(excluded)!=len(dataset['rows']): raise ValueError('Restored feature denominator changed')
    path=FOLDER/'features.npz';save_npz(path,ids=np.array(ids,dtype=str),features=np.stack([vectors[uid] for uid in ids]) if ids else np.empty((0,2048)),
        present=np.array([presence[uid] for uid in ids],dtype=bool))
    checked()
    save_json(FOLDER/'feature-report.json',{'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),
        'dataset_sha256':sha(FOLDER/'dataset.json'),'features_sha256':sha(path),'model':model.identity,'vad':gate.identity,
        'targets':len(ids),'excluded':excluded,'sources':sources,'speech_present_targets':sum(presence[uid] for uid in ids)})
    print('RESTORED FEATURE COMPLETE',len(ids),'targets;',len(excluded),'feature failures',flush=True)


def evaluate():
    from nasal_feature_fusion import gate_scores
    from probe_phonetic_xeus import apply,cohort_summary
    plan=checked();dataset=load_dataset()
    if (FOLDER/'evaluation.json').exists(): raise ValueError('Restored evaluation frozen')
    index=json.loads((FOLDER/'feature-report.json').read_text())
    if (not index.get('complete') or index['plan_sha256']!=sha(FOLDER/'plan.json')
            or index['dataset_sha256']!=sha(FOLDER/'dataset.json') or index['features_sha256']!=sha(FOLDER/'features.npz')):
        raise ValueError('Incomplete or changed restored features')
    selection=json.loads((KERNEL/'selection.json').read_text());lookup={r['id']:r for r in dataset['rows']}
    with np.load(FOLDER/'features.npz',allow_pickle=False) as stored:
        rows=[lookup[uid] for uid in stored['ids'].tolist()];x=stored['features'];present=stored['present']
    if {r['id'] for r in rows}|{r['id'] for r in index['excluded']}!=set(lookup): raise ValueError('Restored feature membership changed')
    comparison={}
    for name in plan['models']:
        candidate=selection['selected'][name]
        with np.load(KERNEL/f'{name}-model.npz',allow_pickle=False) as stored: model=dict(stored)
        observations=apply(rows,gate_scores(predict(model,x,candidate['kind']),present),candidate)
        comparison[name]=cohort_summary(dataset,observations)
        print('RESTORED EVALUATED',name,json.dumps(comparison[name]['evaluation_only']),flush=True)
    save_json(FOLDER/'evaluation.json',{'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),
        'feature_report_sha256':sha(FOLDER/'feature-report.json'),'comparison':comparison,
        'training':False,'threshold_selection':False,'limits':plan['limits']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','align','extract','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'align':align,'extract':extract,'evaluate':evaluate}[args.mode]()
