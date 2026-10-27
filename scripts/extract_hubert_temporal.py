"""Resumable time-detail extraction under the original Chinese HuBERT runtime."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from chinese_hubert_features import ChineseHubert,LAYERS
from hubert_temporal_features import VIEWS,pool_views
from nasal_acoustics import read_audio
from probe_hubert_temporal import FOLDER,checked,engine,previous
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def main():
    plan=checked();output=FOLDER/'feature-report.json'
    if output.exists():raise ValueError('Temporal features already frozen')
    model=ChineseHubert()
    if model.identity!=plan['model']:raise ValueError('HuBERT runtime changed')
    cache=FOLDER/'cache';cache.mkdir(exist_ok=True);sources={};outputs={};summaries={};plan_sha=engine.sha(FOLDER/'plan.json');started=time.monotonic()
    for cohort in plan['cohorts']:
        rows,baseline,available,_,_=previous.load_features(cohort,'hubert_18')
        if not available.all():raise ValueError('Original temporal membership changed')
        originals={r['id']:baseline[i] for i,r in enumerate(rows)};groups=defaultdict(list)
        for row in rows:groups[row['audio']].append(row)
        vectors={};frame_counts={};differences=[];windows=0
        for audio,members in groups.items():
            digest=engine.sha(audio)
            if any(r['audio_sha256']!=digest for r in members):raise ValueError('Audio source changed')
            samples=read_audio(Path(audio),max_seconds=180);parents=defaultdict(list)
            for row in members:parents[context_interval(len(samples),row['bounds']['syllable'])].append(row)
            for (a,b),targets in parents.items():
                identity={'plan_sha256':plan_sha,'model':model.identity,'audio_sha256':digest,'window':[a,b],
                    'targets':[[r['id'],r['bounds']] for r in targets]}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();path=cache/(key+'.npz');meta=cache/(key+'.json')
                if not(path.exists() and meta.exists()):
                    states=model.infer(samples[a:b])[LAYERS.index(plan['layer'])];values={k:[] for k in VIEWS};counts=[];delta=[]
                    for row in targets:
                        views,count=pool_views(states,row['bounds'],a,b-a,model.stride,model.field)
                        difference=float(np.max(np.abs(views['trajectory2']-originals[row['id']])))
                        if difference>plan['baseline_pooling_tolerance']:raise ValueError('Original temporal features failed replay')
                        delta.append(difference);views['trajectory2']=originals[row['id']].copy()
                        for view in VIEWS:values[view].append(views[view])
                        counts.append(count)
                    temporary=path.with_suffix('.tmp.npz')
                    engine.save_npz(temporary,ids=np.array([r['id'] for r in targets]),frame_counts=np.array(counts),**{k:np.stack(v) for k,v in values.items()});temporary.replace(path)
                    save_json(meta,{'identity':identity,'features_sha256':engine.sha(path),'maximum_baseline_difference':max(delta)})
                    del states
                information=json.loads(meta.read_text())
                if information['identity']!=identity or information['features_sha256']!=engine.sha(path):raise ValueError('Temporal cache changed')
                with np.load(path,allow_pickle=False) as stored:
                    if stored['ids'].tolist()!=[r['id'] for r in targets]:raise ValueError('Temporal cache target identity changed')
                    for i,uid in enumerate(stored['ids'].tolist()):
                        if uid in vectors:raise ValueError('Duplicate temporal target')
                        vectors[uid]={k:stored[k][i] for k in VIEWS};frame_counts[uid]=int(stored['frame_counts'][i])
                sources[str(path)]=engine.sha(path);sources[str(meta)]=engine.sha(meta);differences.append(information['maximum_baseline_difference']);windows+=1
            print('TEMPORAL FEATURES',cohort,len(vectors),'/',len(rows),'targets;',windows,'windows',flush=True)
        ids=[r['id'] for r in rows]
        if set(ids)!=set(vectors):raise ValueError('Temporal extraction lost targets')
        values={k:np.stack([vectors[uid][k] for uid in ids]) for k in VIEWS};counts=np.array([frame_counts[uid] for uid in ids])
        if not np.array_equal(values['trajectory2'],baseline):raise ValueError('Baseline replacement failed')
        path=FOLDER/f'{cohort}-features.npz';engine.save_npz(path,ids=np.array(ids),frame_counts=counts,**values);outputs[str(path)]=engine.sha(path)
        summaries[cohort]={'targets':len(ids),'recordings':len(groups),'parent_windows':windows,'available':len(ids),
            'maximum_baseline_difference':max(differences),'observed_vowel_frame_counts':dict(sorted(Counter(counts.tolist()).items()))}
        print('TEMPORAL COHORT COMPLETE',cohort,len(ids),'targets',flush=True)
    checked();save_json(output,{'complete':True,'plan_sha256':plan_sha,'model':model.identity,'layer':plan['layer'],
        'outputs':outputs,'cache_sources':sources,'cohorts':summaries,'elapsed_seconds':time.monotonic()-started,'reference_text_input':False})
    print('CHINESE TEMPORAL EXTRACTION COMPLETE',flush=True)


if __name__=='__main__':main()
