"""New recordings for a frozen classifier, with no fitting/development speakers.

Selection uses published human labels and source identities, never predictions.
Normal controls require three unanimous vowel scores and an exact aggregate join.
The sources were explored earlier; this is not a final unseen product benchmark.
"""
import argparse
import asyncio
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import wave

from pypinyin import lazy_pinyin, Style

from nasal_acoustics import nasal_group
from prepare_eduhk_passage_probe import chinese_reference
from prepare_ompal_controls import unanimous_correct
from probe_eduhk_nasal import model_final
from train_nasal_feature_probe import save_json as private_json


SEED = 'feedback-v3-fresh-recordings-20261027'


def label(final):
    return nasal_group(final) or 'other'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def download_audio(folder, uid, url, suffix):
    source=folder/(uid+'-source'+suffix); audio=folder/(uid+'.wav')
    if not source.exists():
        source.write_bytes(urllib.request.urlopen(url,timeout=30).read())
        source.chmod(0o600)
    if not audio.exists():
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(audio)],check=True)
        audio.chmod(0o600)
    with wave.open(str(audio),'rb') as wav:
        duration=wav.getnframes()/wav.getframerate()
    return str(audio),duration,hashlib.sha256(source.read_bytes()).hexdigest()


def prepare(folder):
    from opencc import OpenCC
    converter=OpenCC('tw2s')
    base=Path('data/derived/nasal-acoustic-validation')
    fit=json.loads((base/'feature-classifier-v2-final/dataset.json').read_text())['rows']
    fit_speakers={r['speaker'] for r in fit if r['split'] in ('train','dev')}
    known_audio={r['audio_sha256'] for r in fit}
    if (folder/'input.json').exists():
        raise ValueError('Holdout selection is already frozen')
    audio_dir=folder/'audio';audio_dir.mkdir(parents=True,exist_ok=True)
    records=[];excluded=[]
    passages=json.loads((base/'eduhk-passages/annotations.json').read_text())['rows']
    used_passages={r['uid'] for r in json.loads((base/'eduhk-passages/probe-input.json').read_text())['recordings']}
    for row in passages:
        speaker='eduhk:'+str(row['speaker']);uid=f"eduhk-s{row['speaker']}-p{row['passage']}"
        if row['passage']!=1 or not row['nasal_errors'] or speaker in fit_speakers or uid in used_passages:
            continue
        reference=converter.convert(chinese_reference(row['text']))
        chars=''.join(c for c in reference if '\u3400'<=c<='\u9fff')
        if len(chars)!=len(row['characters']) or len(chars)>100:
            raise ValueError('Passage character positions do not match')
        pinyin=lazy_pinyin(chars,style=Style.NORMAL);targets=[]
        for error in row['nasal_errors']:
            pos=error['position']
            if pinyin[pos]!=error['expected_plain']:
                raise ValueError('Passage contextual pronunciation differs from annotation')
            final=model_final(pinyin[pos])
            targets.append({'position':pos,'expected_final':final,'expected_label':label(final),
                            'actual_label':error['actual_group'],'condition':'sentence_error',
                            'label_source':'explicit_nasal_substitution'})
        audio,duration,sha=download_audio(audio_dir,uid,row['audio_url'],'.mp3')
        if not .1<=duration<40:
            excluded.append({'id':uid,'speaker':speaker,'split':'holdout',
                             'reason':'outside_existing_duration_envelope','duration':duration,'target_count':len(targets)})
            continue
        records.append({'uid':uid,'speaker':speaker,'audio':audio,'reference':reference,'targets':targets,
                        'source_url':row['audio_url'],'source_sha256':sha,'duration':duration})
    ompal=base/'ompal'
    raw=json.loads((ompal/'non-native_scores-detail.json').read_text())
    aggregate=json.loads((ompal/'non-native_scores.json').read_text())
    revision=json.loads((ompal/'source-revision.json').read_text())['commit']
    paths={Path(r['path']).stem:r['path'] for r in json.loads((ompal/'tree.json').read_text())['tree'] if r['path'].endswith('.wav')}
    used={r['uid'] for manifest in ['controls-input.json','expansion-input.json']
          for r in json.loads((ompal/manifest).read_text())['recordings']}
    pools=defaultdict(list)
    for uid,record in raw.items():
        speaker='ompal:'+uid[:6]
        if uid in used or uid not in paths or uid not in aggregate or speaker in fit_speakers:
            continue
        other=aggregate[uid]
        if record['text']!=other['text'] or [w['text'] for w in record['words']]!=[w['text'] for w in other['words']]:
            raise ValueError('Normal-control annotation identity mismatch')
        chars=''.join(c for c in record['text'] if '\u3400'<=c<='\u9fff')
        if any(len(w['text'])!=1 or len(w['text'][0])!=1 for w in record['words']) or ''.join(w['text'][0] for w in record['words'])!=chars:
            continue
        reference=converter.convert(chars)
        if len(reference)!=len(chars):
            continue
        finals=[model_final(p) for p in lazy_pinyin(reference,style=Style.NORMAL)]
        targets=[]
        for pos,word in enumerate(record['words']):
            final=finals[pos]
            if label(final)=='other' or not unanimous_correct(word['phoneme_vowel']):
                continue
            if other['words'][pos]['phoneme_vowel']!=1:
                raise ValueError('Normal-control teacher labels conflict')
            targets.append({'position':pos,'expected_final':final,'expected_label':label(final),
                            'actual_label':label(final),'condition':'teacher_correct','label_source':'unanimous_vowel_scores'})
        if len(targets)>=2:
            pools[speaker].append({'uid':uid,'speaker':speaker,'reference':reference,'targets':targets})
    for speaker in sorted(pools,key=lambda s:digest(SEED+s))[:4]:
        for record in sorted(pools[speaker],key=lambda r:digest(SEED+r['uid']))[:2]:
            uid=record['uid'];url=f'https://raw.githubusercontent.com/phantomhsieh/OMPAL-corpus/{revision}/{paths[uid]}'
            audio,duration,sha=download_audio(audio_dir,uid,url,'.wav')
            if not .1<=duration<40:
                excluded.append({'id':uid,'speaker':speaker,'split':'holdout','reason':'outside_existing_duration_envelope',
                                 'duration':duration,'target_count':len(record['targets'])})
                continue
            records.append({**record,'audio':audio,'source_url':url,'source_sha256':sha,'duration':duration})
    cases=[]
    for record in records:
        if hashlib.sha256(Path(record['audio']).read_bytes()).hexdigest() in known_audio:
            raise ValueError('Holdout audio duplicates an earlier model dataset recording')
        pos=record['targets'][0]['position']
        cases.append({'id':record['uid'],'audio':record['audio'],'reference':record['reference'],
                      'position':pos,'core':'read_sentence','condition':'holdout_alignment_carrier'})
    private_json(folder/'input.json',{'selection_seed':SEED,'selection_used_predictions':False,
                                    'fit_speaker_overlap':False,'recordings':records,'cases':cases,'excluded':excluded})
    print('recordings',len(records),'targets',sum(len(r['targets']) for r in records),'excluded',excluded,flush=True)


