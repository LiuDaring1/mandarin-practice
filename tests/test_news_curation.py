import importlib.util
import json
from pathlib import Path
import wave

import numpy as np
import pytest


def module(monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts';monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('news_curate_test',scripts/'curate_news_release.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_local_match_accepts_timbre_change_but_rejects_silence(monkeypatch):
    m=module(monkeypatch);t=np.arange(64000)/16000
    env=.1+.08*np.sin(2*np.pi*2.3*t)
    x=(env*np.sin(2*np.pi*220*t)).astype(np.float32)
    y=(env*np.sin(2*np.pi*370*t)).astype(np.float32)
    assert m.local_match(x,y)>.98
    assert m.local_match(x,np.zeros_like(y))==0
    clip={'start':10,'end':15};timing={'median_lag_ms':100,'windows':[{'source_start':12,'correlation':.64,'lag_ms':100}]}
    assert m.held_windows(clip,timing)==[12]
    assert not m.held_windows({'start':21,'end':25},timing)


def test_only_paired_clean_sentences_publish_and_evidence_is_bound(tmp_path,monkeypatch):
    m=module(monkeypatch);data=tmp_path/'data';out=data/'derived/news-sentence-v1';out.mkdir(parents=True)
    def write(path,pcm):
        path.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as f:f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(pcm.astype('<i2').tobytes())
    t=np.arange(48000)/16000;env=.2+.1*np.sin(2*np.pi*2.7*t)
    source=(env*np.sin(2*np.pi*220*t)*30000).astype('<i2');converted=(env*np.sin(2*np.pi*350*t)*30000).astype('<i2')
    selected=[];clips=[]
    for i in range(3):
        sid=f'news-2649000000-1-{i+1:04d}';relative=f'derived/news-sentence-v1/clips/{sid}.wav';path=data/relative;write(path,source)
        selected.append({'sentence_id':sid,'original_relative_path':relative,'clip_sha256':m.vc.digest(path),'text':'完整新闻句子。'})
        clips.append({'id':sid,'relative_path':relative,'start':i*4,'end':i*4+3})
    (out/'selection.json').write_text(json.dumps(selected))
    packet=data/'packet.wav';write(packet,np.concatenate([np.r_[source,np.zeros(16000,dtype='<i2')]]*3))
    for voice,sex in [('news-female','female'),('news-male','male')]:
        batch=data/f'derived/voice-conversion/news-sentences-{sex}-v1';batch.mkdir(parents=True)
        export=batch/'exports/news-001.wav';write(export,np.concatenate([np.r_[converted,np.zeros(16000,dtype='<i2')]]*3))
        job={'id':'news-001','kind':'sentence','voice':voice,'source':str(packet),'source_sha256':m.vc.digest(packet),'export_name':export.name,'clips':clips}
        (batch/'queue.json').write_text(json.dumps({'jobs':[job]}))
        checks=[{'id':c['id'],'new_loss':i==1 and sex=='male','source_silent':False} for i,c in enumerate(clips)]
        report={'job':'news-001','export_sha256':m.vc.digest(export),'file_integrity':True,'untreated_input_suspected':False,
            'timing':{'median_lag_ms':0,'windows':[{'source_start':i*.2,'correlation':.99,'lag_ms':0} for i in range(11)]},'clips':checks}
        m.vc.write_json(batch/'reports/news-001__conversion-integrity.json',report)
    rows,manifests=m.curate(data,minimum=2)
    assert [r['sentence_id'] for r in rows]==[selected[0]['sentence_id'],selected[2]['sentence_id']]
    assert set(manifests['news-female']['clips'])==set(manifests['news-male']['clips'])
    m.verify(data,manifests['news-female'])
    path=data/selected[0]['original_relative_path'];path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Original clip changed'):m.verify(data,manifests['news-female'])
