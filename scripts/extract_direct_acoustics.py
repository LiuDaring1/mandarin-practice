"""Extract direct acoustic features with resumable, identity-checked caches."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from nasal_acoustics import read_audio
from nasal_direct_acoustics import spectral_frames,formant_frames,pool_spectrum,pool_formants
from probe_direct_acoustics import FOLDER,checked,load_base,engine
from train_nasal_feature_probe import save_json
from zipa_context import context_interval


def runtime():
    import parselmouth
    return {'parselmouth_version':parselmouth.__version__,'praat_version':parselmouth.PRAAT_VERSION,
        'extension_sha256':engine.sha(parselmouth.__file__)}


def main():
    plan=checked();report=FOLDER/'feature-report.json'
    if report.exists(): raise ValueError('Direct features frozen')
    if runtime()!=plan['runtime']: raise ValueError('Formant runtime changed')
    cache=FOLDER/'features';cache.mkdir(exist_ok=True);sources={};outputs={};cohorts={};started=time.monotonic()
    for cohort in plan['cohorts']:
        rows,_,_,_=load_base(cohort);groups=defaultdict(list)
        for row in rows:groups[row['audio']].append(row)
        features={};flags={};failures=[];windows=0
        for audio,targets in groups.items():
            digest=engine.sha(audio)
            if any(digest!=r['audio_sha256'] for r in targets): raise ValueError('Direct audio changed')
            samples=read_audio(Path(audio),max_seconds=180);grouped=defaultdict(list)
            for row in targets:grouped[context_interval(len(samples),row['bounds']['syllable'])].append(row)
            for (a,b),members in grouped.items():
                identity={'plan_sha256':engine.sha(FOLDER/'plan.json'),'audio_sha256':digest,
                    'window':[a,b],'targets':[(r['id'],r['bounds']) for r in members]}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();path=cache/(key+'.npz');meta=cache/(key+'.json')
                if not(path.exists() and meta.exists()):
                    times,raw,cmn=spectral_frames(samples[a:b]);contours=formant_frames(samples[a:b]);values=[];available=[];bad=[]
                    for row in members:
                        try:
                            v=[pool_spectrum(times,raw,row['bounds'],a),pool_spectrum(times,cmn,row['bounds'],a),pool_formants(contours,row['bounds'],a)]
                            if [len(x) for x in v]!=[108,108,54] or not np.isfinite(v[:2]).all() or np.isinf(v[2]).any(): raise ValueError('Invalid pooled direct features')
                            available.append(True)
                        except ValueError as error:
                            v=[np.zeros(108),np.zeros(108),np.full(54,np.nan)];available.append(False)
                            bad.append({'id':row['id'],'reason':str(error)})
                        values.append(v)
                    temporary=path.with_suffix('.tmp.npz')
                    engine.save_npz(temporary,ids=np.array([r['id'] for r in members]),available=np.array(available,dtype=bool),
                        mfcc=np.stack([v[0] for v in values]),cmn=np.stack([v[1] for v in values]),formants=np.stack([v[2] for v in values]))
                    temporary.replace(path);save_json(meta,{'identity':identity,'features_sha256':engine.sha(path),'failures':bad})
                metadata=json.loads(meta.read_text())
                if metadata['identity']!=json.loads(json.dumps(identity)) or metadata['features_sha256']!=engine.sha(path): raise ValueError('Direct cache changed')
                with np.load(path,allow_pickle=False) as stored:
                    if stored['ids'].tolist()!=[r['id'] for r in members]: raise ValueError('Direct cache identity mismatch')
                    for i,uid in enumerate(stored['ids'].tolist()):
                        if uid in features: raise ValueError('Duplicate direct feature')
                        features[uid]=[stored[k][i] for k in ('mfcc','cmn','formants')];flags[uid]=stored['available'][i]
                failures.extend(metadata['failures']);sources[str(path)]=engine.sha(path);sources[str(meta)]=engine.sha(meta);windows+=1
            print('DIRECT FEATURES',cohort,len(features),'/',len(rows),'targets',flush=True)
        ids=[r['id'] for r in rows]
        if set(features)!=set(ids): raise ValueError('Direct extraction lost targets')
        values={k:np.stack([features[uid][i] for uid in ids]) for i,k in enumerate(('mfcc','cmn','formants'))}
        path=FOLDER/f'{cohort}-features.npz';engine.save_npz(path,ids=np.array(ids),available=np.array([flags[uid] for uid in ids],dtype=bool),**values)
        outputs[str(path)]=engine.sha(path)
        cohorts[cohort]={'targets':len(ids),'recordings':len(groups),'parent_windows':windows,'available':sum(bool(flags[uid]) for uid in ids),
            'targets_with_missing_formant_values':int(np.isnan(values['formants']).any(axis=1).sum()),
            'missing_formant_coordinates':int(np.isnan(values['formants']).sum()),'failures':failures}
        print('DIRECT COHORT COMPLETE',cohort,json.dumps(cohorts[cohort]),flush=True)
    checked();save_json(report,{'complete':True,'plan_sha256':engine.sha(FOLDER/'plan.json'),'runtime':runtime(),
        'outputs':outputs,'cohorts':cohorts,'cache_sources':sources,'elapsed_seconds':time.monotonic()-started,
        'reference_text_feature':False,'source_identity_feature':False})
    print('DIRECT EXTRACTION COMPLETE',flush=True)


if __name__=='__main__':main()
