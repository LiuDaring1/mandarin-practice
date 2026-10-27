import asyncio
import json

import pytest

import resume_matrix_validation as recovery


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def test_partition_never_retries_reserved_without_response(tmp_path):
    dump(tmp_path/'done.json',{'status':'ok'})
    plan={'ledger_prefix':['old'],'new_request_keys':['done','uncertain','new'],
          'requests':[{'key':k} for k in ('done','uncertain','new')]}
    assert recovery.partition(plan,['old','done','uncertain'],tmp_path)=={
        'completed_keys':['done'],'unresolved_keys':['uncertain'],'remaining_keys':['new']}
    with pytest.raises(ValueError):recovery.partition(plan,['changed'],tmp_path)


def test_publication_refuses_different_existing_response(tmp_path):
    a=tmp_path/'source';b=tmp_path/'destination';a.write_text('real response')
    recovery.publish_file(a,b);recovery.publish_file(a,b)
    a.write_text('changed response')
    with pytest.raises(ValueError):recovery.publish_file(a,b)
    assert b.read_text()=='real response'


def test_resume_uses_cache_sends_only_unsent_and_keeps_unknown(tmp_path,monkeypatch):
    run=recovery.run;folder=tmp_path/'batch';mirror=tmp_path/'mirror';provider=tmp_path/'external-provider'
    monkeypatch.setattr(run,'FOLDER',folder);monkeypatch.setattr(run,'MIRROR',mirror);monkeypatch.setattr(run,'PROVIDER',provider)
    ledger=['old','done','uncertain'];requests=[{'key':k,'audio':k,'reference':'文','core':'read_sentence'} for k in ('done','uncertain','new')]
    plan={'requests':requests,'ledger_prefix':['old'],'new_request_keys':['done','uncertain','new'],'maximum_total_attempts':4}
    resume={'ledger_checkpoint':ledger,'unresolved_keys':['uncertain']}
    dump(folder/'api-plan.json',plan);dump(mirror/'resume-plan.json',resume)
    dump(provider/'requests.json',ledger);dump(mirror/'provider/requests.json',ledger)
    dump(mirror/'provider/cache/done.json',{'status':'ok'})
    monkeypatch.setattr(recovery,'checked',lambda:(plan,resume));monkeypatch.setattr(recovery,'public_result',lambda value:value)
    sent=[]
    class Probe:
        def __init__(self,directory,**kwargs):
            self.directory=directory;assert kwargs['max_calls']==4 and kwargs['allow_paid']
        async def call(self,audio,*args,**kwargs):
            cache=self.directory/'cache'/(audio+'.json')
            if cache.exists():return json.loads(cache.read_text())
            current=json.loads((self.directory/'requests.json').read_text())
            assert audio not in current;sent.append(audio);current.append(audio)
            dump(self.directory/'requests.json',current);dump(cache,{'status':'ok'})
            return {'status':'ok'}
    monkeypatch.setattr(recovery,'MirroredIseProbe',Probe)
    asyncio.run(recovery.api(True))
    result=json.loads((folder/'api-result.json').read_text())
    assert sent==['new']
    assert result['new_reservations']==3 and result['confirmed_new_responses']==2
    assert result['unresolved_keys']==['uncertain'] and result['cumulative_reservations']==4
    assert set(result['results'])=={'done','new'}
    assert not (provider/'cache/uncertain.json').exists()
    assert json.loads((provider/'requests.json').read_text())==['old','done','uncertain','new']
