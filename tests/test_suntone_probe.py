"""Offline protocol, privacy and request-budget checks; never calls a provider."""
import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import pytest

spec=importlib.util.spec_from_file_location('suntone_probe',Path(__file__).parents[1]/'scripts/suntone_probe.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_signature():
 c={'api_key':'fake-key','api_secret':'fake-secret','app_id':'fake-app'}
 date='Fri, 23 Oct 2026 00:00:00 GMT'
 q=parse_qs(urlsplit(m.signed_url(c,date)).query)
 auth=base64.b64decode(q['authorization'][0]).decode()
 sig=base64.b64encode(hmac.new(b'fake-secret',f'host: {m.HOST}\ndate: {date}\nGET {m.PATH} HTTP/1.1'.encode(),hashlib.sha256).digest()).decode()
 assert f'signature="{sig}"' in auth
 assert q['date']==[date]

@pytest.mark.parametrize('size',[2,100,1280,1281,5000])
def test_frames_reassemble_nonempty_end(size):
 audio=b'x'*size;packets=list(m.frames({'app_id':'fake'},m.parameters('心'),audio))
 assert packets[0]['header']['status']==0
 assert packets[-1]['header']['status']==2
 assert b''.join(base64.b64decode(x['payload']['data']['audio']) for x in packets)==audio
 assert all(x['payload']['data']['audio'] for x in packets)
 assert all(x['header']['status']==x['payload']['data']['status'] for x in packets)

def test_public_report_excludes_identifiers():
 raw={'status':'ok','payload':{'applicationId':'secret','audioUrl':'https://private','result':{'overall':80,'secret':'private','words':[{'word':'心','audioUrl':'private','phonemes':[{'phone':'in','pronunciation':60,'private':'secret'}]}]}}}
 out=json.dumps(m.public_result(raw))
 assert 'secret' not in out and 'private' not in out and 'audioUrl' not in out
 assert 'pronunciation' in out

def test_cache_and_budget(tmp_path,monkeypatch):
 m.private_json(tmp_path/'config.json',{'app_id':'fake'})
 audio=tmp_path/'a.mp3';audio.write_bytes(b'fake-mp3')
 calls=[]
 async def fake(*args):calls.append(1);return {'status':'ok','payload':{'result':{}}}
 monkeypatch.setattr(m,'evaluate',fake)
 async def run():
  with pytest.raises(RuntimeError,match='allow-paid'):await m.Probe(tmp_path).call(audio,'心')
  p=m.Probe(tmp_path,allow_paid=True,max_calls=1)
  await p.call(audio,'心');await p.call(audio,'心')
  with pytest.raises(RuntimeError,match='cap'):await p.call(audio,'星')
 asyncio.run(run());assert len(calls)==1
 assert (tmp_path/'config.json').stat().st_mode&0o777==0o600

def test_error_never_logs_signed_url(tmp_path,monkeypatch):
 m.private_json(tmp_path/'config.json',{})
 audio=tmp_path/'a.mp3';audio.write_bytes(b'fake-mp3')
 async def fake(*args):raise RuntimeError('wss://private?authorization=secret')
 monkeypatch.setattr(m,'evaluate',fake)
 r=asyncio.run(m.Probe(tmp_path,allow_paid=True).call(audio,'心'))
 assert r=={'status':'transport_error','error_type':'RuntimeError'}

def test_concurrent_probe_rejected(tmp_path):
 fd=m.os.open(tmp_path/'probe.lock',m.os.O_CREAT|m.os.O_RDWR,0o600)
 try:
  m.fcntl.flock(fd,m.fcntl.LOCK_EX|m.fcntl.LOCK_NB)
  with pytest.raises(RuntimeError,match='Another probe'):
   asyncio.run(m.Probe(tmp_path,allow_paid=True).call(tmp_path/'unused','心'))
 finally:m.os.close(fd)
