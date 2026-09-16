#!/usr/bin/env python3
"""A v2 celebration layer: warm major cadence, pickup + bloom + settle.
Additive original synthesis, deterministic RNG, mono compatible. Does not run or
change v1 generation, and never overwrites an original A/B WAV.
"""
from pathlib import Path
import json, wave, hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SR=44100; TAU=2*np.pi; rng=np.random.default_rng(2026091202)
def blank(d):return np.zeros(round(d*SR))
def env(x,attack=.005,release=.05):
    x=x.copy();a=min(len(x),round(attack*SR));r=min(len(x),round(release*SR))
    x[:a]*=np.sin(np.linspace(0,np.pi/2,a))**2;x[-r:]*=np.sin(np.linspace(np.pi/2,0,r))**2
    x[0]=x[-1]=0;return x
def add(y,x,at,g=1):
    start=round(at*SR);n=min(len(x),len(y)-start)
    if n>0:y[start:start+n]+=g*x[:n]
def mallet(f,d=.24):
    t=np.arange(round(d*SR))/SR
    ph=TAU*(f*t+.09*f*.006*(1-np.exp(-t/.006)))
    x=np.sin(ph)*np.exp(-t/.105)
    x+=.22*np.sin(2*ph)*np.exp(-t/.045)+.065*np.sin(2.76*ph)*np.exp(-t/.018)
    return env(x,.003,.032)
def pluck(f,d=.5):
    t=np.arange(round(d*SR))/SR
    # Round kalimba-like body, harmonic high modes decay much faster.
    x=sum(a*np.sin(TAU*f*k*t)*np.exp(-t/tau) for k,a,tau in [(1,1,.23),(2,.28,.105),(3,.13,.057),(4,.04,.027)])
    return env(x,.006,.08)
def felt_chord(freqs,d):
    t=np.arange(round(d*SR))/SR;x=np.zeros_like(t)
    for f in freqs:
        x+=(np.sin(TAU*f*t)+.20*np.sin(TAU*f*1.0018*t)+.12*np.sin(TAU*f*2*t))*np.exp(-t/.45)
    return env(x/np.sqrt(len(freqs)),.026,min(.24,d*.36))
def pulse(d=.16):
    t=np.arange(round(d*SR))/SR
    ph=TAU*(92*t+42*.022*(1-np.exp(-t/.022)))
    return env(np.sin(ph)*np.exp(-t/.045),.006,.04)
def sparkle(d):
    t=np.arange(round(d*SR))/SR
    x=sum(a*np.sin(TAU*f*t)*np.exp(-t/tau) for f,a,tau in [(1568,.6,.10),(2093,.2,.085),(2637,.08,.052)])
    return env(x,.008,.07)
def lift(d):
    t=np.arange(round(d*SR))/SR
    noise=np.convolve(rng.normal(0,1,len(t)),np.ones(33)/33,mode='same')
    phase=TAU*(440*t+330*t*t/d)
    x=.65*noise+.13*np.sin(phase)
    return env(x*(t/d)**1.7,.025,.035)
