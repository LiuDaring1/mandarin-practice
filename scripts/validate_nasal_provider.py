"""Explicit small, repeatable n/ng controls using labeled local reference recordings.

Never uses learner recordings or writes learner progress. Run with --allow-paid
only when provider calls are authorized. Cached cells are not billed again.
"""
import argparse
import asyncio
import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit
from pypinyin import lazy_pinyin, Style

from pth_corpus import assessment as provider
from pth_corpus.assessment import AssessmentService, read_settings
from pth_corpus.prototype_app import PrototypeRuntime
from pth_corpus.reading_coach import nasal_feedback
from pth_corpus.sentence_reading import score_sentence

PAIRS = [('心','星'),('林','零'),('陈','成'),('真','争'),('山','商'),('班','帮')]


def prepare(root, folder):
    # Do not construct the web app: its job recovery owns real progress state.
    # The corpus runtime alone reads items without touching the reading queue.
    items=PrototypeRuntime(data_root=root).items()
    lookup={i.word_raw:i for i in items}
    cells=[]
    for front,back in PAIRS:
        for spoken in (front,back):
            item=lookup[spoken]
            output=folder/f'{item.item_id}.wav'
            if not output.exists():
                subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(root/item.clip_path),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)],check=True)
            for reference in (front,back):
                features=score_sentence(reference)
                cells.append({'reference':reference,'spoken_label':spoken,'pair':[front,back],
                    'audio_id':item.item_id,'audio_file':str(output),
                    'targets':[{'position':0,'text':reference,'pinyin':features['pinyin_seq'],'final':features['final_seq']}]})
    return cells


async def main(args):
    root=Path(args.data_root);folder=root/'derived/nasal-validation-v2';folder.mkdir(parents=True,exist_ok=True)
    service=AssessmentService(root)
    settings=read_settings(root);service.settings=lambda:{**settings,'score_coeff':4.0}
    prefix='tencent-pinyin' if args.pinyin else 'tencent'
    if args.pinyin:
        original=provider.signed_url
        def pinyin_url(settings, text, voice_id):
            url=urlsplit(original(settings,text,voice_id))
            params={k:v[0] for k,v in parse_qs(url.query).items()}
            params.pop('signature');params['eval_mode']='8'
            params['ref_text']=' '.join(lazy_pinyin(text,style=Style.TONE3,neutral_tone_with_five=True))
            unsigned=url.netloc+url.path+'?'+'&'.join(f'{k}={params[k]}' for k in sorted(params))
            params['signature']=base64.b64encode(hmac.new(settings['secret_key'].encode(),unsigned.encode(),hashlib.sha1).digest()).decode()
            return 'wss://'+url.netloc+url.path+'?'+urlencode(params)
        provider.signed_url=pinyin_url
    results=[]
    for cell in prepare(root,folder):
        path=folder/f"{prefix}-{cell['audio_id']}-{cell['reference']}.json"
        if path.exists():
            row=json.loads(path.read_text())
        else:
            if not args.allow_paid:raise SystemExit('Uncached paid cells require --allow-paid')
            result=await service.assess('nasal-v2-'+str(uuid.uuid4()),cell['reference'],Path(cell['audio_file']).read_bytes())
            aligned=copy.deepcopy(result)
            if args.pinyin:
                expected=' '.join(lazy_pinyin(cell['reference'],style=Style.TONE3,neutral_tone_with_five=True))
                if len(aligned.get('words',[]))==1 and aligned['words'][0]['text']==expected:
                    aligned['words'][0]['text']=cell['reference']
            feedback=nasal_feedback(cell['reference'],cell['targets'],aligned)
            row={**cell,'score_coeff':4.0,'result':result,'nasal_feedback':feedback}
            path.write_text(json.dumps(row,ensure_ascii=False,indent=2))
        results.append(row)
        print(json.dumps({'reference':row['reference'],'spoken_label':row['spoken_label'],'status':row['result']['status'],
                          'score':row['nasal_feedback'][0]['accuracy'] if row['nasal_feedback'] else None},ensure_ascii=False),flush=True)
    public=[]
    for row in results:
        public.append({k:row[k] for k in ('reference','spoken_label','pair','audio_id','score_coeff')}|{
            'status':row['result']['status'],'target_score':row['nasal_feedback'][0]['accuracy'] if row['nasal_feedback'] else None,
            'components':row['nasal_feedback'][0]['components'] if row['nasal_feedback'] else []})
    correct=[r['target_score'] for r in public if r['reference']==r['spoken_label'] and r['target_score'] is not None]
    wrong=[r['target_score'] for r in public if r['reference']!=r['spoken_label'] and r['target_score'] is not None]
    ranking=[]
    for row in public:
        if row['reference']!=row['spoken_label']:continue
        other=next(r for r in public if r['audio_id']==row['audio_id'] and r['reference']!=row['reference'])
        if row['target_score'] is not None and other['target_score'] is not None:
            ranking.append(row['target_score']-other['target_score'])
    report={'source':'original labeled corpus reference clips; not a new human-annotated clinical set','mode':8 if args.pinyin else 0,
        'cells':public,'available':len(correct)+len(wrong),'correct_mean':sum(correct)/len(correct) if correct else None,
        'cross_mean':sum(wrong)/len(wrong) if wrong else None,'true_final_ranks_higher':sum(d>0 for d in ranking),
        'ranking_count':len(ranking),'cross_accepted_at_70':sum(s>=70 for s in wrong),
        'correct_accepted_at_70':sum(s>=70 for s in correct),
        'auc':sum((p>n)+.5*(p==n) for p in correct for n in wrong)/(len(correct)*len(wrong)) if correct and wrong else None}
    (folder/f'{prefix}-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('SUMMARY',json.dumps({k:v for k,v in report.items() if k!='cells'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='data');p.add_argument('--allow-paid',action='store_true');p.add_argument('--pinyin',action='store_true')
    asyncio.run(main(p.parse_args()))
