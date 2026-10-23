"""Reference-only follow-up: existing converted voices and natural word contexts.

Converted voices share source recordings: never count them as independent speakers.
No production integration, microphone collection, or progress writes.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import wave
from ise_probe import IseProbe, public_result
from suntone_probe import private_json
from pth_corpus.prototype_app import PrototypeRuntime
from validate_nasal_provider import prepare


def pcm16(source, output):
    with wave.open(str(source),'rb') as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2):
            return source
    if not output.exists():
        output.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)],check=True)
    return output


def target_observation(result, required):
    if result['status']!='ok':return {'state':'unavailable','finals':[]}
    nodes=result['nodes']
    if any(n.get('is_rejected')=='true' or n.get('except_info','0')!='0' for n in nodes):
        return {'state':'rejected','finals':[]}
    finals=[n for n in nodes if n.get('is_yun')=='1' and n.get('syll_content',n.get('word_content'))==required]
    if len(finals)!=1:return {'state':'ambiguous_target','finals':finals}
    n=finals[0]
    if n.get('dp_message') not in ('0','128') or (n.get('dp_message')!='128' and n.get('perr_msg') not in ('0','1','2','3')):
        return {'state':'unusable_alignment','finals':finals}
    flagged=n['perr_msg'] in ('1','3') or n['dp_message']=='128'
    return {'state':'flagged' if flagged else 'not_flagged','finals':finals}


def prepare_cells(folder):
    runtime=PrototypeRuntime(data_root=Path('data'));outputs=folder/'stability-audio'
    cells=[]
    # New original recordings in natural two-character words, not concatenated audio.
    wanted=[('零件','零','林'),('林业','林','零'),('班级','班','帮'),('帮助','帮','班')]
    lookup={i.word_raw:i for i in runtime.items()}
    for word,target,opposite in wanted:
        item=lookup[word];source=Path('data')/item.clip_path
        audio=pcm16(source,outputs/(item.item_id+'.wav'))
        for cross in (False,True):
            cells.append({'kind':'word_context','voice':'original','audio_id':item.item_id,'audio':str(audio),
                          'source_text':word,'reference':word.replace(target,opposite,1) if cross else word,
                          'target':target,'required':opposite if cross else target,'cross_reference':cross,'core':'read_word'})
    for c in prepare(Path('data'),Path('data/derived/nasal-validation-v2')):
        if c['spoken_label'] not in ('心','星','林','零','班','帮'):continue
        for voice in ('original','news-female','news-male'):
            source=Path(c['audio_file']) if voice=='original' else Path('data/derived/nasal-validation-v2')/(c['audio_id']+'-'+voice+'.wav')
            audio=pcm16(source,outputs/(c['audio_id']+'-'+voice+'.wav'))
            cells.append({'kind':'single','voice':voice,'audio_id':c['audio_id'],'audio':str(audio),
                          'source_text':c['spoken_label'],'reference':c['reference'],'target':c['spoken_label'],
                          'required':c['reference'],'cross_reference':c['reference']!=c['spoken_label'],'core':'read_syllable'})
    pool=runtime.sentence_pool()
    for sid,target,opposite in [('28-我喜欢出发-0011','山','商'),('12-晋祠-0023','清','亲')]:
        row=next(r for r in pool if r['sentence_id']==sid)
        for voice in ('original','news-female','news-male'):
            source=(Path('data/derived/sentence-practice-v1/clips')/sid.rsplit('-',1)[0]/(sid+'.wav') if voice=='original' else runtime.sentence_clip_path(sid,voice))
            if source is None:raise RuntimeError('Required converted sentence is missing')
            audio=pcm16(source,outputs/(sid+'-'+voice+'.wav'))
            for cross in (False,True):
                cells.append({'kind':'sentence','voice':voice,'audio_id':sid,'audio':str(audio),'source_text':row['text'],
                              'reference':row['text'].replace(target,opposite,1) if cross else row['text'],
                              'target':target,'required':opposite if cross else target,'cross_reference':cross,'core':'read_sentence'})
    return cells


async def run(args):
    folder=Path(args.directory);cells=prepare_cells(folder)
    # Prior ledger stays intact. This user-authorized batch adds at most 40 calls.
    probe=IseProbe(folder,allow_paid=args.allow_paid,max_calls=args.max_total_calls)
    rows=[]
    for cell in cells:
        result=public_result(await probe.call(cell['audio'],cell['reference'],core=cell['core']))
        observation=target_observation(result,cell['required'])
        row={k:cell[k] for k in ('kind','voice','audio_id','target','required','cross_reference','core')}
        row.update(status=result['status'],observation=observation,audio_sha256=hashlib.sha256(Path(cell['audio']).read_bytes()).hexdigest())
        if cell['kind']!='sentence':row.update(source_text=cell['source_text'],reference=cell['reference'])
        rows.append(row);private_json(folder/'stability-2026-10-24.json',{'cells':rows})
        print(json.dumps({'kind':cell['kind'],'voice':cell['voice'],'spoken_target':cell['target'],'required':cell['required'],'state':observation['state']},ensure_ascii=False),flush=True)
        if result['status']!='ok':raise RuntimeError('Provider failure; batch stopped without retry')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',default='data/derived/ise-validation');p.add_argument('--allow-paid',action='store_true');p.add_argument('--max-total-calls',type=int,default=80)
    asyncio.run(run(p.parse_args()))
