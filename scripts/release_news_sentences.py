"""Stage <=8 minute Jianying inputs; publish verified dual-voice news additively."""
import argparse
import json
import math
from pathlib import Path
import random
import re
import wave

import voice_conversion_batch as vc
import voice_conversion_groups as groups

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
OUT=DATA/'derived/news-sentence-v1'
VOICES=DATA/'derived/voice-conversion'


def all_candidates():
    from prepare_news_sentences import extract_article
    result=[]
    for path in sorted((OUT/'articles').glob('*.json'),reverse=True):
        article=json.loads(path.read_text())
        raw_path=DATA/'raw/news-wechat-v1'/path.name
        raw=json.loads(raw_path.read_text())
        _,_,sentences=extract_article(raw)
        text_by_id={row['sentence_id']:row['text'] for row in sentences}
        for row in article['sentences']:
            # Assign closing quotation marks to the sentence they belong to;
            # this does not change any spoken character, ID or cut boundary.
            text=text_by_id[row['sentence_id']]
            result.append({**row,'text':text,'spoken_text':text})
    return result


def select(count, existing=()):
    # Round-robin across articles, with at most five unique sentences per article.
    by_article={};seen={row["text"] for row in existing}
    previous_counts={}
    for row in existing:previous_counts[row["article_id"]]=previous_counts.get(row["article_id"],0)+1
    for row in all_candidates():
        text=row['text']
        if not text.endswith(('。','！','？','。”','！”','？”')):continue
        if any(text.count(left)!=text.count(right) for left,right in [('“','”'),('‘','’'),('（','）'),('《','》')]):continue
        if row['text'] in seen:continue
        seen.add(row['text']);by_article.setdefault(row['article_id'],[]).append(row)
    rng=random.Random(20261022);articles=list(by_article);rng.shuffle(articles)
    for article,rows in by_article.items():
        rows.sort(key=lambda r:(-r['confidence'],-r['nasal_count']))
        by_article[article]=rows[:max(0,5-previous_counts.get(article,0))]
    picked=[]
    for index in range(5):
        for article in articles:
            if len(by_article[article])>index:picked.append(by_article[article][index])
            if len(picked)==count:return picked
    raise ValueError(f'Need {count} verified sentences; currently {len(picked)}')


def prepare(count):
    selection=OUT/'selection.json'
    previous=json.loads(selection.read_text()) if selection.exists() else []
    if count<len(previous):raise ValueError('Refuse to shrink an existing news selection')
    snapshot=OUT/f'selection-{count:04d}.json'
    if snapshot.exists():
        rows=json.loads(snapshot.read_text())
        if rows[:len(previous)]!=previous:raise ValueError('Selection prefix changed')
    else:
        rows=previous+select(count-len(previous),previous) if count>len(previous) else previous
        vc.write_json(snapshot,rows)
    batch=VOICES/'news-sentences-female-v1'
    old_queue=json.loads((batch/'queue.json').read_text())['jobs'] if (batch/'queue.json').exists() else []
    primary=[j for j in old_queue if j['kind']!='repair']
    reserved={c['id'] for j in primary for c in j['clips']}
    fresh_rows=[r for r in rows if r['sentence_id'] not in reserved]
    sources=OUT/'conversion-inputs';sources.mkdir(exist_ok=True)
    packets=[];current=[];seconds=0
    for row in fresh_rows:
        length=math.ceil((row['clip_duration']+.4)*10)/10
        if current and seconds+length>480:packets.append(current);current=[];seconds=0
        current.append(row);seconds+=length
    if current:packets.append(current)
    jobs=[]
    start=max((int(j["id"].split("-")[1]) for j in primary),default=0)+1
    for index,packet in enumerate(packets,start):
        jid=f'news-{index:03d}';path=sources/(jid+'.wav');clips=[];cursor=0
        payload=bytearray()
        for row in packet:
            original=DATA/row['original_relative_path']
            if vc.digest(original)!=row['clip_sha256']:raise ValueError('Candidate changed')
            with wave.open(str(original),'rb') as f:
                if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,16000):raise ValueError('Wrong clip format')
                frames=f.getnframes();pcm=f.readframes(frames)
            clips.append({'id':row['sentence_id'],'text':row['text'],'relative_path':row['original_relative_path'],
                          'start':cursor/16000,'end':(cursor+frames)/16000})
            packet_samples=math.ceil((frames/16000+.4)*10)*1600
            payload.extend(pcm);payload.extend(bytes((packet_samples-frames)*2));cursor+=packet_samples
        if not path.exists():
            with wave.open(str(path),'wb') as f:f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(payload)
        elif path.read_bytes()[44:]!=payload:
            raise ValueError('Existing packet differs from selected sentences')
        jobs.append({'id':jid,'kind':'sentence','source':str(path.resolve()),'source_sha256':vc.digest(path),
                     'duration':cursor/16000,'clips':clips,'voice':'news-female',
                     'export_name':jid+'__news-female.wav'})
    canonical=primary+jobs
    for voice,name in (('news-female','news-sentences-female-v1'),('news-male','news-sentences-male-v1')):
        target=VOICES/name;queue_file=target/'queue.json'
        existing=json.loads(queue_file.read_text())['jobs'] if queue_file.exists() else []
        main=[{**j,'voice':voice,'export_name':j['id']+'__'+voice+'.wav'} for j in canonical]
        expected={j['id']:j for j in main}
        for j in existing:
            if j['kind']!='repair' and j!=expected.get(j['id']):raise ValueError('Existing source job changed')
        payload={'version':1,'jobs':main+[j for j in existing if j['kind']=='repair']}
        temporary=queue_file.with_suffix('.tmp');vc.write_json(temporary,payload);temporary.replace(queue_file)
        for folder in ('inputs','exports','reports'):(target/folder).mkdir(exist_ok=True)
        plan=groups.prepare(target)
        assigned={row['job'] for g in plan['groups'] for row in g['jobs']}
        pending=[j for j in main if j['id'] not in assigned]
        for offset in range(0,len(pending),30):
            packet_jobs=pending[offset:offset+30]
            gid=f"group-{max(int(g['id'].split('-')[1]) for g in plan['groups'])+1:03d}"
            cursor=0;entries=[]
            for i,j in enumerate(packet_jobs,1):
                duration=math.ceil(j['duration']*10)/10;samples=round(duration*16000)
                entries.append({'job':j['id'],'source':j['source'],'source_sha256':j['source_sha256'],
                    'duration':duration,'start_sample':cursor,'samples':samples,
                    'file':f"{voice}__{i:03d}__{j['id']}.wav"});cursor+=samples
            plan['groups'].append({'id':gid,'duration':cursor/16000,'jobs':entries,'voice':voice,
                                   'export_name':gid+'__'+voice+'.wav'})
        vc.write_json(target/'groups/plan.json',plan)
        for group in plan['groups']:
            if not (target/'exports'/group['export_name']).exists():groups.inputs(target,group['id'])
    vc.write_json(selection,rows)
    print(json.dumps({'sentences':len(rows),'packets':len(canonical),'new_packets':len(jobs),
                      'seconds':sum(j['duration'] for j in canonical)}))


