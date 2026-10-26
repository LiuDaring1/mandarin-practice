"""Offline checks for the specific ISE dialect; no external requests."""
import base64
import asyncio
import io
from pathlib import Path
import sys
import wave
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import ise_probe as m

def wav_bytes(rate=16000,frames=2000):
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b'\x01\x00'*frames)
    return b.getvalue()

def test_error_fields_enabled_together():
    p=m.parameters('心')
    assert p['text']=='\ufeff心' and p['ttp_skip'] is True
    assert p['category']=='read_syllable' and p['ent']=='cn_vip'
    assert (p['ise_unite'],p['rst'])==('1','entirety')
    assert 'syll_phone_err_msg' in p['extra_ability']

@pytest.mark.parametrize('length',[2,640,641,2000])
def test_pcm_packets_and_header_removed(length):
    packets=list(m.frames({'app_id':'fake'},m.parameters('心'),wav_bytes(frames=length)))
    assert packets[0]['business']['cmd']=='ssb' and packets[0]['data']['status']==0
    chunks=packets[1:]
    assert chunks[0]['business']['aus']==1
    assert chunks[-1]['business']['aus']==4 and chunks[-1]['data']['status']==2
    assert all(c['data']['status']==1 for c in chunks[:-1])
    assert b''.join(base64.b64decode(c['data']['data']) for c in chunks)==b'\x01\x00'*length

def test_reject_wrong_sample_rate():
    with pytest.raises(ValueError,match='16kHz'):
        list(m.frames({'app_id':'fake'},m.parameters('心'),wav_bytes(rate=8000)))


def test_long_audio_deadline_covers_streaming_and_stays_bounded():
    assert m.request_timeout(50)==45
    assert 80<m.request_timeout(1601)<100  # 64 s upload, result overhead
    assert 180<m.request_timeout(4501)<210
    with pytest.raises(ValueError,match='packet count'):
        m.request_timeout(4502)


def test_oversized_audio_is_rejected_before_ledger_reservation(tmp_path):
    audio=tmp_path/'too-long.wav';audio.write_bytes(wav_bytes(frames=16000*181))
    probe=m.IseProbe(tmp_path/'probe',allow_paid=True,max_calls=1)
    with pytest.raises(ValueError,match='180 seconds'):
        asyncio.run(probe.call(audio,'心'))
    assert not (tmp_path/'probe/requests.json').exists()


def test_chapter_rejection_is_preserved_for_target_mapping():
    result=m.public_result({'status':'ok','xml':'<xml><read_chapter is_rejected="true" except_info="28673"/></xml>'})
    assert result['nodes'][0]['tag']=='read_chapter'
    assert m.target_at(result,'心',0)['state']=='rejected'

def test_xml_error_fields_and_privacy():
    raw={'status':'ok','xml':'<xml sid="private"><read_syllable total_score="75"><word content="心"><phone content="in" is_yun="1" perr_msg="1" dp_message="128" perr_level_msg="2"/></word></read_syllable></xml>'}
    r=m.public_result(raw)
    assert 'private' not in str(r)
    phone=r['nodes'][-1]
    assert phone['perr_msg']=='1' and phone['dp_message']=='128'
    assert phone['is_yun']=='1' and phone['perr_level_msg']=='2'

def test_provider_error_message_not_public():
    assert m.public_result({'status':'provider_error','code':11200,'message':'private'})=={'status':'provider_error','code':11200}


def test_probe_defaults_to_chinese_syllable(tmp_path,monkeypatch):
    from suntone_probe import private_json
    private_json(tmp_path/'config.json',{'app_id':'fake'})
    wav=tmp_path/'input.wav';wav.write_bytes(wav_bytes())
    captured=[]
    async def fake(config,params,audio):
        captured.append(params);return {'status':'ok','xml':'<xml/>'}
    monkeypatch.setattr(m,'evaluate',fake)
    asyncio.run(m.IseProbe(tmp_path,allow_paid=True).call(wav,'心'))
    assert captured[0]['category']=='read_syllable'
