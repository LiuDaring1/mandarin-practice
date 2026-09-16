#!/usr/bin/env python3
"""Original modal / elastic synthesis, deterministic seed; no imported SFX.
Build dependency: NumPy. Runtime deliverables: mono PCM16 WAV + JSON, no packages.
"""
from pathlib import Path
import hashlib, json, math, wave
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SR = 44100
TAU = 2 * np.pi
rng = np.random.default_rng(20260912)

def blank(seconds): return np.zeros(round(seconds * SR), dtype=np.float64)

def shape(y, attack=.004, release=.016):
    y = y.copy()
    a, r = min(len(y), round(attack*SR)), min(len(y), round(release*SR))
    y[:a] *= np.sin(np.linspace(0,np.pi/2,a)) ** 2
    y[-r:] *= np.sin(np.linspace(np.pi/2,0,r)) ** 2
    y[0] = y[-1] = 0
    return y

def hit(freq=660, dur=.075, style='wood'):
    t = np.arange(round(dur*SR))/SR
    if style == 'wood':
        # Damped inharmonic modes, a little pitch settling and a soft felt contact.
        ph = TAU * (freq*t + freq*.12*.006*(1-np.exp(-t/.006)))
        y = np.sin(ph)*np.exp(-t/(dur*.29))
        y += .26*np.sin(1.48*ph)*np.exp(-t/(dur*.16))
        y += .10*np.sin(2.76*ph)*np.exp(-t/(dur*.10))
        noise = np.convolve(rng.normal(0,1,len(t)), np.ones(19)/19, mode='same')
        y += .10*noise*np.exp(-t/.007)
    else:
        ph = TAU*(freq*t + freq*.65*.014*(1-np.exp(-t/.014)))
        y = np.sin(ph + .35*np.sin(TAU*freq*.5*t)*np.exp(-t/.025))*np.exp(-t/(dur*.34))
        y += .10*np.sin(2*ph)*np.exp(-t/.018)
    return shape(y)

def note(freq, dur=.32):
    t=np.arange(round(dur*SR))/SR
    y=(np.sin(TAU*freq*t)+.17*np.sin(TAU*freq*2*t)+.04*np.sin(TAU*freq*3*t))*np.exp(-t/(dur*.23))
    return shape(y,.008,.05)

def add(dst,src,offset=0,gain=1):
    at=round(offset*SR); n=min(len(src),len(dst)-at)
    if n>0: dst[at:at+n]+=src[:n]*gain

def chord_sequence(duration, notes, style='wood'):
    y=blank(duration)
    for at,f,d,g in notes:
        add(y,hit(f,d,style),at,g)
        add(y,note(f*.5,min(d*1.5,duration-at)),at,.16*g)
    return shape(y,.004,.05)

specs=[
 ('ui.confirm','确认 / 切换',.078,-23,'interaction',90,'短木珠轻触，只确认明确操作'),
 ('training.start','开始训练',.28,-21,'feedback',400,'轻抬一步，播完再进入示范'),
 ('follow.ready','轮到你跟读（可选）',.10,-28,'interaction',500,'中性单颗，默认关闭，不代表发音判断'),
 ('answer.correct','辨音答对',.22,-20,'feedback',220,'短双珠，同一方向的小肯定'),
 ('answer.retry','辨音答错',.20,-24,'feedback',250,'低而柔的双触，无惩罚性警报'),
 ('reward.arrive','结算 / 奖励到账',.65,-19,'celebration',1200,'三颗舒展，所有到账合并一次'),
 ('day.complete','今日三练达成',.94,-18.5,'celebration',1500,'在到账动机上多一个柔亮收尾'),
 ('bead.place','拼入一颗',.066,-25,'bead',100,'六个物理落珠变体，限流、不排队'),
 ('artwork.fuse','熨烫 / 融合',1.80,-27,'texture',1900,'柔软摩擦与共鸣，淡入淡出贴合动画'),
 ('artwork.complete','单件作品完成',1.20,-18.5,'celebration',1500,'珠子落稳后绽放，尾音干净'),
 ('series.complete','系列集齐',1.65,-18,'celebration',2000,'同一家族加一层和声，只实际集齐时用'),
]