# Pickup accents lead to a definite C-major arrival. Every event has its own scale.
# (id, label, duration, same peak as A v1, landing, notes [onset, frequency, strength])
SPECS=[
 ('reward.arrive','奖励到账',.95,-19,.255,[(0,523.25,.6),(.085,659.25,.74),(.17,783.99,.85),(.255,1046.5,1.10)]),
 ('day.complete','今日三练',1.22,-18.5,.37,[(0,523.25,.52),(.085,659.25,.64),(.17,783.99,.78),(.27,987.77,.68),(.37,1046.5,1.10),(.53,1318.51,.40)]),
 ('artwork.complete','单件作品完成',1.80,-18.5,.60,[(0,392,.50),(.10,523.25,.57),(.20,659.25,.66),(.31,783.99,.75),(.42,1046.5,.90),(.60,1318.51,1.05),(.82,1174.66,.53),(.94,1046.5,.86)]),
 ('series.complete','系列集齐',2.25,-18,.78,[(0,392,.44),(.10,523.25,.52),(.20,659.25,.64),(.30,783.99,.74),(.405,1046.5,.83),(.51,1318.51,.92),(.62,1567.98,.72),(.78,2093,.63),(1.02,1567.98,.49),(1.15,1318.51,.63),(1.30,1046.5,1.03)]),
]
DESCRIPTIONS={
 'reward.arrive':'四颗木珠轻快跃起，最后一颗落在明亮和弦上。',
 'day.complete':'多一步向上推进，三练完成时亮开一个小笑容。',
 'artwork.complete':'短短蓄势后展开，带温暖低音和清亮收尾。',
 'series.complete':'更完整的上行与落稳，两次展开，留给真正的集齐。',
}
records=[];audio={}
for id,label,d,peak,landing,notes in SPECS:
    y=blank(d)
    for at,f,g in notes:
        add(y,mallet(f,min(.29,d-at)),at,.70*g)
        add(y,pluck(f,min(.48,d-at)),at,.23*g)
    # A subtle shared room gives physical body without a long ringing tail.
    dry=y.copy()
    for delay,g in [(.026,.075),(.043,.052),(.067,.027)]:add(y,dry,delay,g)
    add(y,lift(landing),0,.35 if 'complete' in id else .20)
    chord=[261.63,329.63,392,523.25]
    add(y,felt_chord(chord,d-landing),landing,.61)
    add(y,pulse(),landing,.31)
    add(y,sparkle(min(.38,d-landing)),landing,.16)
    if id in ['artwork.complete','series.complete']:
        at=.94 if id=='artwork.complete' else 1.30
        add(y,felt_chord([261.63,392,523.25,659.25],d-at),at,.38)
        add(y,pulse(),at,.17)
    if id=='series.complete':
        add(y,pluck(523.25,.48),.80,.20);add(y,sparkle(.5),1.30,.14)
    y=env(y,.003,.13)
    # Softly round coincident transients to keep the harmony present at the old peak.
    y=np.tanh(2.1*y/np.max(np.abs(y)))
    y=y/np.max(np.abs(y))*10**(peak/20)
    pcm=np.rint(y*32767).astype('<i2');name=f'a-lift-{id.replace(".","-")}-01.wav';p=ROOT/'exports'/name
    with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(SR);w.writeframes(pcm.tobytes())
    audio[id]=pcm.astype(float)/32768
    records.append({'id':id,'style':'a-lift','label':label,'description':DESCRIPTIONS[id],'duration_ms':round(d*1000),
      'gain':1,'peak_dbfs':peak,'bus':'celebration','priority':2,'cooldown_ms':round((d+.2)*1000),'variants':['exports/'+name],
      'default_enabled':True,'source':'原创程序合成；sources/generate_celebrations.py；seed 2026091202',
      'revision':'v2','compares_to_style':'a','design':{'landing_ms':round(landing*1000),'layers':['木珠／拨片上行动机','柔和大三和弦','短低音支撑','少量亮音与短空间'],'notes':notes}})
# A standalone four-event preview retains the same relative levels as the samples.
reel=blank(9.0)
for (id,*_),at in zip(SPECS,[.20,1.65,3.45,6.00]):add(reel,audio[id],at)
reel=env(reel,.003,.08);pcm=np.rint(reel*32767).astype('<i2');reel_name='a-lift-celebrations-preview.wav'
with wave.open(str(ROOT/'exports'/reel_name),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(SR);w.writeframes(pcm.tobytes())
p=ROOT/'manifest.json';m=json.loads(p.read_text())
m['version']='sound-lab-2026-09-12-v2';m['approved_base_style']='a';m['recommended_celebration_style']='a-lift'
m['styles']['a-lift']={'name':'奶油木珠 · 欢庆版','note':'A 音色延续，四种庆祝增强；待用户试听'}
m['sounds']=[s for s in m['sounds'] if s['style']!='a-lift']+records
m['reels']=[s for s in m['reels'] if s['style']!='a-lift']+[{'style':'a-lift','label':'A 欢庆版 · 四段预览','file':'exports/'+reel_name}]
p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'generated':[r['variants'][0] for r in records]+['exports/'+reel_name],'originals':'unchanged'},ensure_ascii=False))
