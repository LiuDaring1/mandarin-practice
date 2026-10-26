"""Run the frozen Xeus context experiment without supplying expected text."""
import json
from pathlib import Path

import numpy as np

from phonetic_xeus import FOLDER, XeusModel, sha256
from nasal_acoustics import read_audio
from xeus_nasal_evidence import target_evidence
from zipa_context import context_interval


def main():
    plan=json.loads((FOLDER/'plan.json').read_text())
    if any(sha256(Path(p))!=value for p,value in plan['sources'].items()):
        raise ValueError('Frozen Xeus sources changed')
    output=FOLDER/'predictions.json'
    if output.exists():raise ValueError('Xeus inference report frozen')
    model=XeusModel(); cohorts={}; references=[]; audio_cache={}; window_cache={}
    controls=json.loads((FOLDER.parent/'zipa-v1/plan.json').read_text())['reference_inputs']
    for control in controls:
        path=Path(control['audio'])
        if sha256(path)!=control['audio_sha256']:raise ValueError('Control changed')
        samples=read_audio(path); result=model.infer(samples)
        centers=(np.arange(len(result['logits']))*model.stride+model.field/2)/16000
        bounds={'syllable':[0.,len(samples)/16000],'vowel':[0.,len(samples)/16000]}
        scores,reason=target_evidence(result['logits'],model.vocab,centers,bounds,'syllable',0,'terminal')
        references.append({**control,'predicted':('front','back','other')[int(scores.argmax())],
                           'scores':scores.tolist(),'reason':reason,'cache_key':result['key']})
    for name in ('existing','griffith'):
        dataset=json.loads((FOLDER.parent/'zipa-v1'/f'{name}-dataset.json').read_text()); records=[]
        for index,row in enumerate(dataset['rows']):
            path=row['audio']
            if path not in audio_cache:
                if sha256(Path(path))!=row['audio_sha256']:raise ValueError('Audio changed')
                audio_cache[path]=read_audio(Path(path),max_seconds=180)
            try:
                a,b=context_interval(len(audio_cache[path]),row['bounds']['syllable'])
            except ValueError as error:
                records.extend({'id':row['id'],'policy':policy,'unavailable':True,'reason':str(error)} for policy in plan['policies'])
                continue
            key=(path,a,b)
            if key not in window_cache:window_cache[key]=model.infer(audio_cache[path][a:b])
            result=window_cache[key]
            centers=(np.arange(len(result['logits']))*model.stride+model.field/2+a)/16000
            for policy in plan['policies']:
                scores,reason=target_evidence(result['logits'],model.vocab,centers,row['bounds'],**policy)
                records.append({'id':row['id'],'policy':policy,'scores':scores.tolist(),'reason':reason,
                                'context_samples':[a,b],'cache_key':result['key']})
            if (index+1)%40==0:print(name,index+1,'targets complete',flush=True)
        cohorts[name]=records
    report={'complete':True,'plan_sha256':sha256(FOLDER/'plan.json'),'model':model.identity,
            'reference_controls':references,'cohorts':cohorts,'inference_windows':len(window_cache),
            'conditioning_calls_verified_on_every_new_window':True}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');output.chmod(0o600)
    print('XEUS INFERENCE COMPLETE',flush=True)


if __name__=='__main__':main()
