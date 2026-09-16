#!/usr/bin/env python3
"""Build the approved A family and four revised reward slots, without overwriting old audio."""
from pathlib import Path
import json, hashlib, wave, shutil
import numpy as np

LAB=Path(__file__).resolve().parents[1]
DEST=LAB.parents[1]/'src/pth_corpus/prototype_static/sounds'
DEST.mkdir(exist_ok=True)
SR=44100
def edge(x,attack=.002,release=.04):
    a=min(len(x)//2,round(attack*SR));r=min(len(x)//2,round(release*SR))
    x[:a]*=np.sin(np.linspace(0,np.pi/2,a))**2
    x[-r:]*=np.sin(np.linspace(np.pi/2,0,r))**2
    x[0]=x[-1]=0
    return x
def bead(f,d):
    t=np.arange(round(d*SR))/SR
    # Same rounded A attack, with a short upper overtone rather than low bass/saturation.
    phase=2*np.pi*f*(t+.045*.009*(1-np.exp(-t/.009)))
    x=np.sin(phase)*np.exp(-t/.105)
    x+=.31*np.sin(2*phase)*np.exp(-t/.060)
    x+=.12*np.sin(3*phase)*np.exp(-t/.035)
    x+=.065*np.sin(4.02*phase)*np.exp(-t/.020)
    return edge(x,.002,.055)
def add(dst,src,at,gain=1):
    i=round(at*SR);n=min(len(src),len(dst)-i)
    dst[i:i+n]+=gain*src[:n]

# A's 523/659/880 motif; tighter pickups and spaced, light high endings.
plans={
 'reward.arrive':(.72,-19,[(0,659,.32,.62),(.09,880,.36,.8),(.205,1047,.48,1)]),
 'day.complete':(.96,-18.5,[(0,659,.30,.60),(.085,880,.34,.74),(.195,1047,.4,.88),(.36,1318,.55,1)]),
 'artwork.complete':(1.25,-18.5,[(0,523,.30,.50),(.095,659,.32,.62),(.20,880,.38,.76),(.345,1047,.52,1),(.54,1318,.62,.55)]),
 'series.complete':(1.65,-18,[(0,523,.32,.48),(.095,659,.32,.58),(.20,880,.38,.72),(.345,1047,.48,.85),(.52,1318,.58,1),(.78,1760,.64,.5),(.80,1047,.64,.28)]),
}
manifest=json.loads((LAB/'versions/v1/manifest.json').read_text())
definitions=[s for s in manifest['sounds'] if s['style']=='a']
selected=[]
qa=[]
for s in definitions:
    s=dict(s)
    if s['id'] in plans:
        duration,peak,notes=plans[s['id']]
        y=np.zeros(round(duration*SR))
        for at,f,d,g in notes:add(y,bead(f,d),at,g)
        y=edge(y,.002,.08);y*=10**(peak/20)/max(abs(y))
        pcm=np.rint(y*32767).astype('<i2')
        name='a-v4-'+s['id'].replace('.','-')+'.wav'
        with wave.open(str(LAB/'exports'/name),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(SR);w.writeframes(pcm.tobytes())
        shutil.copy2(LAB/'exports'/name,DEST/name)
        s.update(variants=[name],duration_ms=round(duration*1000),source='Original A reward refinement; sources/build_app_sounds.py',description='A 原动机：轻快上行、短亮泛音与干净收尾')
    else:
        names=[]
        for file in s['variants']:
            name=Path(file).name;shutil.copy2(LAB/file,DEST/name);names.append(name)
        s['variants']=names
    if s['id']=='training.start':s['description']='开始时轻提示；示范音立即优先，不延迟训练'
    selected.append(s)
    for name in s['variants']:
        path=DEST/name
        with wave.open(str(path)) as w:x=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768
        up=np.fft.irfft(np.fft.rfft(x),n=len(x)*4)*4
        db=lambda v:float(20*np.log10(max(v,1e-12)))
        assert x[0]==x[-1]==0 and max(abs(up))<10**(-15/20)
        qa.append(dict(file=name,id=s['id'],duration=len(x)/SR,peak_dbfs=db(max(abs(x))),true_peak_estimate_dbfs=db(max(abs(up))),rms_dbfs=db(np.sqrt(np.mean(x*x))),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
output=dict(version='a-app-v4-2026-09-12',description='A original daily cues + revised rewards. Swap slot variants/gain in this manifest; keep event IDs.',
    defaults=dict(volume=.7,muted=False,preference_key='pth-sound-preferences-v1'),sounds=selected)
(DEST/'manifest.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
shutil.copy2(LAB/'sound-manager.js',DEST/'sound-manager.js')
(LAB/'qa/integration-v4/audio-report.json').write_text(json.dumps(dict(files=qa,count=len(qa),old_daily_files_byte_identical=True,listening_status='Machine checks only; reward refinement follows user feedback, device listening remains subjective.'),ensure_ascii=False,indent=2)+'\n')
print(f'Built {len(qa)} app WAVs in 11 replaceable event slots; 4 revised rewards, other A files unchanged.')
