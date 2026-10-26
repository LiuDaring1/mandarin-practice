"""Extend the frozen speaker partitions with explicit sentence nasal errors.

No unmarked EdUHK syllable becomes a positive label. Existing held-out speakers
remain held out. Unassigned speakers form additional validation, never training.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import wave

from nasal_acoustics import nasal_group
from prepare_eduhk_passage_probe import chinese_reference
from prepare_nasal_feedback_holdout import download_audio
from probe_eduhk_nasal import model_final
from train_nasal_feature_probe import save_json


BASE=Path('data/derived/nasal-acoustic-validation')


def speaker_partitions():
    original=json.loads((BASE/'feature-classifier-v2-phoneme/dataset.json').read_text())
    fresh=json.loads((BASE/'feedback-v3-holdout/dataset.json').read_text())
    mapping={r['speaker']:r['split'] for r in original['rows']}
    manifest=json.loads((BASE/'feedback-v3-holdout/input.json').read_text())
    for rec in manifest['recordings']+manifest['excluded']:
        if mapping.get(rec['speaker']) in ('train','dev'):
            raise ValueError('Previously held-out speaker is in fitting data')
        mapping.setdefault(rec['speaker'],'holdout')
    return original,fresh,mapping


def prepare(folder):
    from opencc import OpenCC
    converter=OpenCC('tw2s')
    if (folder/'input.json').exists():
        raise ValueError('Sentence expansion is already frozen')
    _,_,mapping=speaker_partitions()
    annotations=json.loads((BASE/'eduhk-passages/annotations.json').read_text())
    if annotations.get('complete') is not True:
        raise ValueError('Incomplete source annotations')
    known={r['uid']:r for manifest in ['eduhk-passages/probe-input.json','feedback-v3-holdout/input.json']
           for r in json.loads((BASE/manifest).read_text())['recordings'] if r['uid'].startswith('eduhk-')}
    audio_dir=folder/'audio';audio_dir.mkdir(parents=True,exist_ok=True)
    records=[];excluded=[]
    for source in annotations['rows']:
        if not source['nasal_errors']:
            continue
        uid=f"eduhk-s{source['speaker']}-p{source['passage']}";speaker='eduhk:'+str(source['speaker'])
        split=mapping.get(speaker,'validation')
        reference=converter.convert(chinese_reference(source['text']))
        chars=''.join(c for c in reference if '\u3400'<=c<='\u9fff')
        if len(chars)!=len(source['characters']) or len(chars)>1000:
            raise ValueError('Passage reference position/length mismatch')
        targets=[]
        for error in source['nasal_errors']:
            pos=error['position']
            if chars[pos]!=converter.convert(error['character']):
                raise ValueError('Human target character does not match reference')
            final=model_final(error['expected_plain'])
            expected=nasal_group(final)
            if expected not in ('front','back') or expected==error['actual_group']:
                raise ValueError('Human expected nasal label mismatch')
            targets.append({'position':pos,'expected_final':final,'expected_label':expected,
                            'actual_label':error['actual_group'],'label_source':'explicit_nasal_substitution'})
        if uid in known:
            audio=known[uid]['audio'];sha=known[uid]['source_sha256']
            with wave.open(audio,'rb') as wav:duration=wav.getnframes()/wav.getframerate()
        else:
            audio,duration,sha=download_audio(audio_dir,uid,source['audio_url'],'.mp3')
        if not .1<=duration<=180:
            excluded.extend({'id':uid+'-pos'+str(t['position']),'speaker':speaker,'split':split,
                             'reason':'outside_180_second_envelope','duration':duration,'actual_label':t['actual_label']}
                            for t in targets)
            continue
        records.append({'uid':uid,'speaker':speaker,'split':split,'audio':audio,'reference':reference,
                        'core':'read_sentence' if len(chars)<=100 else 'read_chapter','targets':targets,
                        'source_url':source['audio_url'],'source_sha256':sha,'duration':duration})
        print(uid,split,round(duration,2),'seconds',len(targets),'targets',flush=True)
    # Start with the previously excluded long passage and one chapter as the
    # protocol smoke check. The full batch subsequently reuses their cache.
    records.sort(key=lambda r:(0 if r['uid']=='eduhk-s33-p1' else 1 if r['core']=='read_chapter' else 2,r['uid']))
    cases=[{'id':r['uid'],'audio':r['audio'],'reference':r['reference'],'position':r['targets'][0]['position'],
            'core':r['core'],'condition':'sentence_alignment_carrier'} for r in records]
    save_json(folder/'input.json',{'records':records,'cases':cases,'excluded':excluded,
                                 'selection_used_predictions':False,'existing_speaker_partitions_preserved':True})
    save_json(folder/'smoke-input.json',{'cases':cases[:2]})
    print('COMPLETE',len(records),'recordings',sum(len(r['targets']) for r in records),'targets',flush=True)


async def freeze(folder):
    from ise_probe import IseProbe,public_result,target_at
    from nasal_feature_probe import assert_speaker_partition
    from prepare_nasal_feature_data import interval
    output=folder/'dataset.json'
    if output.exists():
        raise ValueError('Context training dataset is frozen')
    original,fresh,mapping=speaker_partitions()
    manifest=json.loads((folder/'input.json').read_text())
    ledger=Path('data/derived/ise-validation/requests.json');before=ledger.read_bytes()
    probe=IseProbe(ledger.parent,allow_paid=False);cache={}
    async def result(audio,reference,core):
        key=(audio,reference,core)
        if key not in cache:
            cache[key]=public_result(await probe.call(audio,reference,core=core))
        return cache[key]
    word_cores={r['id']:r['core'] for r in json.loads((BASE/'ise-word-calibration-input.json').read_text())['cases']}
    by_id={};excluded=list(original['excluded'])
    for cohort,dataset in [('previous',original),('previous_holdout',fresh)]:
        for row in dataset['rows']:
            core=word_cores[row['id']] if row['condition']=='word_error' else 'read_sentence'
            state=target_at(await result(row['audio'],row['reference'],core),row['reference'],row['position'])['state']
            canonical={**row,'split':mapping[row['speaker']],'cohort':cohort,'api_state':state,'core':core}
            if row['id'] in by_id:
                raise ValueError('Repeated existing target identity')
            by_id[row['id']]=canonical
    # A duration exclusion is historical and will be attempted in this manifest;
    # keep other unavailable normal targets in the new denominator.
    for row in fresh['excluded']:
        if row['reason']!='outside_existing_duration_envelope':
            excluded.append({**row,'split':mapping[row['speaker']],'cohort':'previous_holdout'})
    existing_ids=set(by_id)
    for rec in manifest['records']:
        public=await result(rec['audio'],rec['reference'],rec['core'])
        for target in rec['targets']:
            uid=rec['uid']+'-pos'+str(target['position'])
            row={'id':uid,'speaker':rec['speaker'],'split':rec['split'],'cohort':'new_sentence',
                 'condition':'sentence_error','audio':rec['audio'],'reference':rec['reference'],
                 'core':rec['core'],**target}
            observation=target_at(public,rec['reference'],target['position'])
            bounds=interval(observation,rec['audio'])
            if uid in existing_ids:
                old=by_id[uid]
                if old['actual_label']!=row['actual_label'] or old['expected_label']!=row['expected_label'] or old['split']!=row['split']:
                    raise ValueError('New manifest conflicts with previous target labels/partitions')
                continue
            if bounds is None:
                excluded.append({k:row[k] for k in ['id','speaker','split','cohort','actual_label']}
                                | {'reason':'unusable_cached_interval','api_state':observation['state']})
                continue
            by_id[uid]={**row,'bounds':bounds,'api_state':observation['state'],
                        'audio_sha256':hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()}
    rows=list(by_id.values());assert_speaker_partition(rows)
    excluded.extend(manifest['excluded'])
    if before!=ledger.read_bytes():
        raise ValueError('Cache-only data preparation changed the API ledger')
    save_json(output,{'rows':rows,'excluded':excluded,'version':4,
                      'prior_data':'feature-classifier-v2-phoneme plus feedback-v3-holdout',
                      'limits':['Unassigned speakers are validation only.',
                                'Normal and erroneous labels predominantly come from different corpora.',
                                'Automatic/API boundaries are not independently human-audited.']})
    print('rows',len(rows),'excluded',len(excluded),flush=True)
    for split in sorted({r['split'] for r in rows}):
        subset=[r for r in rows if r['split']==split]
        print(split,'labels',dict(Counter(r['actual_label'] for r in subset)),
              'cohorts',dict(Counter(r['cohort'] for r in subset)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','freeze'])
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/context-training-v4')
    args=parser.parse_args();folder=Path(args.directory)
    if args.mode=='prepare':prepare(folder)
    else:asyncio.run(freeze(folder))
