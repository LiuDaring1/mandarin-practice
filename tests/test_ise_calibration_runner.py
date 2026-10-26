import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import run_ise_calibration as runner


def setup_batch(tmp_path, monkeypatch, audio_ids, continue_on_unavailable):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path/'data/derived/ise-validation'
    directory.mkdir(parents=True)
    (directory/'requests.json').write_text('[]')
    cases = [{'id':str(i), 'audio':audio, 'reference':'人', 'position':0, 'core':'read_syllable'}
             for i,audio in enumerate(audio_ids)]
    source = tmp_path/'input.json'
    source.write_text(json.dumps({'cases':cases}))
    calls = []

    class Probe:
        def __init__(self, path, *, allow_paid, max_calls):
            assert not allow_paid
            assert max_calls == 100

        async def call(self, audio, *args, **kwargs):
            calls.append(audio)
            return {'status':'transport_error','error_type':'TimeoutError'} if audio.startswith('fail') else {'status':'ok'}

    monkeypatch.setattr(runner, 'IseProbe', Probe)
    monkeypatch.setattr(runner, 'public_result', lambda result: result)
    monkeypatch.setattr(runner, 'target_at', lambda result,*args: {'state':'unavailable' if result['status']!='ok' else 'not_flagged', 'finals':[]})
    args = SimpleNamespace(input=str(source), output=str(tmp_path/'output.json'), allow_paid=False,
                           continue_on_unavailable=continue_on_unavailable)
    return args, calls


def test_failure_stops_by_default_and_preserves_incomplete_report(tmp_path, monkeypatch):
    args, calls = setup_batch(tmp_path, monkeypatch, ['fail1','good'], False)
    with pytest.raises(RuntimeError, match='without retry'):
        asyncio.run(runner.run(args))
    report = json.loads((tmp_path/'output.json').read_text())
    assert calls == ['fail1']
    assert not report['complete']
    assert report['cases'][0]['ise_failure']['error_type'] == 'TimeoutError'


def test_optional_continuation_keeps_unknown_rows_and_stops_at_three_distinct_failures(tmp_path, monkeypatch):
    args, calls = setup_batch(tmp_path, monkeypatch, ['fail1','fail1','fail2','fail3','good'], True)
    with pytest.raises(RuntimeError, match='without retry'):
        asyncio.run(runner.run(args))
    report = json.loads((tmp_path/'output.json').read_text())
    assert calls == ['fail1','fail1','fail2','fail3']  # duplicate targets read the probe cache
    assert len(report['cases']) == 4
    assert all(r['ise_observation']['state']=='unavailable' for r in report['cases'])


def test_cached_failure_does_not_delete_other_recordings(tmp_path, monkeypatch):
    args, calls = setup_batch(tmp_path, monkeypatch, ['fail1','good'], True)
    asyncio.run(runner.run(args))
    report = json.loads((tmp_path/'output.json').read_text())
    assert report['complete']
    assert report['new_calls'] == 0
    assert [r['ise_observation']['state'] for r in report['cases']] == ['unavailable','not_flagged']


@pytest.mark.parametrize('before,ceiling,expected',[(178,280,278),(178,200,200),(268,280,280)])
def test_explicit_cumulative_ceiling_keeps_the_hundred_request_per_run_limit(tmp_path,monkeypatch,before,ceiling,expected):
    args,_=setup_batch(tmp_path,monkeypatch,[],False)
    Path('data/derived/ise-validation/requests.json').write_text(json.dumps([{}]*before))
    observed=[]
    class Probe:
        def __init__(self,path,*,allow_paid,max_calls):
            observed.append(max_calls)
    monkeypatch.setattr(runner,'IseProbe',Probe)
    args.max_total_calls=ceiling
    asyncio.run(runner.run(args))
    assert observed==[expected]
