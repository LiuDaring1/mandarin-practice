import asyncio
import hashlib
import json
import stat

import pytest

import recover_same_tail_specificity as recovery


def test_durable_json_replaces_atomically_with_private_permissions(tmp_path):
    path=tmp_path/'sub/result.json'
    recovery.durable_json(path,{'n':1})
    recovery.durable_json(path,{'n':2})
    assert json.loads(path.read_text())=={'n':2}
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert not path.with_suffix('.durable-tmp').exists()


def test_mirror_reserves_on_internal_disk_before_network_and_saves_response(tmp_path,monkeypatch):
    mirror=tmp_path/'internal';provider=tmp_path/'external';provider.mkdir()
    monkeypatch.setattr(recovery,'MIRROR',mirror)
    params={'test':'no credential'};audio=b'fake protocol test'
    key=hashlib.sha256(recovery.IseProbe.cache_namespace+json.dumps(params,sort_keys=True,ensure_ascii=False).encode()+audio).hexdigest()
    (provider/'requests.json').write_text(json.dumps(['before',key]))
    result={'status':'ok','xml':'<test/>'}
    async def evaluate(self,config,received_params,received_audio):
        assert json.loads((mirror/'requests.json').read_text())==['before',key]
        assert received_params==params and received_audio==audio
        assert not (mirror/'cache'/(key+'.json')).exists()
        return result
    monkeypatch.setattr(recovery.IseProbe,'evaluate',evaluate)
    probe=recovery.MirroredIseProbe(provider)
    assert asyncio.run(probe.evaluate({},params,audio))==result
    assert json.loads((mirror/'cache'/(key+'.json')).read_text())==result


def test_unreserved_request_never_reaches_network(tmp_path,monkeypatch):
    monkeypatch.setattr(recovery,'MIRROR',tmp_path/'internal')
    (tmp_path/'requests.json').write_text('[]')
    async def forbidden(*args):raise AssertionError('Network was reached')
    monkeypatch.setattr(recovery.IseProbe,'evaluate',forbidden)
    with pytest.raises(ValueError,match='not reserved'):
        asyncio.run(recovery.MirroredIseProbe(tmp_path).evaluate({}, {},b'fake'))


@pytest.mark.parametrize('kind',['extra','removed','fabricated_cache'])
def test_recovered_reader_rejects_changed_missing_denominator(kind,monkeypatch):
    monkeypatch.setattr(recovery,'checked',lambda:{'never_resend_keys':['a','b']})
    monkeypatch.setattr(recovery.original,'checked_stage',lambda name:None)
    monkeypatch.setattr(recovery.original.paired,'sha',lambda path:'digest')
    value={'result':{'status':'interrupted_missing_result'},'cache_sha256':None,'disk_recovery_plan_sha256':'digest'}
    results={'a':dict(value),'b':dict(value)}
    if kind=='extra':results['c']=dict(value)
    elif kind=='removed':del results['b']
    else:results['a']['cache_sha256']='fabricated'
    monkeypatch.setattr(recovery.original,'read',lambda path:{'complete':True,'stage_plan_sha256':'digest',
        'disk_recovery_plan_sha256':'digest','results':results})
    with pytest.raises(ValueError):recovery.recovered_plain('plain')
