"""Extract encoder-only context variants and replay every full-context target."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from nasal_acoustics import read_audio
from phonetic_xeus import XeusModel
from probe_xeus_encoder_context import FOLDER,checked,load_base,engine
from train_nasal_feature_probe import save_json
from xeus_encoder_context import preprocess,encode_frames,context_frames,pool_trajectory
from zipa_context import context_interval


def main():
    import torch
    plan=checked();report_path=FOLDER/'feature-report.json'
    if report_path.exists(): raise ValueError('Encoder context features frozen')
    model=XeusModel();cache=FOLDER/'features';cache.mkdir(exist_ok=True)
    sources={};outputs={};summaries={};started=time.monotonic()
    for cohort in plan['cohorts']:
        rows,baseline,_,_=load_base(cohort)
        originals={r['id']:baseline[i] for i,r in enumerate(rows)}
        groups=defaultdict(list)
        for row in rows:groups[row['audio']].append(row)
        vectors={};availability={};failures=[];differences=[];windows=0
        for audio,targets in groups.items():
            if any(engine.sha(audio)!=r['audio_sha256'] for r in targets): raise ValueError('Context audio changed')
            samples=read_audio(Path(audio),max_seconds=180);grouped=defaultdict(list)
            for row in targets: grouped[context_interval(len(samples),row['bounds']['syllable'])].append(row)
            for (a,b),members in grouped.items():
                identity={'plan_sha256':engine.sha(FOLDER/'plan.json'),'model':model.identity,'audio_sha256':engine.sha(audio),
                    'window':[a,b],'targets':[(r['id'],r['bounds']) for r in members]}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                path=cache/(key+'.npz');meta=cache/(key+'.json')
                if not(path.exists() and meta.exists()):
                    features=preprocess(model,samples[a:b]);full=encode_frames(model,features)
                    values=[];available=[];bad=[];delta=[];crop_sizes=[]
                    for row in members:
                        uid=row['id'];bounds=row['bounds']
                        replay=pool_trajectory(full,bounds,a,stride=model.stride,field=model.field)
                        difference=float(np.max(np.abs(replay-originals[uid])))
                        if difference>plan['full_feature_replay_tolerance']:
                            raise ValueError(f'Full context replay changed for {uid}: {difference}')
                        delta.append(difference)
                        local_values=[originals[uid].copy()];local_available=[True];sizes=[len(full)]
                        for margin in plan['margins_ms'][1:]:
                            try:
                                start,stop=context_frames(bounds,(a,b),len(full),margin,model.stride,model.field)
                                if start==0 and stop==len(full): value=originals[uid].copy()
                                else:
                                    local=encode_frames(model,features[:,start:stop])
                                    value=pool_trajectory(local,bounds,a,start,model.stride,model.field)
                                    del local
                                local_values.append(value);local_available.append(True);sizes.append(stop-start)
                            except ValueError as error:
                                local_values.append(np.zeros(2048,dtype=np.float32));local_available.append(False);sizes.append(0)
                                bad.append({'id':uid,'margin_ms':margin,'reason':str(error)})
                        values.append(np.stack(local_values));available.append(local_available);crop_sizes.append(sizes)
                    temporary=path.with_suffix('.tmp.npz')
                    engine.save_npz(temporary,ids=np.array([r['id'] for r in members]),features=np.stack(values),
                        available=np.array(available,dtype=bool),frame_counts=np.array(crop_sizes))
                    temporary.replace(path)
                    save_json(meta,{'identity':identity,'features_sha256':engine.sha(path),'failures':bad,
                        'full_feature_maximum_difference':max(delta),'full_features_replayed':len(delta)})
                    del features,full
                    torch.mps.empty_cache()
                metadata=json.loads(meta.read_text())
                if metadata['identity']!=json.loads(json.dumps(identity)) or metadata['features_sha256']!=engine.sha(path):
                    raise ValueError('Context cache changed')
                with np.load(path,allow_pickle=False) as stored:
                    if stored['ids'].tolist()!=[r['id'] for r in members]: raise ValueError('Context cache membership changed')
                    for uid,value,valid in zip(stored['ids'].tolist(),stored['features'],stored['available']):
                        if uid in vectors: raise ValueError('Duplicate context feature')
                        vectors[uid]=value;availability[uid]=valid
                failures.extend(metadata['failures']);differences.append(metadata['full_feature_maximum_difference'])
                sources[str(path)]=engine.sha(path);sources[str(meta)]=engine.sha(meta);windows+=1
            print('CONTEXT FEATURES',cohort,len(vectors),'/',len(rows),'targets;',windows,'parent windows',flush=True)
        ids=[r['id'] for r in rows]
        if set(vectors)!=set(ids): raise ValueError('Context extraction lost targets')
        values=np.stack([vectors[uid] for uid in ids]);available=np.stack([availability[uid] for uid in ids])
        if not np.array_equal(values[:,0],baseline): raise ValueError('Full baseline features changed')
        path=FOLDER/f'{cohort}-features.npz'
        engine.save_npz(path,ids=np.array(ids),features=values,available=available)
        outputs[str(path)]=engine.sha(path)
        summaries[cohort]={'targets':len(ids),'recordings':len(groups),'parent_windows':windows,
            'available_by_condition':available.sum(axis=0).tolist(),'failures':failures,
            'full_features_replayed':len(ids),'maximum_full_feature_difference':max(differences)}
        print('CONTEXT COHORT COMPLETE',cohort,json.dumps(summaries[cohort]),flush=True)
    checked()
    save_json(report_path,{'complete':True,'plan_sha256':engine.sha(FOLDER/'plan.json'),'model':model.identity,
        'outputs':outputs,'cohorts':summaries,'cache_sources':sources,'elapsed_seconds':time.monotonic()-started,
        'reference_text_input':False,'parent_frontend_unchanged':True})
    print('CONTEXT EXTRACTION COMPLETE',flush=True)


if __name__=='__main__':
    main()
