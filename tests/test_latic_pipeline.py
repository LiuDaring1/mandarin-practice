import asyncio
import io
import json
from pathlib import Path
import wave

import numpy as np
import pytest

import ise_probe
import run_latic_validation as pipe
from nasal_validation_execution import MirroredIseProbe,align_target,durable_json,model_membership


def wav_bytes(value=0):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'))
        w.writeframes(int(value).to_bytes(2,'little',signed=True)*16000)
    return stream.getvalue()


def response(symbol='ren2',omitted=False):
    return {'status':'ok','xml':f'''<read_sentence><word content="人人">
      <syll content="人" symbol="{symbol}" rec_node_type="paper" dp_message="{'16' if omitted else '0'}" beg_pos="10" end_pos="30">
      <phone is_yun="1" content="en" dp_message="0" perr_msg="0" beg_pos="15" end_pos="30"/></syll>
      <syll content="人" symbol="ren2" rec_node_type="paper" dp_message="0" beg_pos="50" end_pos="70">
      <phone is_yun="1" content="en" dp_message="0" perr_msg="0" beg_pos="55" end_pos="70"/></syll>
    </word></read_sentence>'''}


def test_alignment_keeps_repeated_character_position_and_reading(tmp_path):
    p=tmp_path/'a.wav';p.write_bytes(wav_bytes())
    row={'audio':str(p),'reference':'人人。','position':1,'expected_pinyin':'ren'}
    got,ok=align_target(row,ise_probe.public_result(response()))
    assert ok and got['bounds']=={'syllable':[.5,.7],'vowel':[.55,.7]}
    row['position']=0
    got,ok=align_target(row,ise_probe.public_result(response('reng2')))
    assert not ok and got['reason']=='reference_pinyin_mismatch'
    assert not align_target(row,ise_probe.public_result(response(omitted=True)))[1]
    row['reference']='人'
    assert not align_target(row,ise_probe.public_result(response()))[1]


@pytest.mark.parametrize('name,want',[
    ('xeus',[True,False,True,True]),('hubert',[True,True,False,True]),
    ('hubert_pair',[True,True,False,True]),('fusion',[True,False,False,True]),
    ('hubert_temporal',[True,True,True,False])])
def test_feature_failures_are_model_specific(name,want):
    flags=np.array([[1,1,1],[0,1,1],[1,0,1],[1,1,0]],dtype=bool)
    assert model_membership(name,flags).tolist()==want


def test_nonboolean_availability_is_not_implicitly_coerced():
    with pytest.raises(ValueError):model_membership('xeus',np.ones((3,3)))
    with pytest.raises(ValueError):model_membership('unknown',np.ones((3,3),dtype=bool))


def test_live_replay_allows_only_small_numeric_drift():
    base={'id':'x','scores':[.1,.2,.7],'gap':.5,'candidate_nasal_change':False}
    pipe.compare_prediction({**base,'gap':.5000001},base,1e-5)
    with pytest.raises(ValueError):pipe.compare_prediction({**base,'candidate_nasal_change':True},base,1e-5)
    with pytest.raises(ValueError):pipe.compare_prediction({**base,'scores':[.1,.3,.6]},base,1e-5)


def test_internal_mirror_blocks_ledger_regression_before_call(tmp_path,monkeypatch):
    provider=tmp_path/'provider';mirror=tmp_path/'mirror';provider.mkdir();mirror.mkdir()
    (provider/'requests.json').write_text('["a"]');(mirror/'requests.json').write_text('["a","b"]')
    async def forbidden(*args,**kwargs):raise AssertionError('Request reached parent')
    monkeypatch.setattr(ise_probe.IseProbe,'_call_locked',forbidden)
    probe=MirroredIseProbe(provider,mirror=mirror)
    with pytest.raises(RuntimeError,match='regressed'):asyncio.run(probe._call_locked('unused','unused'))


def test_internal_completed_result_cannot_be_overwritten_after_volume_loss(tmp_path,monkeypatch):
    monkeypatch.setattr(pipe,'FOLDER',tmp_path/'missing-external')
    mirror=tmp_path/'internal';mirror.mkdir();monkeypatch.setattr(pipe,'MIRROR',mirror)
    (mirror/'api-result.json').write_text('{}')
    with pytest.raises(ValueError,match='internal mirror'):pipe.require_new('api-result.json')


