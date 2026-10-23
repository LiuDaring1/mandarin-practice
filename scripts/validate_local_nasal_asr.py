"""Reference-only local alternative probe. Does not get the expected text as a prompt.

Requires the existing MLX/Qwen ASR runtime; no application dependency changes.
This is a small benchmark, not an activated pronunciation diagnostic.
"""
import argparse
import json
from pathlib import Path
import time

import httpx
from mlx_audio.stt.utils import load_model
from pypinyin import lazy_pinyin, Style


def nasal_group(text):
    chars=''.join(ch for ch in text if '\u3400' <= ch <= '\u9fff')
    groups=[]
    for py in lazy_pinyin(chars,style=Style.NORMAL):
        if py.endswith('ng'):groups.append('back')
        elif py.endswith('n'):groups.append('front')
    return groups[0] if groups and len(set(groups))==1 else None


def main(args):
    folder=Path(args.folder);report=json.loads((folder/'tencent-report.json').read_text())
    cells=[r for r in report['cells'] if r['reference']==r['spoken_label']]
    inputs=[]
    for row in cells:
        for voice in ('original','news-female','news-male'):
            path=folder/f"{row['audio_id']}-{voice}.wav"
            if voice=='original':path=folder/f"{row['audio_id']}.wav"
            elif not path.exists():
                response=httpx.get(f"http://127.0.0.1:8769/api/clips/{row['audio_id']}?voice={voice}",timeout=15)
                response.raise_for_status();path.write_bytes(response.content)
            inputs.append({'audio':str(path),'spoken_label':row['spoken_label'],'voice':voice,
                           'expected_group':nasal_group(row['spoken_label'])})
    model=load_model(Path(args.model))
    result=[]
    for item in inputs:
        cache=folder/(Path(item['audio']).stem+'-qwen.json')
        if cache.exists():row=json.loads(cache.read_text())
        else:
            started=time.monotonic()
            output=model.generate(item['audio'],language='Chinese',max_tokens=64,temperature=0)
            row={**item,'transcription':output.text,'predicted_group':nasal_group(output.text),
                 'seconds':time.monotonic()-started}
            cache.write_text(json.dumps(row,ensure_ascii=False,indent=2))
        result.append(row)
        print(json.dumps({k:row[k] for k in ('spoken_label','voice','transcription','predicted_group')},ensure_ascii=False),flush=True)
    summary={'model':'Qwen3-ASR-1.7B-8bit','reference_text_prompt':False,
             'scope':'labeled reference clips; coarse n/ng class only; not a validated human-error detector',
             'count':len(result),'correct':sum(r['predicted_group']==r['expected_group'] for r in result),
             'abstained':sum(r['predicted_group'] is None for r in result),
             'wrong':sum(r['predicted_group'] is not None and r['predicted_group']!=r['expected_group'] for r in result),
             'by_voice':{v:{'count':sum(r['voice']==v for r in result),'correct':sum(r['voice']==v and r['predicted_group']==r['expected_group'] for r in result)} for v in ('original','news-female','news-male')},
             'mean_seconds':sum(r['seconds'] for r in result)/len(result),'cells':result}
    (folder/'local-asr-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print('SUMMARY',json.dumps({k:v for k,v in summary.items() if k!='cells'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',default='data/derived/nasal-validation-v2')
    p.add_argument('--model',required=True);main(p.parse_args())
