"""Isolate annotated vowel errors that preserve the n/ng class.

These are not correctly pronounced words. They are specificity controls for a
nasal-confusion claim, selected without API/model results and validation only.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave
from zipfile import ZipFile

from audit_griffith_nominal import canonical_syllable, map_nominal_canonical, sha
from nasal_acoustics import nasal_group
from prepare_griffith_nasal_probe import auxiliary_conflict, same_interval
from probe_eduhk_nasal import model_final
from suntone_probe import private_json


BASE=Path('data/derived/nasal-acoustic-validation')
FOLDER=BASE/'same-tail-controls-v1'


def same_tail_label(nominal, error, miscellaneous=''):
    syllable=canonical_syllable(nominal);expected=nasal_group(model_final(syllable))
    if expected is None or syllable.endswith('r') or miscellaneous.strip():return None
    segment=re.sub(r'TT?[0-4]\{[0-4]\}','',error).strip()
    match=re.fullmatch(r'([a-z]+)\{([a-z]+)\}',segment)
    if not match or not syllable.endswith(match[1]):return None
    actual=syllable[:-len(match[1])]+match[2]
    if actual==syllable or nasal_group(model_final(actual))!=expected:return None
    return {'state':'same_tail_segmental_error','expected_label':expected,'actual_label':expected,
            'expected_final':model_final(syllable),'actual_final':model_final(actual),
            'actual_pinyin':actual,'label_source':'explicit_suffix_same_nasal_class',
            'whole_pronunciation_correct':False,'evaluation_only':True}


def targets_for_record(record, reference):
    tiers=record['tiers'];mapping=map_nominal_canonical(tiers['NP'],reference)
    names=[k for k in ('ER','EI') if k in tiers]
    if mapping is None or len(names)!=1 or 'Misc' not in tiers:return [],'sequence_or_tier_mismatch'
    nominal=tiers['NP'];errors=tiers[names[0]];misc=tiers['Misc']
    if len(errors)!=len(nominal) or len(misc)!=len(nominal):return [],'tier_length_mismatch'
    targets=[]
    for item in mapping:
        i=item['tier_index'];n=nominal[i]
        if not same_interval(n,errors[i]) or not same_interval(n,misc[i]):continue
        label=same_tail_label(n['text'],errors[i]['text'],misc[i]['text'])
        if label is None or auxiliary_conflict(n,errors[i]['text'],tiers):continue
        targets.append({**label,'position':item['position'],'human_syllable':[n['start'],n['end']],
                        'nominal_pinyin':n['text'],'annotation':errors[i]['text']})
    return targets,None


def main():
    if FOLDER.exists():raise ValueError('Same-tail control inventory already frozen')
    directory=BASE/'griffith';archive=directory/'10072-395757_Tsurutani.zip'
    inventory=json.loads((directory/'annotations-v1.json').read_text())
    source=json.loads((directory/'source.json').read_text());stimuli=json.loads((directory/'stimuli.json').read_text())
    if sha(archive)!=source['sha256'] or inventory['archive_sha256']!=source['sha256']:
        raise ValueError('Source archive identity changed')
    records=[];excluded=Counter()
    for rec in inventory['rows']:
        numbers=re.findall(r'(?:^|_)(\d{2})(?:_|\.)',Path(rec['member']).name)
        if len(numbers)!=1 or numbers[0] not in stimuli or not rec['audio_exists']:
            excluded['unmatched_stimulus_or_audio']+=1;continue
        reference=stimuli[numbers[0]];targets,reason=targets_for_record(rec,reference)
        if reason:excluded[reason]+=1
        if targets:records.append({**{k:rec[k] for k in ('member','speaker','audio_member','annotation_sha256')},
                                   'reference':reference,'targets':targets})
    if sum(len(r['targets']) for r in records)!=24:raise ValueError('Expected 24 explicitly annotated specificity controls')
    previous={}
    for folder in ('griffith-external-v2','griffith-restored-v3'):
        for row in json.loads((BASE/folder/'input.json').read_text())['records']:
            previous.setdefault(row['member'],row)
    FOLDER.mkdir();(FOLDER/'audio').mkdir();manifest=[];reused=0
    with ZipFile(archive) as bundle:
        for rec in records:
            if hashlib.sha256(bundle.read(rec['member'])).hexdigest()!=rec['annotation_sha256']:
                raise ValueError('TextGrid identity changed')
            raw=bundle.read(rec['audio_member']);raw_sha=hashlib.sha256(raw).hexdigest()
            uid='griffith-same-tail-'+hashlib.sha256(rec['member'].encode()).hexdigest()[:16]
            prior=previous.get(rec['member'])
            if prior is not None:
                if prior['source_sha256']!=raw_sha:raise ValueError('Existing converted source differs')
                audio=Path(prior['audio']);reused+=1
            else:
                audio=FOLDER/'audio'/(uid+'.wav')
                subprocess.run(['ffmpeg','-v','error','-nostdin','-f','wav','-i','pipe:0','-ac','1',
                    '-ar','16000','-c:a','pcm_s16le',str(audio)],input=raw,check=True,capture_output=True)
                audio.chmod(0o600)
            with wave.open(str(audio),'rb') as wav:
                if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('Unexpected converted format')
                duration=wav.getnframes()/wav.getframerate()
            if not .1<duration<60 or any(not 0<=t['human_syllable'][0]<t['human_syllable'][1]<=duration+.01 for t in rec['targets']):
                raise ValueError('Target outside original audio')
            manifest.append({**rec,'uid':uid,'speaker':'griffith:'+rec['speaker'],'split':'external',
                'audio':str(audio),'audio_sha256':sha(audio),'source_audio_sha256':raw_sha,'duration':duration,
                'core':'read_sentence','reused_existing_audio':prior is not None})
    paths=[directory/name for name in ('source.json','annotations-v1.json','stimuli.json')]
    paths += [Path(__file__),Path('scripts/audit_griffith_nominal.py'),Path('scripts/prepare_griffith_nasal_probe.py'),
              Path('scripts/nasal_acoustics.py'),Path('scripts/probe_eduhk_nasal.py'),
              BASE/'hubert-temporal-v1/selection.json',BASE/'hubert-temporal-v1/evaluation.json',
              BASE/'ise-pinyin-challenge-v1/plan.json']
    plan={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'sources':{str(p):sha(p) for p in paths},
        'archive_sha256':source['sha256'],'selection':'Every strict explicit suffix substitution preserving nasal class; complete reference mapping, no Misc/auxiliary conflict.',
        'targets':24,'recordings':len(manifest),'speakers':len({r['speaker'] for r in manifest}),
        'reused_audio_recordings':reused,'newly_converted_recordings':len(manifest)-reused,
        'labels_are_nasal_class_only':True,'whole_pronunciation_correct':False,
        'training_or_threshold_tuning':False,'model_or_api_outcomes_used_in_selection':False,
        'same_corpus_speakers_as_previous_evaluation':True,'new_api_calls':0,'production_enabled':False,
        'next_measurements':['original ISE reference','same-hanzi opposite nasal reference where supported','frozen temporal model'],
        'api_budget':'Must freeze exact deduplicated keys and cumulative cap before any new request; at most one plain request per recording plus two references per target, no retries.',
        'limit':'Published closest-pronunciation annotation, not new per-target human adjudication; same nasal class does not mean a fully correct final or word.'}
    private_json(FOLDER/'plan.json',plan)
    private_json(FOLDER/'input.json',{'plan_sha256':sha(FOLDER/'plan.json'),'records':manifest,
        'excluded_record_reasons':dict(excluded),'class_counts':dict(Counter(t['expected_label'] for r in manifest for t in r['targets']))})
    print('SAME-TAIL CONTROLS FROZEN',json.dumps({k:plan[k] for k in ('targets','recordings','speakers','reused_audio_recordings','newly_converted_recordings')}),flush=True)


if __name__=='__main__':main()
