"""Check transport pacing, score strictness and explicit expected pinyin."""
import argparse
import asyncio
import json
from pathlib import Path
from suntone_probe import Probe, evaluate, public_result, private_json

class PacedProbe(Probe):
    cache_namespace=b'suntone-mp3-320-per40ms-v1'
    async def evaluate(self,config,params,audio):
        return await evaluate(config,params,audio,frame_bytes=320)

async def run(args):
    folder=Path(args.directory);cells=json.loads((folder/'word-report.json').read_text())['cells']
    default=Probe(folder,allow_paid=args.allow_paid);paced=PacedProbe(folder,allow_paid=args.allow_paid)
    rows=[]
    variants=[('realtime-mp3',paced,{}),('strict-half',default,{'slack':-.5,'precision':.1}),('explicit-pinyin',default,{})]
    for label,probe,extra in variants:
        for spoken,reference in [('心','心'),('星','心'),('星','星'),('林','林')]:
            c=next(c for c in cells if c['spoken_label']==spoken and c['reference']==reference)
            options=extra.copy()
            if label=='explicit-pinyin':options.update(refPinyin={'心':'xin1','星':'xing1','林':'lin2'}[reference],precision=.1,getParam=1)
            r=await probe.call(folder/(c['audio_id']+'.mp3'),reference,**options)
            public=public_result(r);rows.append({'variant':label,'spoken_label':spoken,'reference':reference,'parameters':options,'result':public})
            private_json(folder/'usage-audit.json',{'cells':rows})
            phones=public.get('words',[{}])[0].get('phonemes',[])
            print(json.dumps({'variant':label,'spoken':spoken,'required':reference,'status':public['status'],'final':phones[-1]['pronunciation'] if phones else None},ensure_ascii=False),flush=True)
            if public['status']!='ok':return

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',default='data/derived/suntone-validation');p.add_argument('--allow-paid',action='store_true')
    asyncio.run(run(p.parse_args()))
