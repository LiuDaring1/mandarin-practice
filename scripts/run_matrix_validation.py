"""Prospective CMNmatrix style controls, without invented actual-phone labels.

Reuse the frozen LATIC encoder/model runtime, but never its label summaries or
request budget. ASR is a content-identity check only; all selected targets remain
in the output denominator, including content, alignment and feature failures.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import wave

import numpy as np

import latic_validation_runtime as runtime
import run_latic_validation as pipeline
from audit_matrix_corpus import SENTENCE, checksum
from ise_probe import public_result
from nasal_validation_execution import MirroredIseProbe, align_target, durable_json, model_membership
from probe_eduhk_nasal import model_final
from probe_ise_pinyin_pairs import PROVIDER, cache_key, check_ledger
from probe_nasal_pairs import save_npz
from probe_same_tail_specificity import stage_budget
from resume_ise_pinyin_pairs import input_failure

SOURCE = runtime.BASE/'source-expansion-v1'
FOLDER = runtime.BASE/'matrix-control-v1'
MIRROR = Path.home()/'.cache/nasal-api-recovery/matrix-control-v1'


def new(name):
    if (FOLDER/name).exists() or (MIRROR/name).exists():
        raise ValueError('Stage already frozen: '+name)


def save(name, value):
    MIRROR.mkdir(parents=True, exist_ok=True); MIRROR.chmod(0o700)
    durable_json(MIRROR/name, value); durable_json(FOLDER/name, value)


def hanzi(text):
    return ''.join(c for c in text if '\u3400' <= c <= '\u9fff')


def selected(records):
    rows=[]
    for r in records:
        for t in r['targets']:
            if t.get('actual_label') is not None:
                raise ValueError('No actual-phone labels exist for this control')
            rows.append({**t, 'speaker':r['speaker'], 'style':r['style'], 'code':r['code']})
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate selected target')
    return rows


def output_summary(rows, observations):
    """Count outputs, not accuracy; retain missing observations as unknown."""
    index={r['id']:r for r in rows}; seen={}
    if len(index)!=len(rows):raise ValueError('Duplicate selected target')
    for o in observations:
        if o['id'] not in index or o['id'] in seen:raise ValueError('Invalid prediction identity')
        if o.get('actual') is not None:raise ValueError('Invented actual label')
        if o['expected'] != index[o['id']]['expected_label']:raise ValueError('Expected category changed')
        if o['candidate_nasal_change'] and o['candidate_nasal_match']:raise ValueError('Conflicting outputs')
        seen[o['id']]=o
    changes=sum(o['candidate_nasal_change'] for o in observations)
    matches=sum(o['candidate_nasal_match'] for o in observations)
    return {'selected':len(rows), 'scored':len(observations), 'unavailable':len(rows)-len(observations),
            'correction_outputs':changes, 'matching_outputs':matches,
            'unknown_outputs':len(rows)-changes-matches,
            'actual_phone_accuracy_measured':False}


def style_pairs(rows, observations):
    groups=defaultdict(dict); by_id={o['id']:o for o in observations}
    output_summary(rows, observations)
    for r in rows:
        key=(r['speaker'],r['code'],r['position'])
        if r['style'] in groups[key]:raise ValueError('Duplicate paired style')
        groups[key][r['style']]=r
    def state(row):
        o=by_id.get(row['id']) if row else None
        if o is None:return 'unavailable'
        return 'correction' if o['candidate_nasal_change'] else 'match' if o['candidate_nasal_match'] else 'unknown'
    transitions=Counter(); raw_changed=0; both_scored=0
    for pair in groups.values():
        a,b=(pair.get(s) for s in ('Plain','Lombard'))
        if a and b and a['expected_label']!=b['expected_label']:raise ValueError('Pair category differs')
        transitions[state(a)+' -> '+state(b)]+=1
        if a and b and a['id'] in by_id and b['id'] in by_id:
            both_scored+=1;raw_changed+=by_id[a['id']]['predicted']!=by_id[b['id']]['predicted']
    return {'selected_pairs':len(groups),'both_scored':both_scored,
            'raw_category_changed':raw_changed,'plain_to_lombard_outputs':dict(transitions)}


def checked():
    plan=runtime.read(FOLDER/'plan.json'); pipeline.checked()
    for p,d in plan['sources'].items():
        if runtime.sha(p)!=d:raise ValueError('Frozen source changed: '+p)
    if plan['models']!=runtime.checked()['models']:raise ValueError('Frozen models changed')
    for r in plan['records']:
        if runtime.sha(r['audio'])!=r['audio_sha256']:raise ValueError('Converted audio changed')
    if len(selected(plan['records']))!=154:raise ValueError('Target denominator changed')
    return plan


def prepare():
    new('plan.json'); parent=pipeline.checked(); source=runtime.read(SOURCE/'matrix-control-plan.json')
    for p,d in source['sources'].items():
        if runtime.sha(p)!=d:raise ValueError('Prospective source changed')
    if source['models']!=parent['models'] or source['selected_targets']!=154 or source['selected_recordings']!=44:
        raise ValueError('Prospective cohort/model mismatch')
    inv=runtime.read(SOURCE/'matrix-inventory.json'); archive=Path(inv['archive'])
    if checksum(archive)['sha256']!=source['archive_sha256']:raise ValueError('Archive changed')
    baseline={'ledger':runtime.read(PROVIDER/'requests.json'),
        'progress':{str(p):runtime.sha(p) for p in Path('data/derived/prototype').rglob('*') if p.is_file()}}
    new('baseline.json');save('baseline.json',baseline)
    audio_root=MIRROR/'audio';audio_root.mkdir(parents=True,exist_ok=True)
    records=[]
    for r in source['records']:
        if not SENTENCE.fullmatch(r['member']) or r['source_missing']:raise ValueError('Selected source unavailable')
        name=r['member'].replace('/','_');raw=audio_root/('original_'+name);out=audio_root/name
        if raw.exists() or out.exists():raise ValueError('Audio already exists; inspect interrupted preparation')
        raw.write_bytes(subprocess.run(['bsdtar','-xOf',str(archive),r['member']],check=True,capture_output=True).stdout)
        with wave.open(str(raw),'rb') as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(44100,1,2):raise ValueError('Unexpected original audio')
            duration=w.getnframes()/w.getframerate()
        subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(raw),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(out)],check=True)
        with wave.open(str(out),'rb') as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2) or abs(w.getnframes()/16000-duration)>.001:
                raise ValueError('Conversion format/duration changed')
        for p in (raw,out):p.chmod(0o600)
        targets=[{**t,'actual_label':None,'expected_final':model_final(t['expected_pinyin']),
                  'split':'external','cohort':'matrix','condition':'source_qc_'+r['style']} for t in r['targets']]
        records.append({**r,'targets':targets,'audio':str(out),'audio_sha256':runtime.sha(out),'core':'read_sentence',
                        'original':str(raw),'original_sha256':runtime.sha(raw),'duration_seconds':duration})
        print('MATRIX CONVERTED',len(records),'/ 44',flush=True)
    identity=runtime.read(SOURCE/'matrix-identity-plan.json')
    sources={**source['sources'],str(SOURCE/'matrix-control-plan.json'):runtime.sha(SOURCE/'matrix-control-plan.json'),
             str(pipeline.FOLDER/'plan.json'):runtime.sha(pipeline.FOLDER/'plan.json'),
             str(pipeline.FOLDER/'preflight.json'):runtime.sha(pipeline.FOLDER/'preflight.json'),
             __file__:runtime.sha(__file__)}
    for p in Path(identity['model']).iterdir():
        if p.is_file():sources[str(p)]=runtime.sha(p)
    save('plan.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),'sources':sources,'records':records,
        **{k:parent[k] for k in ('models','xeus_identity','hubert_identity','vad_identity','layers')},
        'asr':{k:identity[k] for k in ('model','parameters','reference_prompt')},
        'identity_policy':'Exact Hanzi after punctuation removal; mismatch retained as unavailable, no actual labels inferred.',
        'actual_phone_labels_available':False,'training_allowed':False,'threshold_tuning_allowed':False,
        'maximum_new_requests':44,'production_enabled':False})


def content():
    plan=checked();new('content.json')
    from mlx_audio.stt.utils import load_model
    model=load_model(plan['asr']['model']);rows=[]
    for i,r in enumerate(plan['records']):
        transcript=model.generate(r['audio'],**plan['asr']['parameters']).text
        rows.append({'member':r['member'],'audio_sha256':r['audio_sha256'],'transcription':transcript,
                     'identity_ok':hanzi(transcript)==hanzi(r['reference'])})
        save('content-progress.json',{'rows':rows})
        print('MATRIX CONTENT',i+1,'/ 44',rows[-1]['identity_ok'],flush=True)
    save('content.json',{'complete':True,'plan_sha256':runtime.sha(FOLDER/'plan.json'),'rows':rows,
        'identity_ok':sum(r['identity_ok'] for r in rows),'actual_phone_labels_established':False})


def imported():
    plan=checked();content=runtime.read(FOLDER/'content.json')
    if not content['complete'] or content['plan_sha256']!=runtime.sha(FOLDER/'plan.json'):raise ValueError('Content provenance changed')
    if [r['member'] for r in content['rows']]!=[r['member'] for r in plan['records']]:raise ValueError('Content membership changed')
    for r,c in zip(plan['records'],content['rows']):
        if r['audio_sha256']!=c['audio_sha256'] or c['identity_ok']!=(hanzi(c['transcription'])==hanzi(r['reference'])):
            raise ValueError('Content check changed')
    return plan,content


def budget():
    plan,content=imported();new('api-plan.json')
    requests=[{k:r[k] for k in ('audio','reference','core')}|{'key':cache_key(r['audio'],r['reference'],r['core'])}
              for r,c in zip(plan['records'],content['rows']) if c['identity_ok']]
    staged=stage_budget(requests,runtime.read(PROVIDER/'requests.json'),PROVIDER/'cache')
    if len(staged['new_request_keys'])>44:raise ValueError('Allowance exceeded')
    save('api-plan.json',{**staged,'plan_sha256':runtime.sha(FOLDER/'plan.json'),'content_sha256':runtime.sha(FOLDER/'content.json')})
    print('MATRIX BUDGET',len(staged['new_request_keys']),'new; cap',staged['maximum_total_attempts'],flush=True)


def api_checked():
    imported();plan=runtime.read(FOLDER/'api-plan.json')
    if plan['plan_sha256']!=runtime.sha(FOLDER/'plan.json') or plan['content_sha256']!=runtime.sha(FOLDER/'content.json'):
        raise ValueError('Request provenance changed')
    for p,d in plan['existing_caches'].items():
        if runtime.sha(p)!=d:raise ValueError('Existing cache changed')
    for r in plan['requests']:
        if cache_key(r['audio'],r['reference'],r['core'])!=r['key']:raise ValueError('Request identity changed')
    return plan


async def api(allow_paid=False):
    plan=api_checked();new('api-result.json')
    check_ledger(plan['ledger_prefix'],runtime.read(PROVIDER/'requests.json'),plan['new_request_keys'])
    probe=MirroredIseProbe(PROVIDER,mirror=MIRROR/'provider',allow_paid=allow_paid,max_calls=plan['maximum_total_attempts'])
    results={}
    for i,r in enumerate(plan['requests']):
        result=public_result(await probe.call(r['audio'],r['reference'],core=r['core']))
        results[r['key']]={'result':result,'cache_sha256':runtime.sha(PROVIDER/'cache'/(r['key']+'.json'))}
        save('api-progress.json',{'results':results})
        if result['status']!='ok' and not input_failure(result):raise RuntimeError('Unclassified failure; inspect, no automatic retry')
        print('MATRIX API',i+1,'/',len(plan['requests']),result['status'],flush=True)
    added=check_ledger(plan['ledger_prefix'],runtime.read(PROVIDER/'requests.json'),plan['new_request_keys'])
    save('api-result.json',{'complete':True,'api_plan_sha256':runtime.sha(FOLDER/'api-plan.json'),'results':results,
        'new_calls':added,'cumulative_reservations':len(runtime.read(PROVIDER/'requests.json'))})


def align():
    api_checked();plan,content=imported();new('dataset.json');response=runtime.read(FOLDER/'api-result.json')
    if not response['complete'] or response['api_plan_sha256']!=runtime.sha(FOLDER/'api-plan.json'):raise ValueError('Response provenance changed')
    for k,v in response['results'].items():
        if runtime.sha(PROVIDER/'cache'/(k+'.json'))!=v['cache_sha256']:raise ValueError('Response changed')
    rows=[];excluded=[]
    for r,c in zip(plan['records'],content['rows']):
        for target in selected([r]):
            row={**target,**{k:r[k] for k in ('audio','audio_sha256','reference','core')}}
            if not c['identity_ok']:excluded.append({**row,'reason':'content_identity_mismatch'});continue
            item,ok=align_target(row,response['results'][cache_key(r['audio'],r['reference'],r['core'])]['result'])
            (rows if ok else excluded).append(item)
    if len(rows)+len(excluded)!=154:raise ValueError('Alignment lost targets')
    save('dataset.json',{'rows':rows,'excluded':excluded,'api_result_sha256':runtime.sha(FOLDER/'api-result.json')})
    print('MATRIX ALIGNED',len(rows),'unavailable',len(excluded),flush=True)


def features():
    plan=checked();api_checked();data=runtime.read(FOLDER/'dataset.json');new('feature-report.json')
    if data['api_result_sha256']!=runtime.sha(FOLDER/'api-result.json'):raise ValueError('Alignment provenance changed')
    # extract_rows uses the pipeline plan solely for the cache identity. Keep the
    # original LATIC plan/code on disk unchanged; point this process at this plan.
    old=pipeline.FOLDER
    try:
        pipeline.FOLDER=FOLDER
        values,details=pipeline.extract_rows(data['rows'],MIRROR/'feature-cache',plan)
    finally:pipeline.FOLDER=old
    save_npz(FOLDER/'features.npz',**values);save_npz(MIRROR/'features.npz',**values)
    save('feature-report.json',{'complete':True,'plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'dataset_sha256':runtime.sha(FOLDER/'dataset.json'),'features_sha256':runtime.sha(FOLDER/'features.npz'),
        **details,'available_by_block':dict(zip(pipeline.BLOCKS,values['available'].sum(axis=0).tolist()))})


def evaluate():
    plan=checked();api_checked();new('evaluation.json');data=runtime.read(FOLDER/'dataset.json');report=runtime.read(FOLDER/'feature-report.json')
    if (not report['complete'] or report['plan_sha256']!=runtime.sha(FOLDER/'plan.json') or
        report['dataset_sha256']!=runtime.sha(FOLDER/'dataset.json') or report['features_sha256']!=runtime.sha(FOLDER/'features.npz')):
        raise ValueError('Feature provenance changed')
    for p,d in report['sources'].items():
        if runtime.sha(p)!=d:raise ValueError('Feature cache changed')
    all_rows=selected(plan['records']);comparisons={}
    with np.load(FOLDER/'features.npz',allow_pickle=False) as values:
        if values['ids'].tolist()!=[r['id'] for r in data['rows']]:raise ValueError('Feature order changed')
        for name,spec in plan['models'].items():
            mask=model_membership(name,values['available']);rows=[data['rows'][i] for i in np.flatnonzero(mask)]
            outputs=runtime.predict(spec,rows,values['paired'][mask],values['temporal'][mask],values['present'][mask])
            comparisons[name]={'all':output_summary(all_rows,outputs),
                'styles':{s:output_summary([r for r in all_rows if r['style']==s],
                    [o for o in outputs if any(r['id']==o['id'] and r['style']==s for r in all_rows)]) for s in ('Plain','Lombard')},
                'pairs':style_pairs(all_rows,outputs),'predictions':outputs}
    save('evaluation.json',{'complete':True,'plan_sha256':runtime.sha(FOLDER/'plan.json'),
        'feature_report_sha256':runtime.sha(FOLDER/'feature-report.json'),'comparisons':comparisons,
        'actual_phone_accuracy_measured':False,'new_fit_or_threshold_selection':False,'production_enabled':False})
    print('MATRIX OUTPUT COMPARISON COMPLETE',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','content','budget','api','align','features','evaluate'])
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.mode=='api':asyncio.run(api(args.allow_paid))
    else:globals()[args.mode]()
