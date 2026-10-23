"""Sentence reference-pronunciation controls; no learner recordings."""
import argparse,asyncio,json,subprocess
from pathlib import Path
from suntone_probe import Probe,public_result,private_json
from pth_corpus.prototype_app import PrototypeRuntime
async def main(args):
 p=Path(args.directory);p.mkdir(parents=True,exist_ok=True);probe=Probe(p,allow_paid=args.allow_paid);out=[]
 pool=PrototypeRuntime(data_root=Path('data')).sentence_pool()
 for sid,word,wrong in [('28-我喜欢出发-0011','山','shang1'),('12-晋祠-0023','清','qin1')]:
  row=next(x for x in pool if x['sentence_id']==sid)
  source=Path('data/derived/sentence-practice-v1/clips')/sid.rsplit('-',1)[0]/(sid+'.wav')
  audio=p/(sid+'.mp3')
  if not audio.exists():subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-ac','1','-ar','16000','-c:a','libmp3lame','-b:a','64k',str(audio)],check=True)
  for reference in [row['text'],row['text'].replace(word,word+'{'+wrong+'}',1)]:
   r=public_result(await probe.call(audio,reference,core='sent'))
   out.append({'audio_id':sid,'reference':reference,'target':word,'counterfactual_reference':reference!=row['text'],'result':r})
   private_json(p/'sentence-report.json',{'source':'Same original reference audio with normal or altered expected pronunciation, not learner error recordings','cells':out})
   print(json.dumps({'id':sid,'counterfactual':reference!=row['text'],'status':r['status'],'target_words':[w for w in r.get('words',[]) if w.get('word')==word]},ensure_ascii=False),flush=True)
   if r['status']!='ok':return
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--directory',default='data/derived/suntone-validation');p.add_argument('--allow-paid',action='store_true')
 asyncio.run(main(p.parse_args()))
