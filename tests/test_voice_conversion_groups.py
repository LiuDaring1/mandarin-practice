import importlib.util
import json
from pathlib import Path
import sys

import pytest

scripts=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('voice_conversion_groups',scripts/'voice_conversion_groups.py')
groups=importlib.util.module_from_spec(spec)
spec.loader.exec_module(groups)


def test_group_plan_preserves_order_and_exact_frame_boundaries(tmp_path):
    rows=[{'id':'sentence-01-中文','kind':'sentence','source':'/one.wav','source_sha256':'one',
           'duration':123.456,'export_name':'one.wav'},
          {'id':'t1-p001','kind':'word','source':'/two.wav','source_sha256':'two',
           'duration':234.567,'export_name':'two.wav'},
          {'id':'done','kind':'word','source':'/done.wav','source_sha256':'done',
           'duration':20,'export_name':'done.wav'}]
    (tmp_path/'queue.json').write_text(json.dumps({'jobs':rows}))
    (tmp_path/'exports').mkdir();(tmp_path/'exports/done.wav').write_bytes(b'already exported')
    result=groups.prepare(tmp_path)
    g=result['groups'][0]
    assert [r['job'] for r in g['jobs']]==['sentence-01-中文','t1-p001']
    assert g['jobs'][1]['start_sample']==1235*1600
    assert all(r['samples']%1600==0 and r['duration']<600 for r in g['jobs'])
    assert all(r['file'].isascii() for r in g['jobs'])
    assert groups.prepare(tmp_path)==result


def test_group_plan_rejects_input_above_supervised_limit(tmp_path):
    row={'id':'long','kind':'word','source':'/long.wav','source_sha256':'long',
         'duration':600,'export_name':'long.wav'}
    (tmp_path/'queue.json').write_text(json.dumps({'jobs':[row]}))
    with pytest.raises(ValueError,match='subdivision'):
        groups.prepare(tmp_path)
    assert not (tmp_path/'groups/plan.json').exists()


