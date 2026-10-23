"""Reference-audio controls only; no learner diagnosis or application integration."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
from suntone_probe import Probe, public_result, private_json
from validate_nasal_provider import prepare

async def run(args):
    folder=Path(args.directory);folder.mkdir(parents=True,exist_ok=True)
    probe=Probe(folder,allow_paid=args.allow_paid)
    rows=[]
    for cell in prepare(Path('data'),Path('data/derived/nasal-validation-v2')):
        audio=folder/(cell['audio_id']+'.mp3')
        if not audio.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',cell['audio_file'],'-ac','1','-ar','16000','-c:a','libmp3lame','-b:a','64k',str(audio)],check=True)
        r=public_result(await probe.call(audio,cell['reference']))
        row={k:cell[k] for k in ('reference','spoken_label','pair','audio_id')};row['result']=r
        rows.append(row);private_json(folder/'word-report.json',{'source':'Original labeled reference clips, not learner errors','cells':rows})
        phones=r.get('words',[{}])[0].get('phonemes',[])
        print(json.dumps({'spoken':cell['spoken_label'],'reference':cell['reference'],'status':r['status'],'final_score':phones[-1]['pronunciation'] if phones else None},ensure_ascii=False),flush=True)
        if r['status']!='ok':break

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',default='data/derived/suntone-validation');p.add_argument('--allow-paid',action='store_true')
    asyncio.run(run(p.parse_args()))
