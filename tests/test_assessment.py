from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
from urllib.parse import parse_qs, urlsplit
import wave

import numpy as np
import pytest

from pth_corpus import assessment as a


def wav(silent=False):
    pcm = np.zeros(16000, dtype='<i2') if silent else (np.sin(np.arange(16000)*.1)*8000).astype('<i2')
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed')); f.writeframes(pcm.tobytes())
    return out.getvalue()


def settings():
    return {'appid':'123','secret_id':'test-id','secret_key':'test-key','score_coeff':2,'limit_units':5}


def test_signature_uses_unescaped_text_and_encodes_final_query():
    url = urlsplit(a.signed_url(settings(), '新闻，真好！', 'test-voice'))
    q = {k:v[0] for k,v in parse_qs(url.query).items()}
    signature = q.pop('signature')
    text = url.netloc + url.path + '?' + '&'.join(f'{k}={q[k]}' for k in sorted(q))
    assert signature == base64.b64encode(hmac.new(b'test-key',text.encode(),hashlib.sha1).digest()).decode()
    assert q['rec_mode']=='1' and q['eval_mode']=='1'
    assert '新闻' not in url.query


def test_audio_and_mode_limits():
    assert a.validate_wav(wav()) == 1
    with pytest.raises(a.AssessmentError, match='没有检测到'):
        a.validate_wav(wav(True))
    with pytest.raises(a.AssessmentError):
        a.validate_wav(b'fake webm')
    assert [a.evaluation_mode('字'*n) for n in (1,2,30,31,120)] == [0,1,1,2,2]
    with pytest.raises(a.AssessmentError):
        a.evaluation_mode('字'*121)


def test_negative_unavailable_scores_and_missing_word_feedback():
    result = a.normalize_result({'SuggestedScore':-1,'PronAccuracy':90,'PronCompletion':.5,
        'Words':[{'ReferenceWord':'闻','PronAccuracy':-1,'MatchTag':2}]})
    assert result['score'] is None and result['accuracy']==90 and result['completion']==50
    assert result['words']==[{'text':'闻','accuracy':None,'tag':2}]


def test_all_unrecorded_characters_are_not_a_completed_reading():
    result=a.normalize_result({'SuggestedScore':0,'PronCompletion':0,
        'Words':[{'Word':'闻','Tag':4,'PronAccuracy':-1}]})
    assert result['status']=='no_speech'
    assert a.normalize_result({'PronCompletion':0,'Words':[]})['status']=='no_speech'


def test_two_service_instances_share_budget_and_corruption_fails_closed(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    services=[a.AssessmentService(tmp_path),a.AssessmentService(tmp_path)]
    def reserve(service):
        try:service.reserve(1,1);return 'reserved'
        except a.AssessmentError:return 'quota'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve,services))==['quota','reserved']
    assert services[0].units_used()==1
    path=tmp_path/'derived/assessment/usage.json';path.write_text('damaged')
    monkeypatch.setattr(services[0],'settings',settings)
    assert not services[0].status()['available']
    assert services[0].status()['remaining_test_units']==0


def test_final_frame_without_result_keeps_last_result(monkeypatch):
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def recv(self):return '{"code":0}'
        async def send(self,data):pass
        def __aiter__(self):
            async def messages():
                yield json.dumps({'code':0,'result':{'SuggestedScore':93,'Words':[]}})
                yield '{"code":0,"final":1}'
            return messages()
    monkeypatch.setattr(a,'connect',lambda *args,**kwargs:Socket())
    assert asyncio.run(a.evaluate(settings(),'新闻',wav()))['score']==93


def test_silence_and_duplicate_attempt_do_not_spend_twice(tmp_path, monkeypatch):
    service=a.AssessmentService(tmp_path)
    monkeypatch.setattr(service,'settings',settings)
    calls=[]
    async def provider(*args):calls.append(1);return {'status':'ok','score':95}
    monkeypatch.setattr(a,'evaluate',provider)
    async def run():
        with pytest.raises(a.AssessmentError):await service.assess('silence','新闻',wav(True))
        assert service.units_used()==0
        first=await service.assess('same-id','新闻',wav())
        assert await service.assess('same-id','新闻',wav())==first
        with pytest.raises(a.AssessmentError):await service.assess('same-id','另外',wav())
        return service.units_used()
    assert asyncio.run(run())==1 and len(calls)==1


def test_paragraph_budget_charged_before_send_and_error_cached(tmp_path,monkeypatch):
    service=a.AssessmentService(tmp_path); monkeypatch.setattr(service,'settings',settings)
    async def provider(*args):raise a.AssessmentError('unavailable','网络暂不可用')
    monkeypatch.setattr(a,'evaluate',provider)
    async def run():
        assert (await service.assess('first','字'*62,wav()))['status']=='unavailable'
        assert service.units_used()==4
        assert (await service.assess('first','字'*62,wav()))['status']=='unavailable'
        with pytest.raises(a.AssessmentError,match='额度'):await service.assess('second','字'*31,wav())
    asyncio.run(run())
