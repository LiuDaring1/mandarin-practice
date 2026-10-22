import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np


def preparation_module():
    spec=importlib.util.spec_from_file_location('news_preparation',Path(__file__).resolve().parents[1]/'scripts/prepare_news_sentences.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_extract_excludes_heading_and_annotation_and_keeps_spoken_digits():
    module=preparation_module()
    title,body,sentences=module.extract_article({'article_id':'2649371281-1',
        'text':'Preview\n原文试读\n\n新闻标题\n\n今年有2026名同学参加校园公益行动。\n\n新闻摘自央视\n符号标注：不入库。'})
    assert title=='新闻标题'
    assert body=='今年有2026名同学参加校园公益行动。'
    assert len(sentences)==1 and '2026' in sentences[0]['text']
    assert '标注' not in body


def test_independent_timestamps_cut_entire_sentence_and_reject_missing_tail(tmp_path,monkeypatch):
    module=preparation_module();monkeypatch.setattr(module,'RAW',tmp_path);monkeypatch.setattr(module,'OUT',tmp_path/'out')
    body='清晨的阳光洒满公园，人们在林间慢慢散步。城市中的公共文化空间，为居民提供更加丰富的精神生活。'
    chars=[ch for ch in body if module.is_hanzi(ch)]
    words=[{'word':ch,'start':.8+i*.24,'end':.8+(i+1)*.24} for i,ch in enumerate(chars)]
    source=tmp_path/'reference.wav'
    with wave.open(str(source),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'))
        f.writeframes((np.sin(np.arange(16000*15)*.1)*8000).astype('<i2').tobytes())
    raw=tmp_path/'2649371281-1.json'
    raw.write_text(json.dumps({'article_id':'2649371281-1','url':'https://mp.weixin.qq.com/s?mid=2649371281',
        'text':'原文试读\n\n公园新闻\n\n'+body+'\n\n新闻摘自央视',
        'audio_files':[{'file':'reference.wav'}]}))
    class Aligner:
        def generate(self,**kwargs):
            return SimpleNamespace(items=[SimpleNamespace(text=w['word'],start_time=w['start'],end_time=w['end']) for w in words],segments=words)
    class Whisper:
        missing=False
        def generate(self,*args,**kwargs):
            return SimpleNamespace(segments=[{'start':0,'end':14,'text':body,'words':words[:-1] if self.missing else words}])
    whisper=Whisper();result=module.process(raw,Aligner(),whisper)
    assert len(result['sentences'])==2
    for row in result['sentences']:
        assert row['src_start']<=row['first_char_start'] and row['src_end']>=row['last_char_end']
        assert row['clip_duration']>3 and Path(tmp_path/'out'/row['clip_rel']).exists()
    whisper.missing=True
    result=module.process(raw,Aligner(),whisper)
    assert len(result['sentences'])==1 and len(result['holds'])==1
