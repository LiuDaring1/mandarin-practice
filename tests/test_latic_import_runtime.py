import io
import json
from pathlib import Path
import stat
import wave
import shutil
from zipfile import ZipFile,ZipInfo

import numpy as np
import pytest

from import_latic_validation import TABLES,audit_record,index_archive,safe_member,same_annotation,table_mapping,verify_wave
from latic_validation_runtime import predict,summarize_selected
import import_latic_validation as importer


@pytest.mark.parametrize('name,mode',[
    ('../WAVA/000110062.wav',0),('/WAVA/000110062.wav',0),
    ('WAVA\\000110062.wav',0),('WAVA/000110062.wav',stat.S_IFLNK|0o777)])
def test_unsafe_zip_paths_and_symlinks_are_never_audio(name,mode):
    info=ZipInfo(name);info.external_attr=mode<<16
    assert not safe_member(info)


@pytest.mark.parametrize('text',['bad text','000110062','000110062 a\n000110062 b'])
def test_table_identity_ambiguity_rejected(text):
    with pytest.raises(ValueError):table_mapping(text)


def test_annotation_normalization_preserves_pinyin_token_boundaries():
    assert same_annotation('春 天','春天','expected_text')
    assert same_annotation('chun1  tian1','chun1 tian1','expected_pinyin')
    assert not same_annotation('chun1tian1','chun1 tian1','expected_pinyin')
    assert not same_annotation('chun1 tian1','chung1 tian1','actual_pinyin')


def bundle_bytes(duplicate_audio=False,duplicate_table=False):
    data=io.BytesIO()
    with ZipFile(data,'w') as bundle:
        for _,(suffix,_) in TABLES.items():bundle.writestr('data/'+suffix,'000110062 春天\n')
        bundle.writestr('data/WAVA/000110062.wav',b'placeholder')
        if duplicate_audio:bundle.writestr('other/WAVA/000110062.wav',b'placeholder')
        if duplicate_table:bundle.writestr(TABLES['expected_text'][0],'000110062 春天\n')
    data.seek(0);return data


def test_exact_stem_and_all_four_tables_required():
    with ZipFile(bundle_bytes()) as bundle:
        audio,tables=index_archive(bundle)
        expected={kind:{'000110062':'春天'} for kind in TABLES}
        assert audit_record('000110062',audio,tables,expected) is None
        assert audit_record('000110063',audio,tables,expected)=='missing_audio'
        expected['actual_pinyin']['000110062']='different'
        assert audit_record('000110062',audio,tables,expected)=='conflicting_actual_pinyin'


def test_duplicate_wave_id_is_unavailable_not_first_match():
    with ZipFile(bundle_bytes(duplicate_audio=True)) as bundle:
        audio,tables=index_archive(bundle)
        assert audit_record('000110062',audio,tables,{})=='ambiguous_audio_id'


def test_ambiguous_table_stops_import_before_conversion():
    with ZipFile(bundle_bytes(duplicate_table=True)) as bundle:
        with pytest.raises(ValueError,match='ambiguous'):index_archive(bundle)


def wav_bytes(rate=16000,channels=1,seconds=.2):
    data=io.BytesIO()
    with wave.open(data,'wb') as w:
        w.setparams((channels,2,rate,0,'NONE','not compressed'))
        w.writeframes(b'\0'*(int(rate*seconds)*channels*2))
    return data.getvalue()


def test_container_header_and_entire_payload_verified():
    assert verify_wave(wav_bytes())['frames']==3200
    with pytest.raises(ValueError,match='Truncated'):verify_wave(wav_bytes()[:-8])


@pytest.mark.parametrize('kwargs',[{'seconds':.01},{'rate':4000},{'channels':3}])
def test_unsupported_audio_is_not_silently_resampled(kwargs):
    with pytest.raises(ValueError):verify_wave(wav_bytes(**kwargs))


def test_model_adapter_rejects_bad_order_shapes_and_masks_before_weight_load():
    rows=[{'id':'a'},{'id':'a'}]
    with pytest.raises(ValueError):predict({},rows,np.zeros((2,2,2048)),np.zeros((2,4096)),np.ones(2,dtype=bool))
    with pytest.raises(ValueError):predict({},[{'id':'a'}],np.zeros((1,2,2048)),np.zeros((1,4096)),np.ones(1))
    with pytest.raises(ValueError):predict({},[{'id':'a'}],np.zeros((1,2,2048)),np.full((1,4096),np.nan),np.ones(1,dtype=bool))


def test_unavailable_errors_and_normals_stay_in_the_full_denominator():
    rows=[{'id':'a','split':'external','expected_label':'front','actual_label':'back'},
          {'id':'b','split':'external','expected_label':'back','actual_label':'back'}]
    result=summarize_selected(rows,[])
    assert result['all']['selected_targets']==2 and result['all']['unavailable_targets']==2
    assert result['all']['unavailable_errors']==1 and result['all']['unavailable_normal']==1
    assert result['all']['unknown_selected_targets']==2
    assert result['front']['missed_selected_errors']==1


def test_training_membership_and_duplicate_denominator_rejected():
    row={'id':'a','split':'train','expected_label':'front','actual_label':'front'}
    with pytest.raises(ValueError):summarize_selected([row],[])
    row['split']='external'
    with pytest.raises(ValueError):summarize_selected([row,row],[])


@pytest.mark.skipif(shutil.which('ffmpeg') is None,reason='FFmpeg required for conversion integration')
def test_import_integration_keeps_72_targets_with_missing_conflicting_and_bad_audio(tmp_path,monkeypatch):
    runner=tmp_path/'runner';runner.mkdir();(runner/'plan.json').write_text('{}')
    ids=[f'{100000000+i:09d}' for i in range(69)]
    rows=[{'id':uid+':0','utterance_id':uid,'speaker':'synthetic','reference_text':'春天'} for uid in ids]
    rows += [{**rows[i],'id':ids[i]+':1'} for i in range(3)]
    monkeypatch.setattr(importer,'FOLDER',runner)
    monkeypatch.setattr(importer,'checked',lambda:{})
    monkeypatch.setattr(importer,'selected_rows',lambda:rows)
    tables={}
    for kind,(suffix,_) in TABLES.items():
        p=tmp_path/(kind+'.txt');p.write_text(''.join(uid+' 春天\n' for uid in ids))
        tables[kind]=(suffix,p)
    monkeypatch.setattr(importer,'TABLES',tables)
    archive=tmp_path/'synthetic.zip'
    with ZipFile(archive,'w') as z:
        for kind,(suffix,_) in tables.items():
            z.writestr('test/'+suffix,''.join(uid+(' 错文\n' if kind=='actual_text' and i==66 else ' 春天\n') for i,uid in enumerate(ids)))
        for i,uid in enumerate(ids[:-1]):
            z.writestr('test/WAVA/'+uid+'.wav',b'broken-wave' if i==67 else wav_bytes(rate=44100,channels=2))
    importer.run(archive)
    manifest=json.loads((runner/'audio-import/manifest.json').read_text())
    assert manifest['original_selected_targets']==72 and manifest['imported_targets']==69
    assert manifest['unavailable_targets']==3 and len(manifest['records'])==66
    assert len(manifest['excluded'])==3 and manifest['api_calls']==0
    assert not manifest['acoustic_boundaries_or_actual_pronunciation_validated']
    for record in manifest['records']:
        converted=verify_wave(Path(record['audio']).read_bytes())
        assert (converted['channels'],converted['rate'],converted['sample_width'])==(1,16000,2)