async def freeze(folder):
    from ise_probe import IseProbe, public_result, target_at
    from prepare_nasal_feature_data import interval
    if (folder/'dataset.json').exists():
        raise ValueError('Holdout dataset is frozen')
    manifest=json.loads((folder/'input.json').read_text())
    probe=IseProbe(Path('data/derived/ise-validation'),allow_paid=False)
    ledger=Path('data/derived/ise-validation/requests.json');before=ledger.read_bytes()
    rows=[];excluded=list(manifest['excluded'])
    for rec in manifest['recordings']:
        result=public_result(await probe.call(rec['audio'],rec['reference'],core='read_sentence'))
        for target in rec['targets']:
            row={'id':rec['uid']+'-pos'+str(target['position']),'speaker':rec['speaker'],'split':'holdout',
                 'audio':rec['audio'],'reference':rec['reference'],**target}
            bounds=interval(target_at(result,rec['reference'],target['position']),rec['audio'])
            if bounds is None:
                excluded.append({'id':row['id'],'speaker':row['speaker'],'split':'holdout',
                                 'reason':'unusable_cached_interval','target_count':1})
            else:
                rows.append({**row,'bounds':bounds,'audio_sha256':hashlib.sha256(Path(rec['audio']).read_bytes()).hexdigest()})
    if before!=ledger.read_bytes():
        raise ValueError('Cache-only preparation changed the API ledger')
    private_json(folder/'dataset.json',{'rows':rows,'excluded':excluded,'frozen_after_selection':True})
    print('usable targets',len(rows),'excluded targets',sum(r['target_count'] for r in excluded),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','freeze'])
    parser.add_argument('--directory',default='data/derived/nasal-acoustic-validation/feedback-v3-holdout')
    args=parser.parse_args();folder=Path(args.directory)
    if args.mode=='prepare':prepare(folder)
    else:asyncio.run(freeze(folder))
