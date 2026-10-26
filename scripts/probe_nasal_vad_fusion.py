"""Repeat the frozen nine-head experiment with independent VAD evidence.

Uses a new private root and never rewrites the failed phonetic-gate experiment.
The fitting engine is reused verbatim; only the evidence source is changed.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

import numpy as np

import probe_nasal_fusion as engine
from nasal_feature_fusion import align_features,feature_source,gate_scores
from nasal_feature_probe import feature_view,predict_ridge
from silero_nasal_gate import FOLDER as VAD,SileroGate,sha,target_speech
from train_nasal_feature_probe import save_json

BASE=Path('data/derived/nasal-acoustic-validation')
PREVIOUS=BASE/'fusion-gating-v1'
FOLDER=BASE/'fusion-vad-v2'


@contextmanager
def fitting_root():
    """Reuse our fixed fitting engine with an explicit isolated experiment root."""
    previous=engine.FOLDER
    engine.FOLDER=FOLDER
    try:
        yield
    finally:
        engine.FOLDER=previous


def prepare():
    if FOLDER.exists():
        raise ValueError('VAD fusion plan already frozen')
    parity=json.loads((VAD/'parity.json').read_text())
    if any(r['maximum_difference']>1e-6 for r in parity['checks']):
        raise ValueError('VAD wrapper parity not established')
    prior=json.loads((PREVIOUS/'plan.json').read_text())
    files=['existing-dataset.json','existing-features.npz','griffith-dataset.json','griffith-features.npz',
           'noise/dataset.json','noise/feature-index.json','noise/xeus-features.npz']
    sources=[PREVIOUS/p for p in files]+[PREVIOUS/'evaluation.json',VAD/'source.json',VAD/'parity.json',
        Path(__file__),Path('scripts/silero_nasal_gate.py'),Path('scripts/probe_nasal_fusion.py'),
        Path('scripts/nasal_feature_fusion.py'),Path('scripts/nasal_feature_probe.py'),
        Path('scripts/probe_phonetic_xeus.py'),Path('scripts/nasal_directional_calibration.py')]
    plan={k:prior[k] for k in ('feature_sources','regularizations','calibration_mode','selection_splits','ranking')}
    plan.update(frozen_at_utc=datetime.now(timezone.utc).isoformat(),sources={str(p):sha(p) for p in sources},
        gate={'model':'Silero VAD','probability_cutoff':.5,'minimum_consecutive_chunks':2,'chunk_ms':32,'target_padding_ms':30},
        gate_uses_expected_label=False,noise_used_for_selection=False,model_training='ridge head only',
        speech_evaluation_previously_explored=True,backgrounds_used_in_prior_method=True,production_enablement=False)
    FOLDER.mkdir();(FOLDER/'noise').mkdir()
    save_json(FOLDER/'plan.json',plan)
    for relative in files:
        shutil.copyfile(PREVIOUS/relative,FOLDER/relative);(FOLDER/relative).chmod(0o600)
    print('VAD PLAN FROZEN; unchanged features and candidate grid',flush=True)


def checked():
    with fitting_root():return engine.checked()


def infer():
    from nasal_acoustics import read_audio
    checked()
    if (FOLDER/'evidence.json').exists():
        raise ValueError('VAD evidence already frozen')
    model=SileroGate();groups=defaultdict(list)
    for cohort in ('existing','griffith','noise'):
        path=FOLDER/(f'{cohort}-dataset.json' if cohort!='noise' else 'noise/dataset.json')
        for row in json.loads(path.read_text())['rows']:
            if row['expected_label']!='other' or cohort=='noise':
                groups[row['audio']].append((cohort,row))
    cache=FOLDER/'vad-cache';cache.mkdir(exist_ok=True)
    evidence={c:{} for c in ('existing','griffith','noise')}
    for index,(audio,targets) in enumerate(groups.items()):
        audio_sha=sha(audio)
        if any(row['audio_sha256']!=audio_sha for _,row in targets):
            raise ValueError('VAD input recording changed')
        path=cache/(audio_sha+'.npz')
        if not path.exists():
            samples=read_audio(Path(audio),max_seconds=180)
            values=model.score(samples)
            np.savez_compressed(path,scores=values,sample_count=len(samples));path.chmod(0o600)
        with np.load(path,allow_pickle=False) as stored:
            for cohort,row in targets:
                evidence[cohort][row['id']]={'present':target_speech(stored['scores'],int(stored['sample_count']),row['bounds']),
                                           'reason':'fixed_speech_presence_rule','cache_key':audio_sha}
        if (index+1)%40==0:print('VAD',index+1,'recordings',flush=True)
    save_json(FOLDER/'evidence.json',{'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),
        'model':model.identity,'cohorts':evidence,'recordings':len(groups)})
    print('VAD COMPLETE',len(groups),'recordings',flush=True)


def fit():
    checked()
    with fitting_root():engine.fit()


def evaluate():
    from probe_phonetic_xeus import apply,cohort_summary
    checked()
    if (FOLDER/'evaluation.json').exists():
        raise ValueError('VAD fusion evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text());chosen=selection['selected']
    if (selection['plan_sha256']!=sha(FOLDER/'plan.json') or selection['weights_sha256']!=sha(FOLDER/'ridge-model.npz')
        or selection['evidence_sha256']!=sha(FOLDER/'evidence.json')):
        raise ValueError('Frozen VAD fusion model or evidence changed')
    with np.load(FOLDER/'ridge-model.npz',allow_pickle=False) as stored:model={k:stored[k] for k in stored.files}
    comparison={};gate_retention={}
    with fitting_root():
        for cohort in ('existing','griffith'):
            rows,x,dataset=engine.load(cohort);scores=predict_ridge(model,feature_source(x,chosen['feature_source']))
            acceptance=engine.present(rows,cohort)
            selected={k:[r for r in dataset[k] if r['expected_label'] in ('front','back')] for k in ('rows','excluded')}
            comparison[cohort]={}
            for state,sc in [('gated',gate_scores(scores,acceptance)),('ungated',scores)]:
                obs=apply(rows,sc,chosen)
                comparison[cohort][state]=cohort_summary(selected,[r for r in obs if r['expected'] in ('front','back')])
            heldout=[i for i,r in enumerate(rows) if r['expected_label'] in ('front','back') and r['split'] not in ('train','dev')]
            gate_retention[cohort]={'nasal_targets':len(heldout),'retained':int(acceptance[heldout].sum()),
                'errors_retained':int(sum(acceptance[i] and rows[i]['expected_label']!=rows[i]['actual_label'] for i in heldout)),
                'normal_retained':int(sum(acceptance[i] and rows[i]['expected_label']==rows[i]['actual_label'] for i in heldout))}
            print(cohort,json.dumps(comparison[cohort]['gated']['evaluation_only']),flush=True)
        rows,left,_=engine.old_features(FOLDER/'noise')
    with np.load(FOLDER/'noise/xeus-features.npz',allow_pickle=False) as stored:
        lookup={str(uid):i for i,uid in enumerate(stored['ids'])}
        right=feature_view(np.stack([stored['features'][lookup[r['id']]] for r in rows])[:,None],0,'trajectory')
    scores=predict_ridge(model,feature_source(align_features(rows,left,rows,right),chosen['feature_source']))
    evidence=json.loads((FOLDER/'evidence.json').read_text())['cohorts']['noise'];noise=[]
    for row,score in zip(rows,scores):
        for expected in ('front','back'):
            target={**row,'id':row['id']+'-'+expected,'expected_label':expected}
            for state in ('gated','ungated'):
                values=gate_scores(score[None],np.array([evidence[row['id']]['present']])) if state=='gated' else score[None]
                noise.append({**apply([target],values,chosen)[0],'gate':state,'noise_source':row['noise_source'],'category':row['category']})
    summary={kind:{state:{'cases':len(part),'false_matches':sum(r['candidate_nasal_match'] for r in part),
        'false_corrections':sum(r['candidate_nasal_change'] for r in part),
        'abstentions':sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in part)}
        for state in ('gated','ungated') for part in [[r for r in noise if r['noise_source']==kind and r['gate']==state]]}
        for kind in ('synthetic','recorded_environment')}
    report={'complete':True,'selection_sha256':sha(FOLDER/'selection.json'),'selected':chosen,'comparison':comparison,
        'gate_retention':gate_retention,'noise':summary,'noise_predictions':noise,
        'limits':['Speech presence does not verify target identity or n/ng correctness.',
                  'Existing speech and background samples were explored before this method; not final blind validation.',
                  'No microphone, speech-in-noise, omission or repetition validation.',
                  'Ungated comparison keeps the same head and margins; no separate optimization.']}
    save_json(FOLDER/'evaluation.json',report)
    print('RETENTION',json.dumps(gate_retention),'NOISE',json.dumps(summary),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','infer','fit','evaluate']);args=parser.parse_args()
    {'prepare':prepare,'infer':infer,'fit':fit,'evaluate':evaluate}[args.mode]()
