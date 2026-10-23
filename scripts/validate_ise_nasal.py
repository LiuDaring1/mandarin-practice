"""Same labeled reference controls as Suntone, using documented ISE error fields."""
import argparse
import asyncio
import json
from pathlib import Path
from ise_probe import IseProbe, public_result
from suntone_probe import private_json
from validate_nasal_provider import prepare

async def run(args):
    folder=Path(args.directory);probe=IseProbe(folder,allow_paid=args.allow_paid,max_calls=40);rows=[]
    for cell in prepare(Path('data'),Path('data/derived/nasal-validation-v2')):
        result=public_result(await probe.call(cell['audio_file'],cell['reference'],core='read_syllable',check_type=args.check_type))
        row={k:cell[k] for k in ('reference','spoken_label','pair','audio_id')};row['result']=result;rows.append(row)
        private_json(folder/f'words-{args.check_type}.json',{'check_type':args.check_type,'source':'Original reference clips; not learner diagnosis accuracy','cells':rows})
        print(json.dumps({'spoken':cell['spoken_label'],'required':cell['reference'],'result':result['status'],'finals':[n for n in result.get('nodes',[]) if n.get('is_yun')=='1']},ensure_ascii=False),flush=True)
        if result['status']!='ok':break

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',default='data/derived/ise-validation');p.add_argument('--allow-paid',action='store_true');p.add_argument('--check-type',choices=['common','hard'],default='common')
    asyncio.run(run(p.parse_args()))