def test_pipeline_integration_keeps_import_api_and_each_model_failure(tmp_path,monkeypatch):
    """Synthetic complete orchestration; provider and encoder are test doubles."""
    folder=tmp_path/'pipeline';runner=tmp_path/'runner';provider=tmp_path/'provider';mirror=tmp_path/'internal'
    for p in (folder,runner/'audio-import',provider):p.mkdir(parents=True)
    monkeypatch.setattr(pipe,'FOLDER',folder);monkeypatch.setattr(pipe,'MIRROR',mirror)
    monkeypatch.setattr(pipe,'PROVIDER',provider);monkeypatch.setattr(pipe.runtime,'FOLDER',runner)
    selected=[];records=[];excluded=[]
    for i in range(69):
        uid=f'synthetic-{i}';audio=tmp_path/(uid+'.wav');audio.write_bytes(wav_bytes(i))
        targets=[]
        for position in range(2 if i<3 else 1):
            t={'id':uid+':'+str(position),'utterance_id':uid,'speaker':'synthetic','split':'external',
               'cohort':'latic','position':position,'expected_pinyin':'ren','expected_final':'en',
               'expected_label':'front','actual_label':'back' if len(selected)<18 else 'front',
               'role':'error' if len(selected)<18 else 'normal','reference_text':'人人'}
            selected.append(t);targets.append(t)
        r={'utterance_id':uid,'targets':targets,'audio':str(audio),'audio_sha256':pipe.runtime.sha(audio),'reference':'人人','core':'read_sentence'}
        (records if i<67 else excluded).append(r if i<67 else {'utterance_id':uid,'targets':targets,'reason':'synthetic_missing_audio'})
    monkeypatch.setattr(pipe.runtime,'selected_rows',lambda:selected)
    models={n:{'name':n} for n in pipe.runtime.NAMES};plan={'models':models}
    monkeypatch.setattr(pipe,'checked',lambda:plan)
    durable_json(folder/'plan.json',plan);durable_json(runner/'plan.json',{})
    archive=tmp_path/'archive.zip';archive.write_bytes(b'synthetic importer output receipt')
    durable_json(runner/'audio-import/plan.json',{'archive':str(archive),'archive_sha256':pipe.runtime.sha(archive),'runner_plan_sha256':pipe.runtime.sha(runner/'plan.json')})
    durable_json(runner/'audio-import/manifest.json',{'complete':True,'plan_sha256':pipe.runtime.sha(runner/'audio-import/plan.json'),'records':records,'excluded':excluded})
    durable_json(folder/'preflight.json',{'complete':True,'plan_sha256':pipe.runtime.sha(folder/'plan.json')})
    durable_json(provider/'requests.json',['historical']);durable_json(provider/'config.json',{'app_id':'synthetic'})
    calls=[]
    async def fake_evaluate(config,params,audio):
        with wave.open(io.BytesIO(audio),'rb') as w:i=int.from_bytes(w.readframes(1),'little',signed=True)
        # New transport must mirror the reservation before the network boundary.
        assert json.loads((mirror/'provider/requests.json').read_text())==json.loads((provider/'requests.json').read_text())
        calls.append(i)
        return {'status':'provider_error','code':60114} if i==64 else response('reng2' if i==65 else 'ren2',i==66)
    monkeypatch.setattr(ise_probe,'evaluate',fake_evaluate)
    pipe.budget();asyncio.run(pipe.api(True));pipe.align()
    dataset=json.loads((folder/'dataset.json').read_text())
    assert len(dataset['rows'])==67 and len(dataset['excluded'])==5
    assert len(calls)==67 and len(set(calls))==67
    assert len(json.loads((provider/'requests.json').read_text()))==68
    def fake_extract(rows,cache,plan):
        n=len(rows);flags=np.ones((n,3),dtype=bool);flags[0,0]=False;flags[1,1]=False;flags[2,2]=False
        return {'ids':np.array([r['id'] for r in rows]),'paired':np.zeros((n,2,2048)),
                'temporal':np.zeros((n,4096)),'present':np.ones(n,dtype=bool),'available':flags},{'sources':{},'failures':[]}
    monkeypatch.setattr(pipe,'extract_rows',fake_extract)
    def fake_predict(spec,rows,paired,temporal,present):
        from probe_phonetic_xeus import apply
        assert paired.shape[0]==temporal.shape[0]==len(rows)==len(present)
        return apply(rows,np.tile([.8,.1,.1],(len(rows),1)),{'calibration_mode':'global','review_margin':1.,'matching_margin':1.})
    monkeypatch.setattr(pipe.runtime,'predict',fake_predict)
    pipe.features();pipe.evaluate()
    result=json.loads((folder/'evaluation.json').read_text())
    for name,value in result['comparisons'].items():
        summary=value['summary']['all']
        assert summary['selected_targets']==72 and summary['unknown_selected_targets']==72
        assert summary['scored_targets']==(65 if name=='fusion' else 66)
    assert len(list((mirror/'provider/cache').glob('*.json')))==67
    with pytest.raises(ValueError,match='already frozen'):asyncio.run(pipe.api(True))
    assert len(calls)==67
