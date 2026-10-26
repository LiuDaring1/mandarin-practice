"""Resumable label-free Mandarin HuBERT features, with per-parent provenance."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from chinese_hubert_features import ChineseHubert,pool_halves
from nasal_acoustics import read_audio
from probe_chinese_hubert import FOLDER,checked,load_base,engine
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def main():
    plan=checked();report_path=FOLDER/'feature-report.json'
    if report_path.exists(): raise ValueError('HuBERT features frozen')
    model=ChineseHubert();cache=FOLDER/'features';cache.mkdir(exist_ok=True)
    if model.identity!=plan['model']: raise ValueError('HuBERT runtime differs from preflight')
    sources={};outputs={};summaries={};started=time.monotonic();plan_sha=engine.sha(FOLDER/'plan.json')
    for cohort in plan['cohorts']:
        rows,_,_,_=load_base(cohort);groups=defaultdict(list)
        for row in rows: groups[row['audio']].append(row)
        vectors={};availability={};failures=[];windows=0
        for audio,targets in groups.items():
            digest=engine.sha(audio)
            if any(digest!=r['audio_sha256'] for r in targets): raise ValueError('HuBERT audio changed')
            samples=read_audio(Path(audio),max_seconds=180);grouped=defaultdict(list)
            for row in targets: grouped[context_interval(len(samples),row['bounds']['syllable'])].append(row)
            for (a,b),members in grouped.items():
                identity={'plan_sha256':plan_sha,'model':model.identity,'audio_sha256':digest,
                    'window':[a,b],'targets':[(r['id'],r['bounds']) for r in members]}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                path=cache/(key+'.npz');meta=cache/(key+'.json')
                if not(path.exists() and meta.exists()):
                    states=model.infer(samples[a:b]);values=[];available=[];bad=[]
                    for row in members:
                        try:
                            value=pool_halves(states,row['bounds'],a,b-a,model.stride,model.field)
                            values.append(value);available.append(True)
                        except ValueError as error:
                            values.append(np.zeros((4,2048),dtype=np.float32));available.append(False)
                            bad.append({'id':row['id'],'reason':str(error)})
                    temporary=path.with_suffix('.tmp.npz')
                    engine.save_npz(temporary,ids=np.array([r['id'] for r in members]),features=np.stack(values),available=np.array(available,dtype=bool))
                    temporary.replace(path)
                    save_json(meta,{'identity':identity,'features_sha256':engine.sha(path),'failures':bad})
                    del states
                metadata=json.loads(meta.read_text())
                if metadata['identity']!=json.loads(json.dumps(identity)) or metadata['features_sha256']!=engine.sha(path):
                    raise ValueError('HuBERT cache changed')
                with np.load(path,allow_pickle=False) as stored:
                    if stored['ids'].tolist()!=[r['id'] for r in members]: raise ValueError('HuBERT cache membership changed')
                    for uid,value,valid in zip(stored['ids'].tolist(),stored['features'],stored['available']):
                        if uid in vectors: raise ValueError('Duplicate HuBERT feature')
                        vectors[uid]=value;availability[uid]=valid
                failures.extend(metadata['failures']);sources[str(path)]=engine.sha(path);sources[str(meta)]=engine.sha(meta);windows+=1
            print('HUBERT FEATURES',cohort,len(vectors),'/',len(rows),'targets;',windows,'parent windows',flush=True)
        ids=[r['id'] for r in rows]
        if set(vectors)!=set(ids): raise ValueError('HuBERT extraction lost targets')
        values=np.stack([vectors[uid] for uid in ids]);available=np.array([availability[uid] for uid in ids],dtype=bool)
        path=FOLDER/f'{cohort}-features.npz';engine.save_npz(path,ids=np.array(ids),features=values,available=available)
        outputs[str(path)]=engine.sha(path)
        summaries[cohort]={'targets':len(ids),'recordings':len(groups),'parent_windows':windows,'available':int(available.sum()),'failures':failures}
        print('HUBERT COHORT COMPLETE',cohort,len(ids),'available',int(available.sum()),flush=True)
    checked()
    save_json(report_path,{'complete':True,'plan_sha256':plan_sha,'model':model.identity,'outputs':outputs,'cohorts':summaries,
        'cache_sources':sources,'elapsed_seconds':time.monotonic()-started,'reference_text_input':False})
    print('HUBERT EXTRACTION COMPLETE',flush=True)


if __name__=='__main__': main()