def publish(count):
    old_backup=OUT/'voice-pointer-before-news.json'
    if old_backup.exists():raise ValueError('News already published; do not activate twice')
    selection=json.loads((OUT/'selection.json').read_text())
    if len(selection)!=count:raise ValueError(f'Expected {count} news sentences before activation')
    from curate_news_release import curate, verify
    accepted, curated = curate(DATA)
    pointer=VOICES/'active.json';previous=json.loads(pointer.read_text())
    manifests={}
    for voice,batch_name in (('news-female','news-sentences-female-v1'),('news-male','news-sentences-male-v1')):
        batch=VOICES/batch_name
        # News is curated from a larger corpus: questionable candidates are held
        # in both voices instead of weakening the existing conversion checks.
        fresh=curated[voice]
        verify(DATA,fresh)
        vc.write_json(batch/'release-news-v1.json',fresh)
        descriptor=previous['voices'][voice];old_file=DATA/descriptor['manifest']
        if vc.digest(old_file)!=descriptor['sha256']:raise ValueError('Previous voice manifest changed')
        old=json.loads(old_file.read_text())
        if set(old['clips']) & set(fresh['clips']):raise ValueError('New IDs overlap the old library')
        if set(fresh['clips'])!={r['sentence_id'] for r in accepted}:raise ValueError('Paired news release incomplete')
        combined={**old,'jobs':old['jobs']+fresh['jobs'],'clip_count':old['clip_count']+fresh['clip_count'],
                  'clips':{**old['clips'],**fresh['clips']}}
        target=batch/'combined-release-v1.json'
        if target.exists() and json.loads(target.read_text())!=combined:raise ValueError('Refuse to replace immutable release')
        if not target.exists():vc.write_json(target,combined)
        manifests[voice]={'manifest':target.relative_to(DATA).as_posix(),'sha256':vc.digest(target)}
    vc.write_json(old_backup,previous)
    vc.write_json(OUT/'release.json',{'version':1,'count':len(accepted),'sentences':accepted,
                                    'scope':'private local sentence practice'})
    # App restart follows activation; original clips/releases and all progress remain untouched.
    temporary=pointer.with_suffix('.news-tmp')
    vc.write_json(temporary,{**previous,'voices':manifests});temporary.replace(pointer)
    print(json.dumps({'activated_news':len(accepted),'held_candidates':len(selection)-len(accepted),'voices':list(manifests),'previous_clips':old['clip_count']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','publish']);parser.add_argument('--count',type=int,default=582)
    args=parser.parse_args()
    prepare(args.count) if args.command=='prepare' else publish(args.count)