def synth(id,duration,style,variant=0):
    if id=='ui.confirm': return hit(620 if style=='wood' else 720,duration,style)
    if id=='follow.ready': return hit(510,duration,style)
    if id=='bead.place': return hit([760,804,724,838,778,746][variant],duration,style)
    if id=='artwork.fuse':
        t=np.arange(round(duration*SR))/SR
        n=np.convolve(rng.normal(0,1,len(t)),np.ones(91)/91,mode='same')
        y=.46*n*(.7+.15*np.cos(TAU*1.2*t))
        y+=.07*np.sin(TAU*(240*t+16*t*t))+ .028*np.sin(TAU*480*t)
        return shape(y*np.sin(np.pi*t/duration)**.8,.10,.22)
    sequences={
      'training.start':[(0,523,.18,1),(.095,659,.18,.65)],
      'answer.correct':[(0,659,.14,.75),(.070,880,.15,1)],
      'answer.retry':[(0,466,.14,1),(.065,440,.135,.58)],
      'reward.arrive':[(0,523,.26,.82),(.125,659,.30,.78),(.275,880,.37,1)],
      'day.complete':[(0,523,.28,.82),(.13,659,.33,.8),(.28,880,.38,1),(.49,1047,.45,.52)],
      'artwork.complete':[(0,523,.33,.8),(.16,659,.39,.7),(.34,880,.45,1),(.57,1047,.58,.5)],
      'series.complete':[(0,523,.32,.8),(.16,659,.38,.7),(.34,880,.44,.95),(.58,1047,.54,.55),(.84,1318,.68,.4),(.84,659,.7,.25)],
    }
    return chord_sequence(duration,sequences[id],style)

