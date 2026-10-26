"""Prospective fusion/gating experiment with preserved speaker partitions.

Two existing encoders are fixed. Only train/dev choose one of nine small heads.
The evidence gate is fixed before inference, independent of the expected nasal.
Real environmental sounds are evaluation-only, never threshold calibration.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import wave

import numpy as np

from eduhk_word_inventory import current_partitions
from nasal_feature_fusion import align_features, feature_source, gate_scores
from nasal_feature_probe import LABELS, LAYERS, assert_speaker_partition, feature_view, fit_ridge, predict_ridge
from train_nasal_feature_probe import load_features, save_json
from xeus_stress import synthetic

BASE = Path('data/derived/nasal-acoustic-validation')
FOLDER = BASE/'fusion-gating-v1'
RECOVERY = BASE/'eduhk-word-recovery-v2/probe'
GATE = {'region':'syllable', 'extension_ms':80, 'method':'terminal'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_npz(path, **values):
    np.savez_compressed(path, **values)
    path.chmod(0o600)


def old_features(folder):
    features, rows, dataset, index = load_features(folder)
    if index['context_ms'] != 150:
        raise ValueError('Baseline must use the frozen 150 ms context')
    return rows, feature_view(features, LAYERS.index(12), 'trajectory'), dataset


def xeus_features(cohort):
    from fit_xeus_features import load
    rows, features, dataset = load(cohort)
    return rows, feature_view(features, 2, 'trajectory'), dataset


def prepare():
    from fit_nasal_local_context import selected_rows
    if FOLDER.exists():
        raise ValueError('Fusion plan is frozen')
    backgrounds = json.loads((BASE/'background-validation-v1/manifest.json').read_text())
    if backgrounds.get('complete') is not True:
        raise ValueError('Background collection incomplete')
    source_files = [Path(__file__)] + [Path('scripts')/name for name in [
        'nasal_feature_fusion.py','nasal_feature_probe.py','nasal_directional_calibration.py',
        'probe_phonetic_xeus.py','xeus_nasal_evidence.py','phonetic_xeus.py',
        'extract_nasal_features.py','fit_xeus_features.py','fit_nasal_local_context.py',
        'eduhk_word_inventory.py','xeus_stress.py','collect_nasal_backgrounds.py']]
    source_files += [BASE/path for path in [
        'context-training-v4/dataset.json','local-context-training-v8/local150/feature-index.json',
        'context-ablation-v7/api_local150/feature-index.json','xeus-features-v2/selection.json',
        'xeus-features-v2/existing-feature-index.json','xeus-features-v2/griffith-feature-index.json',
        'xeus-v1/predictions.json','xeus-v1/nonspeech/plan.json',
        'background-validation-v1/manifest.json','background-validation-v1/plan.json',
        'eduhk-word-recovery-v2/probe/dataset.json','eduhk-word-recovery-v2/probe/feature-index.json',
        'eduhk-word-recovery-v2/probe/xeus-feature-index.json','eduhk-word-recovery-v2/probe/xeus-features.npz']]
    plan = {'frozen_at_utc':datetime.now(timezone.utc).isoformat(), 'sources':{str(p):sha(p) for p in source_files},
        'feature_sources':['local_phoneme','xeus','concatenated'], 'regularizations':[.01,.1,1.],
        'calibration_mode':'directional', 'gate':GATE, 'gate_uses_expected_label':False,
        'selection_splits':['train','dev'], 'noise_used_for_selection':False,
        'ranking':['dev correct error directions','dev correct normal matches','stronger regularization','simpler feature source'],
        'speech_evaluation_previously_explored':True, 'first_inference_on_environmental_backgrounds':True,
        'production_enablement':False}
    FOLDER.mkdir()
    save_json(FOLDER/'plan.json',plan)
    raw = json.loads((BASE/'context-training-v4/dataset.json').read_text())
    splits, discrepancies = current_partitions(raw)
    for cohort, path in [('existing',BASE/'local-context-training-v8/local150'),
                         ('griffith',BASE/'context-ablation-v7/api_local150')]:
        left_rows,left,dataset=old_features(path)
        right_rows,right,xdataset=xeus_features(cohort)
        paired=align_features(left_rows,left,right_rows,right)
        selected=selected_rows(dataset) if cohort=='existing' else dataset['rows']+dataset['excluded']
        available_ids={r['id'] for r in left_rows}
        if cohort=='existing':
            selected=[{**r,'split':splits[r['speaker']]} for r in selected]
            # Append recovered examples without reassigning any speaker.
            rr,rf,rd=old_features(RECOVERY)
            with np.load(RECOVERY/'xeus-features.npz',allow_pickle=False) as data:
                lookup={str(uid):i for i,uid in enumerate(data['ids'])}
                xr=feature_view(np.stack([data['features'][lookup[r['id']]] for r in rr])[:,None],0,'trajectory')
            extra=align_features(rr,rf,rr,xr)
            if available_ids & {r['id'] for r in rr}:
                raise ValueError('Recovered data overlap existing targets')
            paired=np.concatenate([paired,extra]);left_rows=left_rows+rr
            selected+=rd['rows']+rd['excluded']
        if len({r['id'] for r in selected})!=len(selected):
            raise ValueError('Duplicate selected target')
        by_id={r['id']:r for r in selected}
        rows=[by_id[r['id']] for r in left_rows]
        assert_speaker_partition(selected)
        available_ids={r['id'] for r in rows}
        save_json(FOLDER/f'{cohort}-dataset.json',{'rows':rows,
            'excluded':[r for r in selected if r['id'] not in available_ids],
            'historical_split_discrepancies':discrepancies if cohort=='existing' else []})
        save_npz(FOLDER/f'{cohort}-features.npz',features=paired,ids=np.array([r['id'] for r in rows]))
    noise=FOLDER/'noise';noise.mkdir();(noise/'audio').mkdir()
    rows=[]
    for rec in backgrounds['rows']:
        with wave.open(rec['audio'],'rb') as w:duration=w.getnframes()/w.getframerate()
        rows.append({'id':'esc50-'+rec['filename'], 'speaker':'esc50:'+rec['src_file'],
                     'audio':rec['audio'],'audio_sha256':rec['audio_sha256'],'duration':duration,
                     'noise_source':'recorded_environment','category':rec['category']})
    for rec in json.loads((BASE/'xeus-v1/nonspeech/plan.json').read_text())['signals']:
        uid=f"synthetic-{rec['kind']}-{rec['duration']}"
        values=synthetic(rec['kind'],rec['duration'],rec['seed'])
        if hashlib.sha256(values.tobytes()).hexdigest()!=rec['audio_sha256']:
            raise ValueError('Original synthetic input changed')
        audio=noise/'audio'/(uid+'.wav')
        with wave.open(str(audio),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
            w.writeframes(np.clip(np.rint(values*32768),-32768,32767).astype('<i2').tobytes())
        audio.chmod(0o600)
        rows.append({'id':uid,'speaker':'synthetic','audio':str(audio),'audio_sha256':sha(audio),
                     'duration':rec['duration'],'noise_source':'synthetic','category':rec['kind'],
                     'original_float_sha256':rec['audio_sha256']})
    rows=[{**r,'split':'stress','condition':'nonspeech','expected_label':'other','actual_label':'other',
           'api_state':'not_flagged','bounds':{'syllable':[0.,r['duration']],'vowel':[0.,r['duration']]}} for r in rows]
    save_json(noise/'dataset.json',{'rows':rows,'excluded':[]})
    print('PLAN AND FEATURES FROZEN',len(rows),'noise recordings',flush=True)


def checked():
    plan=json.loads((FOLDER/'plan.json').read_text())
    amendment_path=FOLDER/'implementation-amendment.json'
    amendments=json.loads(amendment_path.read_text())['repairs'] if amendment_path.exists() else {}
    for path,value in plan['sources'].items():
        if sha(path)!=value and amendments.get(path)!={'before':value,'after':sha(path)}:
            raise ValueError('Frozen fusion sources changed')
    return plan


def infer():
    import torch
    from nasal_acoustics import read_audio
    from nasal_feature_probe import pool_regions
    from phonetic_xeus import XeusModel
    from xeus_nasal_evidence import target_evidence
    checked()
    if (FOLDER/'evidence.json').exists():
        raise ValueError('Fusion acoustic evidence already frozen')
    source=json.loads((BASE/'xeus-v1/predictions.json').read_text())
    evidence={cohort:{r['id']:{'present':not r.get('unavailable') and int(np.argmax(r.get('scores',[0,0,1])))!=2,
                               'reason':r.get('reason','unavailable')}
                     for r in values if r['policy']==GATE} for cohort,values in source['cohorts'].items()}
    evidence['noise']={}
    noise=json.loads((FOLDER/'noise/dataset.json').read_text())['rows']
    recovered=json.loads((RECOVERY/'dataset.json').read_text())['rows']
    model=XeusModel();features=[];ids=[]
    cache=FOLDER/'inference-cache';cache.mkdir(exist_ok=True)
    for cohort,rows in [('existing',recovered),('noise',noise)]:
        for row in rows:
            if sha(row['audio'])!=row['audio_sha256']:
                raise ValueError('Input audio changed')
            key=hashlib.sha256(json.dumps({'audio':row['audio_sha256'],'bounds':row['bounds'],
                'model':model.identity,'gate':GATE},sort_keys=True).encode()).hexdigest()
            path=cache/(key+'.npz')
            if not path.exists():
                samples=read_audio(Path(row['audio']))
                speech=torch.from_numpy(samples.copy()).unsqueeze(0).to('mps')
                lengths=torch.tensor([len(samples)],dtype=torch.long,device='mps')
                model.conditioning_calls=0;model.conditioning_norms=[]
                with torch.inference_mode():
                    encoded,output_lengths=model.model.encode(speech,lengths)
                    final,intermediate=encoded
                    if model.conditioning_calls!=3 or [i for i,_ in intermediate]!=[4,8,12]:
                        raise RuntimeError('Xeus conditioning path changed')
                    hidden=final[0].float().cpu().numpy()
                    logits=model.model.ctc.ctc_lo(final)[0].float().cpu().numpy()
                if int(output_lengths[0])!=(len(samples)-model.field)//model.stride+1:
                    raise RuntimeError('Xeus frame geometry changed')
                centers=(np.arange(len(logits))*model.stride+model.field/2)/16000
                score,reason=target_evidence(logits,model.vocab,centers,row['bounds'],**GATE)
                pooled=pool_regions(hidden,row['bounds'],sample_count=len(samples),stride=model.stride,receptive_field=model.field)
                save_npz(path,features=pooled,scores=score,reason=np.array(reason))
                del encoded,final,intermediate,hidden,logits,speech
                torch.mps.empty_cache()
            with np.load(path,allow_pickle=False) as data:
                evidence[cohort][row['id']]={'present':int(data['scores'].argmax())!=2,'reason':str(data['reason'])}
                if cohort=='noise':
                    features.append(data['features']);ids.append(row['id'])
            print('GATE',cohort,len(evidence[cohort]),flush=True)
    save_npz(FOLDER/'noise/xeus-features.npz',features=np.stack(features),ids=np.array(ids))
    save_json(FOLDER/'evidence.json',{'complete':True,'plan_sha256':sha(FOLDER/'plan.json'),'cohorts':evidence})


def load(cohort):
    checked()
    dataset=json.loads((FOLDER/f'{cohort}-dataset.json').read_text())
    with np.load(FOLDER/f'{cohort}-features.npz',allow_pickle=False) as stored:
        if stored['ids'].tolist()!=[r['id'] for r in dataset['rows']]:
            raise ValueError('Prepared fusion feature identity mismatch')
        return dataset['rows'],stored['features'],dataset


def present(rows,cohort):
    report=json.loads((FOLDER/'evidence.json').read_text())
    if report.get('complete') is not True or report['plan_sha256']!=sha(FOLDER/'plan.json'):
        raise ValueError('Incomplete or stale evidence')
    lookup=report['cohorts'][cohort]
    return np.array([True if row['expected_label']=='other' else lookup[row['id']]['present'] for row in rows],dtype=bool)


def fit():
    from probe_nasal_boundaries import summarize_denominator
    from probe_phonetic_xeus import apply, calibrate
    plan=checked()
    if (FOLDER/'selection.json').exists() or (FOLDER/'ridge-model.npz').exists():
        raise ValueError('Fusion head already frozen')
    rows,x,dataset=load('existing')
    fitting=[i for i,r in enumerate(rows) if r['split'] in ('train','dev')]
    rows=[rows[i] for i in fitting];x=x[fitting];assert_speaker_partition(rows)
    train=np.array([r['split']=='train' for r in rows]);dev=~train
    dev_rows=[r for r in rows if r['split']=='dev'];accept=present(dev_rows,'existing')
    denominator=[r for r in dataset['rows']+dataset['excluded'] if r['split']=='dev']
    labels=np.array([LABELS.index(r['actual_label']) for r in rows]);candidates=[]
    for source in plan['feature_sources']:
        values=feature_source(x,source)
        for regularization in plan['regularizations']:
            model=fit_ridge(values[train],labels[train],regularization)
            scores=gate_scores(predict_ridge(model,values[dev]),accept)
            policy=calibrate(dev_rows,scores,plan['calibration_mode'])
            candidate={**policy,'feature_source':source,'regularization':regularization,
                       'development':summarize_denominator(denominator,apply(dev_rows,scores,policy))}
            candidates.append(candidate)
            print('FUSION CANDIDATE',source,regularization,candidate['development']['correct_error_directions'],candidate['development']['correct_nasal_matches'],flush=True)
    candidates.sort(key=lambda c:(-c['development']['correct_error_directions'],-c['development']['correct_nasal_matches'],
                                  -c['regularization'],plan['feature_sources'].index(c['feature_source'])))
    best=candidates[0];model=fit_ridge(feature_source(x,best['feature_source'])[train],labels[train],best['regularization'])
    save_npz(FOLDER/'ridge-model.npz',**model)
    save_json(FOLDER/'selection.json',{'selected':best,'ranking':candidates,'selected_at_utc':datetime.now(timezone.utc).isoformat(),
        'plan_sha256':sha(FOLDER/'plan.json'),'weights_sha256':sha(FOLDER/'ridge-model.npz'),
        'evidence_sha256':sha(FOLDER/'evidence.json'),
        'train_ids':[r['id'] for r in rows if r['split']=='train'],'dev_ids':[r['id'] for r in dev_rows],
        'evaluation_rows_used_for_selection':False,'noise_used_for_selection':False})
    print('FUSION SELECTED',best['feature_source'],best['regularization'],flush=True)


def evaluate():
    from probe_phonetic_xeus import apply, cohort_summary
    checked()
    if (FOLDER/'evaluation.json').exists():
        raise ValueError('Fusion evaluation frozen')
    selection=json.loads((FOLDER/'selection.json').read_text());chosen=selection['selected']
    if (selection['plan_sha256']!=sha(FOLDER/'plan.json') or selection['weights_sha256']!=sha(FOLDER/'ridge-model.npz')
        or selection['evidence_sha256']!=sha(FOLDER/'evidence.json')):
        raise ValueError('Frozen fusion model or evidence changed')
    with np.load(FOLDER/'ridge-model.npz',allow_pickle=False) as stored:model={k:stored[k] for k in stored.files}
    comparisons={}
    for cohort in ('existing','griffith'):
        rows,x,dataset=load(cohort);scores=predict_ridge(model,feature_source(x,chosen['feature_source']))
        selected={k:[r for r in dataset[k] if r['expected_label'] in ('front','back')] for k in ('rows','excluded')}
        comparisons[cohort]={}
        for state,sc in [('gated',gate_scores(scores,present(rows,cohort))),('ungated',scores)]:
            observed=apply(rows,sc,chosen)
            comparisons[cohort][state]=cohort_summary(selected,[r for r in observed if r['expected'] in ('front','back')])
        print(cohort,json.dumps(comparisons[cohort]['gated']['evaluation_only']),flush=True)
    rows,left,dataset=old_features(FOLDER/'noise')
    with np.load(FOLDER/'noise/xeus-features.npz',allow_pickle=False) as stored:
        order={str(uid):i for i,uid in enumerate(stored['ids'])}
        right=feature_view(np.stack([stored['features'][order[r['id']]] for r in rows])[:,None],0,'trajectory')
    paired=align_features(rows,left,rows,right);scores=predict_ridge(model,feature_source(paired,chosen['feature_source']))
    noise=[];evidence=json.loads((FOLDER/'evidence.json').read_text())['cohorts']['noise']
    for row,score in zip(rows,scores):
        for expected in ('front','back'):
            target={**row,'id':row['id']+'-'+expected,'expected_label':expected}
            for state in ('gated','ungated'):
                values=gate_scores(score[None],np.array([evidence[row['id']]['present']])) if state=='gated' else score[None]
                observed=apply([target],values,chosen)[0]
                noise.append({**observed,'gate':state,'noise_source':row['noise_source'],'category':row['category']})
    noise_summary={kind:{state:{'cases':len(part),
        'false_matches':sum(r['candidate_nasal_match'] for r in part),
        'false_corrections':sum(r['candidate_nasal_change'] for r in part),
        'abstentions':sum(not r['candidate_nasal_match'] and not r['candidate_nasal_change'] for r in part)}
        for state in ('gated','ungated')
        for part in [[r for r in noise if r['noise_source']==kind and r['gate']==state]]}
        for kind in ('synthetic','recorded_environment')}
    save_json(FOLDER/'evaluation.json',{'complete':True,'selection_sha256':sha(FOLDER/'selection.json'),
        'selected':chosen,'comparison':comparisons,'noise':noise_summary,'noise_predictions':noise,
        'speech_evaluation_previously_explored':True,'environmental_evaluation_used_for_selection':False,
        'limits':['Evidence presence is a phonetic proxy, not verified speech or correct target content.',
                  'No new independently labelled nasal speech corpus or actual device check.',
                  'Gate-only comparison keeps the same trained head and margins; ungated is not separately optimized.']})
    print('NOISE',json.dumps(noise_summary),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','infer','fit','evaluate'])
    args=parser.parse_args();{'prepare':prepare,'infer':infer,'fit':fit,'evaluate':evaluate}[args.mode]()
