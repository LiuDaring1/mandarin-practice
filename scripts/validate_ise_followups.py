"""ISE strictness and sentence controls, with Suntone sentence-reference parity."""
import argparse
import asyncio
import json
from pathlib import Path
from ise_probe import IseProbe, public_result as ise_public
from suntone_probe import Probe, public_result as suntone_public, private_json
from pth_corpus.prototype_app import PrototypeRuntime
from validate_nasal_provider import prepare

async def run(args):
    folder=Path('data/derived/ise-validation');probe=IseProbe(folder,allow_paid=args.allow_paid,max_calls=40)
    pool=PrototypeRuntime(data_root=Path('data')).sentence_pool();rows=[]
    for sid,target,opposite in [('28-我喜欢出发-0011','山','商'),('12-晋祠-0023','清','亲')]:
        row=next(r for r in pool if r['sentence_id']==sid)
        wav=Path('data/derived/sentence-practice-v1/clips')/sid.rsplit('-',1)[0]/(sid+'.wav')
        for wrong in (False,True):
            ref=row['text'].replace(target,opposite,1) if wrong else row['text']
            result=ise_public(await probe.call(wav,ref,core='read_sentence'))
            rows.append({'audio_id':sid,'target':target,'required':opposite if wrong else target,'counterfactual_reference':wrong,'result':result})
            private_json(folder/'sentences.json',{'cells':rows})
            print(json.dumps({'id':sid,'wrong':wrong,'status':result['status'],'finals':[n for n in result.get('nodes',[]) if n.get('is_yun')=='1' and n.get('word_content')==(opposite if wrong else target)]},ensure_ascii=False),flush=True)
            if result['status']!='ok':return
    cells=prepare(Path('data'),Path('data/derived/nasal-validation-v2'));hard=[]
    for spoken,reference in [('心','心'),('星','心'),('零','林'),('零','零')]:
        cell=next(c for c in cells if c['spoken_label']==spoken and c['reference']==reference)
        result=ise_public(await probe.call(cell['audio_file'],reference,core='read_syllable',check_type='hard'))
        hard.append({'spoken_label':spoken,'reference':reference,'result':result})
        private_json(folder/'hard-controls.json',{'cells':hard})
        print(json.dumps({'hard':True,'spoken':spoken,'required':reference,'status':result['status'],'finals':[n for n in result.get('nodes',[]) if n.get('is_yun')=='1']},ensure_ascii=False),flush=True)
        if result['status']!='ok':return
    st=Path('data/derived/suntone-validation');sp=Probe(st,allow_paid=args.allow_paid);parity=[]
    for sid,target,opposite in [('28-我喜欢出发-0011','山','商'),('12-晋祠-0023','清','亲')]:
        row=next(r for r in pool if r['sentence_id']==sid)
        result=suntone_public(await sp.call(st/(sid+'.mp3'),row['text'].replace(target,opposite,1),core='sent'))
        parity.append({'audio_id':sid,'target':target,'required':opposite,'result':result})
        private_json(st/'sentence-parity.json',{'cells':parity})
        print(json.dumps({'suntone':True,'required':opposite,'status':result['status'],'words':[w for w in result.get('words',[]) if w['word']==opposite]},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--allow-paid',action='store_true');asyncio.run(run(p.parse_args()))
