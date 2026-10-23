"""Isolated continuous-reading UI QA. No real microphone or paid provider calls."""
import asyncio
from pathlib import Path
from tempfile import mkdtemp
import argparse
import uvicorn
from pth_corpus.prototype_app import create_app
from pth_corpus import assessment
from pth_corpus.sentence_reading import score_sentence

root=Path(__file__).resolve().parents[1]
scratch=Path(mkdtemp(prefix='pth-reading-qa-'))
app=create_app(root/'data',prototype_dir=scratch)
service=app.state.assessment
# Explicit synthetic scorer exercises the future review pipeline, never production.
app.state.reading_coach.nasal_review_enabled=True
service.settings=lambda:dict(appid='qa',secret_id='qa',secret_key='qa',score_coeff=2,limit_units=1000)
control={'delay':4,'status':'ok','completion':100,'calls':0}
async def provider(settings,text,audio):
    control['calls']+=1
    await asyncio.sleep(control['delay'])
    if control['status']!='ok':return {'status':control['status']}
    features=score_sentence(text)
    words=[]
    for ch,final in zip((c for c in text if c.isalnum()),features['final_seq'].split()):
        words.append({'text':ch,'tag':0,'accuracy':10,'phones':[{'phone':final+'1','accuracy':45 if final.endswith('n') else 95,'tag':0}]})
    return {'status':'ok','score':10,'completion':control['completion'],'words':words}
assessment.evaluate=provider
@app.get('/__qa/info')
def info():return {'isolated':True,'progress_dir':str(scratch),'provider':'synthetic','control':control}
@app.post('/__qa/control')
def configure(payload:dict):
    for key in ('delay','status','completion'):
        if key in payload:control[key]=payload[key]
    if 'nasal_ready' in payload:app.state.reading_coach.nasal_review_enabled=bool(payload['nasal_ready'])
    return control
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8776);args=parser.parse_args()
    print(f'Isolated reading QA progress: {scratch}',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
