"""Prospective synthetic no-speech checks, never used to tune nasal thresholds."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from phonetic_xeus import FOLDER, sha256
from xeus_nasal_evidence import target_evidence

ROOT = FOLDER / 'nonspeech'
KINDS = ('silence', 'white_noise', 'pink_noise', 'tone440', 'chirp', 'clicks')


def synthetic(kind, duration, seed):
    samples = int(duration*16000); rng = np.random.default_rng(seed)
    times = np.arange(samples)/16000
    if kind == 'silence':
        return np.zeros(samples, dtype=np.float32)
    if kind == 'white_noise':
        values = rng.standard_normal(samples)
    elif kind == 'pink_noise':
        spectrum = np.fft.rfft(rng.standard_normal(samples))
        spectrum[0] = 0
        spectrum[1:] /= np.sqrt(np.arange(1, len(spectrum)))
        values = np.fft.irfft(spectrum, n=samples)
    elif kind == 'tone440':
        values = np.sin(2*np.pi*440*times)
    elif kind == 'chirp':
        values = np.sin(2*np.pi*(100*times+0.5*(3000-100)/duration*times**2))
    elif kind == 'clicks':
        values = np.zeros(samples); values[::3200] = 1
    else:
        raise ValueError('Unknown synthetic signal')
    values = values * .03 / np.sqrt(np.mean(values**2))
    return np.clip(values, -.8, .8).astype(np.float32)


def prepare():
    if ROOT.exists():raise ValueError('No-speech plan exists')
    ROOT.mkdir()
    sources=[Path(__file__),Path('scripts/xeus_nasal_evidence.py'),Path('scripts/phonetic_xeus.py'),FOLDER/'plan.json']
    signals=[]
    for kind in KINDS:
        for duration in (.8,2.):
            seed=20261027; samples=synthetic(kind,duration,seed)
            signals.append({'kind':kind,'duration':duration,'seed':seed,
                            'audio_sha256':hashlib.sha256(samples.tobytes()).hexdigest()})
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):sha256(p) for p in sources},
          'signals':signals,'used_for_calibration':False,'expectation':'No nasal correctness or correction claim for either requested category.',
          'limitations':'Synthetic no-speech checks only, not real rooms/devices or speech-in-noise robustness.'}
    (ROOT/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');(ROOT/'plan.json').chmod(0o600)


def checked():
    plan=json.loads((ROOT/'plan.json').read_text())
    if any(sha256(Path(p))!=v for p,v in plan['sources'].items()):raise ValueError('No-speech plan changed')
    return plan


def infer():
    from phonetic_xeus import XeusModel
    plan=checked();model=XeusModel();rows=[]
    if (ROOT/'predictions.json').exists():raise ValueError('No-speech predictions frozen')
    policies=json.loads((FOLDER/'plan.json').read_text())['policies']
    for record in plan['signals']:
        samples=synthetic(record['kind'],record['duration'],record['seed'])
        if hashlib.sha256(samples.tobytes()).hexdigest()!=record['audio_sha256']:raise ValueError('Synthetic input changed')
        result=model.infer(samples)
        centers=(np.arange(len(result['logits']))*model.stride+model.field/2)/16000
        bounds={'syllable':[0.,record['duration']],'vowel':[0.,record['duration']]}
        for policy in policies:
            scores,reason=target_evidence(result['logits'],model.vocab,centers,bounds,**policy)
            rows.append({**record,'policy':policy,'scores':scores.tolist(),'reason':reason,'cache_key':result['key']})
    (ROOT/'predictions.json').write_text(json.dumps({'complete':True,'plan_sha256':sha256(ROOT/'plan.json'),'rows':rows},indent=2)+'\n')
    (ROOT/'predictions.json').chmod(0o600)
    print('NO-SPEECH INFERENCE COMPLETE',len(plan['signals']),flush=True)


def evaluate():
    from probe_phonetic_xeus import apply
    checked(); selection=json.loads((FOLDER/'selection.json').read_text())['selected']
    inference=json.loads((ROOT/'predictions.json').read_text())
    if inference.get('complete') is not True or inference['plan_sha256']!=sha256(ROOT/'plan.json'):raise ValueError('Stale no-speech predictions')
    if (ROOT/'evaluation.json').exists():raise ValueError('No-speech evaluation frozen')
    observed=[]
    for row in inference['rows']:
        if row['policy']!=selection['policy']:continue
        for expected in ('front','back'):
            target={'id':f"{row['kind']}-{row['duration']}-{expected}",'speaker':'synthetic',
                    'condition':'no_speech','split':'stress','actual_label':'other','expected_label':expected,
                    'api_state':'not_flagged'}
            # Do not credit an API veto: this tests the acoustic decision alone.
            observed.extend(apply([target],np.array([row['scores']]),selection))
    report={'cases':len(observed),'false_matches':sum(r['candidate_nasal_match'] for r in observed),
            'false_corrections':sum(r['candidate_nasal_change'] for r in observed),
            'abstentions':sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in observed),
            'observations':observed,'selection_sha256':sha256(FOLDER/'selection.json'),
            'plan_sha256':sha256(ROOT/'plan.json'),'synthetic_only':True,'used_for_calibration':False}
    (ROOT/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n');(ROOT/'evaluation.json').chmod(0o600)
    print(json.dumps({k:v for k,v in report.items() if k!='observations'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','infer','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'infer':infer,'evaluate':evaluate}[args.mode]()