sounds=[]; memory={}; qa=[]
def export(id,y,db,group,variant):
    y=shape(y,.002,.008)
    y=y/(np.max(np.abs(y)) or 1)*10**(db/20)
    pcm=np.rint(y*32767).astype('<i2')
    filename=f'{group}-{id.replace(".","-")}-{variant+1:02d}.wav'
    p=ROOT/'exports'/filename
    with wave.open(str(p),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(SR);f.writeframes(pcm.tobytes())
    memory[(group,id,variant)]=pcm.astype(float)/32768
    qa.append({'file':filename,'duration_ms':round(len(y)/SR*1000,2),'sample_peak_dbfs':round(20*np.log10(np.max(np.abs(pcm))/32768),2),
               'rms_dbfs':round(20*np.log10(np.sqrt(np.mean((pcm.astype(float)/32768)**2)))),
               'first_sample':int(pcm[0]),'last_sample':int(pcm[-1]),'clipped_samples':int((np.abs(pcm.astype(int))>=32767).sum()),
               'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return 'exports/'+filename

for group,style in [('a','wood'),('b','bubble')]:
    for id,label,dur,peak,bus,cooldown,desc in specs:
        if group=='b' and id not in ['ui.confirm','answer.correct','bead.place','artwork.complete']: continue
        variants=6 if id=='bead.place' and group=='a' else 3 if id=='bead.place' else 1
        files=[export(id,synth(id,dur,style,i),peak,group,i) for i in range(variants)]
        sounds.append({'id':id,'style':group,'label':label,'description':desc,'duration_ms':round(dur*1000),'gain':1,
          'peak_dbfs':peak,'bus':bus,'priority':{'interaction':1,'bead':1,'texture':1,'feedback':3,'celebration':2}[bus],
          'cooldown_ms':cooldown,'variants':files,'default_enabled':id!='follow.ready','source':'原创程序合成；sources/generate.py；seed 20260912'})
# Freeze representative legacy oscillator for a factual A/B reference (old source used Math.random).
t=np.arange(round(.060*SR))/SR
legacy=2/np.pi*np.arcsin(np.sin(TAU*1600*t)) * .035*np.exp(np.log(.0001/.035)*np.minimum(t,.05)/.05)
legacy_file=export('bead.legacy',legacy,-29.2,'legacy',0)
sounds.append({'id':'bead.legacy','style':'legacy','label':'原有拼豆音（参照）','description':'原三角波逻辑固定 1600 Hz 的代表样本；加微淡入淡出，非逐次随机录音',
 'duration_ms':60,'gain':1,'peak_dbfs':-29.2,'bus':'bead','priority':1,'cooldown_ms':70,'variants':[legacy_file],'default_enabled':True,'source':'当前 app.js playPlaceTick 的代表性离线复刻'})
# Portable audio reels: short comparisons with space; not played in manager.
reels=[]
for group in ['a','b']:
    reel=blank(5.8)
    for id,at in [('ui.confirm',.30),('answer.correct',1.10),('bead.place',2.05),('artwork.complete',3.0)]: add(reel,memory[(group,id,0)],at)
    file=export('comparison',reel,-18.5,group,0)
    reels.append({'style':group,'label':('奶油木珠' if group=='a' else '软糖气泡')+' · 四声预览','file':file})

scenes=[
 ['按钮确认 / 选项切换','独立音效','ui.confirm','仅明确确认；前后鼻选项用完全相同的声音'],
 ['普通导航 / 浏览历史 / 作品墙','保持安静',None,'高频浏览无须附加声响'],
 ['开始字词 / 句子 / 辨音','独立音效','training.start','一次短起步；示范要开始时立即让路'],
 ['示范结束 → 进入跟读','独立音效','follow.ready','可选，默认关闭；示范 ended 后留 120 ms 空隙'],
 ['跟读每秒 / 计时结束','保持安静',None,'只有计时，没有发音评测，不能播放答对音'],
 ['辨音整词全对','独立音效','answer.correct','服务器真实判题结果，每整词一次'],
 ['辨音有错 / 连续有错','独立音效','answer.retry','每整词一次，连错不加重音量或警报'],
 ['趁热巩固 / 跨天复习开始','复用音效','training.start','同为起步，无需新增一种声音'],
 ['巩固 / 复习正误','复用音效','answer.correct / answer.retry','沿用实际判题语义'],
 ['训练结算 + 基础奖励 + 复习奖励','独立音效','reward.arrive','实际到账才响，同一结算合并一次'],
 ['今日三练完成','独立音效','day.complete','当次真的新达成，替代普通到账音'],
 ['单颗拼入','独立音效','bead.place','六个变体轮换，继承现有拼入反馈职责'],
 ['按住连续拼入','复用音效','bead.place','只由实际拼入事件触发，最多 10 次/秒，松手终止'],
 ['熨烫 / 融合','独立音效','artwork.fuse','1.8 秒单次纹理，关闭弹层就结束'],
 ['单件作品完成','独立音效','artwork.complete','只在首次完成后显示成品时触发'],
 ['系列集齐','独立音效','series.complete','替代该次单件完成音，不叠放两段庆祝'],
 ['暂停 / 恢复 / 退出 / 取消','保持安静',None,'让用户可以立即安静下来'],
 ['加载中 / 网络失败 / 音效不可用','保持安静',None,'文字反馈即可，错误不应制造更多噪声'],
 ['示范音频 / 标准视频播放期间','保持安静',None,'教学最高优先，全部音效淡出且丢弃新事件'],
]
manifest={'version':'sound-lab-2026-09-12-v1','sample_rate':SR,'format':'mono PCM16 WAV','recommended_style':'a',
 'styles':{'a':{'name':'奶油木珠','note':'推荐 · 温暖、短促、轻实物触感'},'b':{'name':'软糖气泡','note':'对比 · 更多弹性滑音，四个关键声音'}},
 'defaults':{'volume':.7,'muted':False,'max_voices':4,'preference_key':'pth-sound-lab-preferences-v1'},
 'sounds':sounds,'reels':reels,'scenes':[dict(zip(['scene','strategy','sound','reason'],r)) for r in scenes],
 'teaching_fixture':{'url':'/teaching.wav','note':'只读本地既有语料，非本任务原创；仅用于示范优先衔接模拟'}}
(ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(ROOT/'qa/audio-report.json').write_text(json.dumps({'sample_rate':SR,'files':qa,'listening_status':'机器检查；耳机和手机外放人耳听检待用户试听'},ensure_ascii=False,indent=2)+'\n')
print(f'Generated {len(qa)} WAV files, {len(sounds)} sound definitions. Total {sum(p.stat().st_size for p in (ROOT/"exports").glob("*.wav")):,} bytes.')
