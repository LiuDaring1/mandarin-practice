import importlib.util
import json
from pathlib import Path
import wave

import numpy as np
import pytest


def test_incremental_packets_preserve_existing_sources_and_exports(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('news_release_test',scripts/'release_news_sentences.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=tmp_path/'data';out=data/'derived/news-sentence-v1';voices=data/'derived/voice-conversion'
    out.mkdir(parents=True)
    monkeypatch.setattr(module,'DATA',data);monkeypatch.setattr(module,'OUT',out);monkeypatch.setattr(module,'VOICES',voices)
    rows=[]
    for i in range(30):
        sid=f'news-{2649000000+i}-1-0001';relative=f'derived/news-sentence-v1/clips/{sid}.wav'
        audio=data/relative;audio.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(audio),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes((np.sin(np.arange(16000)*.1)*8000).astype('<i2').tobytes())
        rows.append({'sentence_id':sid,'article_id':sid.rsplit('-',1)[0],'text':'这是一条完整而清晰的新闻练习句子'+chr(0x4e00+i)+'。',
                     'confidence':.99,'nasal_count':8,'clip_duration':1,'original_relative_path':relative,
                     'clip_sha256':module.vc.digest(audio)})
    monkeypatch.setattr(module,'all_candidates',lambda:rows)
    module.prepare(10)
    female=voices/'news-sentences-female-v1'
    first=json.loads((female/'queue.json').read_text())['jobs'][0]
    source_hash=module.vc.digest(Path(first['source']))
    export=female/'exports/group-002__news-female.wav';export.write_bytes(b'previous GUI export must survive')
    prefix=json.loads((out/'selection.json').read_text())
    module.prepare(20)
    current=json.loads((female/'queue.json').read_text())['jobs']
    assert len(current)==2 and current[0]==first
    assert module.vc.digest(Path(first['source']))==source_hash
    assert export.read_bytes()==b'previous GUI export must survive'
    assert json.loads((out/'selection.json').read_text())[:10]==prefix
    groups=json.loads((female/'groups/plan.json').read_text())['groups']
    assert [g['id'] for g in groups]==['group-002','group-003']
    assert all(j['duration']<480 for j in current)
    male=json.loads((voices/'news-sentences-male-v1/queue.json').read_text())['jobs']
    assert [j['clips'] for j in male]==[j['clips'] for j in current]
    assert all(j['voice']=='news-male' for j in male)
    with pytest.raises(ValueError,match='shrink'):module.prepare(9)
