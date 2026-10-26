"""Freeze Xeus acoustic features, with replay against the phone experiment."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from phonetic_xeus import FOLDER as PHONE, XeusModel, sha256
from nasal_acoustics import read_audio
from nasal_feature_probe import pool_regions
from zipa_context import context_interval

FOLDER=PHONE.parent/'xeus-features-v2'


def main():
    import torch
    plan=json.loads((FOLDER/'plan.json').read_text())
    if any(sha256(Path(p))!=v for p,v in plan['sources'].items()):raise ValueError('Frozen feature sources changed')
    model=XeusModel(); groups=defaultdict(list); datasets={}
    for cohort in ('existing','griffith'):
        datasets[cohort]=json.loads((FOLDER/f'{cohort}-dataset.json').read_text())
        for row in datasets[cohort]['rows']:groups[row['audio']].append((cohort,row))
    cache=FOLDER/'features';cache.mkdir(exist_ok=True)
    records={'existing':[],'griffith':[]};excluded={'existing':[],'griffith':[]}
    replay_count=0;maximum_difference=0.
    for audio,targets in groups.items():
        if any(sha256(Path(audio))!=row['audio_sha256'] for _,row in targets):raise ValueError('Audio changed')
        samples=read_audio(Path(audio),max_seconds=180);windows=defaultdict(list)
        for cohort,row in targets:
            try:interval=context_interval(len(samples),row['bounds']['syllable'])
            except ValueError as error:
                excluded[cohort].append({'id':row['id'],'reason':str(error)});continue
            windows[interval].append((cohort,row))
        for (a,b),window_targets in windows.items():
            waveform=samples[a:b]
            acoustic_key=hashlib.sha256(json.dumps(model.identity,sort_keys=True).encode()+waveform.tobytes()).hexdigest()
            identity={'acoustic_key':acoustic_key,'layers':plan['layers'],
                      'targets':[(c,r['id'],r['bounds']) for c,r in window_targets]}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            path=cache/(key+'.npz'); meta_path=cache/(key+'.json')
            if not path.exists() or not meta_path.exists():
                speech=torch.from_numpy(waveform.copy()).unsqueeze(0).to('mps')
                lengths=torch.tensor([len(waveform)],dtype=torch.long,device='mps')
                model.conditioning_calls=0;model.conditioning_norms=[]
                with torch.inference_mode():
                    encoded,output_lengths=model.model.encode(speech,lengths)
                    final,intermediate=encoded
                    if [i for i,_ in intermediate]!=[4,8,12] or model.conditioning_calls!=3:
                        raise RuntimeError('Intermediate conditioning path changed')
                    states={i:v[0].float().cpu().numpy() for i,v in intermediate if i in plan['layers']}
                    states[19]=final[0].float().cpu().numpy()
                    logits=model.model.ctc.ctc_lo(final)[0].float().cpu().numpy()
                expected=(len(waveform)-model.field)//model.stride+1
                if int(output_lengths[0])!=expected or not np.isfinite(logits).all():raise RuntimeError('Frame grid changed')
                baseline=PHONE/'cache'/(acoustic_key+'.npz'); difference=None
                if baseline.exists():
                    with np.load(baseline,allow_pickle=False) as previous:
                        difference=float(np.max(np.abs(logits-previous['logits'])))
                    if difference>1e-4:raise RuntimeError('Feature capture changed original logits')
                valid=[];values=[];rejected=[]
                for cohort,row in window_targets:
                    bounds={k:[t-a/16000 for t in interval] for k,interval in row['bounds'].items()}
                    try:
                        pooled=np.stack([pool_regions(states[layer],bounds,sample_count=b-a,
                            stride=model.stride,receptive_field=model.field) for layer in plan['layers']])
                    except ValueError as error:
                        rejected.append({'cohort':cohort,'id':row['id'],'reason':str(error)});continue
                    valid.append((cohort,row['id']));values.append(pooled)
                temporary=path.with_suffix('.tmp.npz')
                np.savez_compressed(temporary,features=np.stack(values) if values else np.empty((0,len(plan['layers']),4,1024)),
                                    ids=np.array([uid for _,uid in valid],dtype=str))
                temporary.chmod(0o600);temporary.replace(path)
                metadata={'identity':identity,'valid':valid,'excluded':rejected,'logit_replay_difference':difference}
                meta_path.write_text(json.dumps(metadata,indent=2)+'\n');meta_path.chmod(0o600)
                del encoded,final,intermediate,states,speech,logits
                torch.mps.empty_cache()
            metadata=json.loads(meta_path.read_text())
            if metadata['logit_replay_difference'] is not None:
                replay_count+=1;maximum_difference=max(maximum_difference,metadata['logit_replay_difference'])
            for index,(cohort,uid) in enumerate(metadata['valid']):records[cohort].append({'id':uid,'cache':str(path),'index':index})
            for row in metadata['excluded']:excluded[row['cohort']].append(row)
        print('FEATURES',sum(len(v) for v in records.values()),'targets cached',flush=True)
    for cohort in records:
        report={'complete':True,'rows':records[cohort],'excluded':excluded[cohort],
                'dataset_sha256':sha256(FOLDER/f'{cohort}-dataset.json'),'plan_sha256':sha256(FOLDER/'plan.json'),
                'model':model.identity,'layers':plan['layers'],'replayed_windows':replay_count,
                'maximum_replayed_logit_difference':maximum_difference}
        p=FOLDER/f'{cohort}-feature-index.json';p.write_text(json.dumps(report,indent=2)+'\n');p.chmod(0o600)
    print('XEUS FEATURE EXTRACTION COMPLETE',replay_count,maximum_difference,flush=True)


if __name__=='__main__':main()