def test_local_repair_plan_is_parent_bound_and_resumable(tmp_path):
    import wave
    import numpy as np
    source=tmp_path/'original.wav'
    with wave.open(str(source),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
        t=np.arange(20*16000)/16000
        w.writeframes((6000*np.sin(2*np.pi*220*t)).astype('<i2').tobytes())
    parent={'id':'page','kind':'word','source':str(source),
        'source_sha256':groups.vc.digest(source),'duration':20,'voice':'news-female',
        'export_name':'page.wav','clips':[{'id':'word','start':3,'end':4,'relative_path':'word.wav'}]}
    groups.vc.write_json(tmp_path/'queue.json',{'version':1,'jobs':[parent]})
    (tmp_path/'inputs').mkdir();(tmp_path/'exports').mkdir()
    (tmp_path/'exports/page.wav').write_bytes(b'bad export already exists')
    groups.vc.write_json(tmp_path/'reports/page__conversion-integrity.json',{
        'passed':False,'file_integrity':True,'timing':{'stable':True},
        'new_loss':[{'source_start':3,'source_end':4}]})
    groups.repair_plan(tmp_path)
    q=json.loads((tmp_path/'queue.json').read_text())['jobs']
    assert q[0]==parent and len(q)==2
    repair=q[1]
    assert repair['parent_job']=='page' and repair['duration']==14
    assert repair['clips'][0]['id']=='word'
    assert groups.vc.probe(repair['source'])['duration']==14
    before=(tmp_path/'queue.json').read_bytes()
    groups.repair_plan(tmp_path)
    assert (tmp_path/'queue.json').read_bytes()==before


def test_release_blocks_unfinished_jobs_and_changed_candidates(tmp_path):
    source=tmp_path/'source.wav';source.write_bytes(b'original protected')
    job={'id':'page','kind':'word','source':str(source),'source_sha256':groups.vc.digest(source),
         'export_name':'converted.wav','voice':'news-female','clips':[
         {'id':'word','relative_path':'word.wav','start':1,'end':2}]}
    groups.vc.write_json(tmp_path/'queue.json',{'jobs':[job]})
    with pytest.raises(ValueError,match='incomplete'):
        groups.release(tmp_path)
    assert not (tmp_path/'release-preserved-v1.json').exists()
    export=tmp_path/'exports/converted.wav';export.parent.mkdir();export.write_bytes(b'converted')
    folder=tmp_path/'staged-preserved-v1/page';folder.mkdir(parents=True)
    wav=folder/'word.wav';wav.write_bytes(b'new clip')
    manifest=folder/'manifest.json'
    groups.vc.write_json(manifest,{'clips':[{**job['clips'][0],'sha256':groups.vc.digest(wav),
                                        'audio':{'duration':1}}]})
    groups.vc.write_json(tmp_path/'reports/page__preserved-v1__conversion-integrity.json',{
        'passed':True,'manifest_sha256':groups.vc.digest(manifest),
        'export_sha256':groups.vc.digest(export)})
    wav.write_bytes(b'modified after review')
    with pytest.raises(ValueError,match='changed since review'):
        groups.release(tmp_path)
    assert not (tmp_path/'release-preserved-v1.json').exists()
    wav.write_bytes(b'new clip')
    groups.release(tmp_path)
    groups.activate(tmp_path,tmp_path)
    from pth_corpus.voice_library import VoiceLibrary
    library=VoiceLibrary(tmp_path)
    assert library.replacement('word','word',tmp_path/'word.wav')==wav
    assert source.read_bytes()==b'original protected'


def test_activation_requires_complete_review_binding(tmp_path):
    batch=tmp_path/'batch';batch.mkdir()
    source=tmp_path/'source.wav';source.write_bytes(b'original')
    clip=tmp_path/'candidate.wav';clip.write_bytes(b'candidate')
    job={'id':'page','kind':'word','source':str(source),'source_sha256':groups.vc.digest(source),
         'clips':[{'id':'word','relative_path':'word.wav'}]}
    groups.vc.write_json(batch/'queue.json',{'jobs':[job]})
    groups.vc.write_json(batch/'release-preserved-v1.json',{'jobs':1,'clips':{'word':{
        'kind':'word','original_relative_path':'word.wav','replacement':str(clip),
        'sha256':groups.vc.digest(clip)}}})
    with pytest.raises(ValueError,match='approval changed'):
        groups.activate(batch,tmp_path)
    assert not (tmp_path/'derived/voice-conversion/active.json').exists()


def test_second_voice_queue_preserves_originals_and_omits_old_repairs(tmp_path):
    source=tmp_path/'source.wav';source.write_bytes(b'original')
    female=tmp_path/'female';male=tmp_path/'male'
    original={'id':'t1-p001','kind':'word','voice':'news-female','source':str(source),
        'source_sha256':groups.vc.digest(source),'duration':10,
        'export_name':'t1-p001__news-female.wav','clips':[{'id':'id','start':1,'end':2}]}
    groups.vc.write_json(female/'queue.json',{'jobs':[original,{'kind':'repair'}]})
    groups.clone_voice(male,female,'news-male')
    jobs=json.loads((male/'queue.json').read_text())['jobs']
    assert jobs==[{**original,'voice':'news-male','export_name':'t1-p001__news-male.wav'}]
    group=groups.prepare(male)['groups'][0]
    assert group['voice']=='news-male' and group['export_name'].endswith('__news-male.wav')
    assert group['jobs'][0]['file'].startswith('news-male__')
    with pytest.raises(ValueError,match='overwrite'):
        groups.clone_voice(male,female,'news-male')


def test_pair_activation_requires_two_complete_matching_releases(tmp_path):
    from pth_corpus.voice_library import VoiceLibrary
    source=tmp_path/'source.wav';source.write_bytes(b'original')
    folders=[]
    for voice in ('news-female','news-male'):
        batch=tmp_path/voice;folders.append(batch)
        job={'id':'page','kind':'word','source':str(source),'source_sha256':groups.vc.digest(source),
             'export_name':'converted.wav','voice':voice,'clips':[
             {'id':'word','relative_path':'word.wav','start':1,'end':2}]}
        groups.vc.write_json(batch/'queue.json',{'jobs':[job]})
        export=batch/'exports/converted.wav';export.parent.mkdir();export.write_bytes(voice.encode())
        folder=batch/'staged-preserved-v1/page';folder.mkdir(parents=True)
        wav=folder/'word.wav';wav.write_bytes(voice.encode())
        manifest=folder/'manifest.json'
        groups.vc.write_json(manifest,{'clips':[{**job['clips'][0],
            'sha256':groups.vc.digest(wav),'audio':{'duration':1}}]})
        groups.vc.write_json(batch/'reports/page__preserved-v1__conversion-integrity.json',{
            'passed':True,'manifest_sha256':groups.vc.digest(manifest),
            'export_sha256':groups.vc.digest(export)})
        groups.release(batch)
    groups.activate_pair(*folders,tmp_path)
    library=VoiceLibrary(tmp_path)
    assert len(library.status()['voices'])==2
    for batch in folders:
        assert library.replacement('word','word',tmp_path/'word.wav',batch.name).read_bytes()==batch.name.encode()
    pointer=tmp_path/'derived/voice-conversion/active.json'
    before=pointer.read_bytes()
    with pytest.raises(ValueError,match='Duplicate voice'):
        groups.activate_pair(folders[0],folders[0],tmp_path)
    assert pointer.read_bytes()==before
