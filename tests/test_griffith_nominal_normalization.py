from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_griffith_nominal import canonical_syllable, map_nominal_canonical, read_targets
from prepare_griffith_nasal_probe import map_nominal


def items(values):
    return [{'text':v} for v in values.split()]


@pytest.mark.parametrize('spelling',['nü3','nv3','nu:3'])
def test_equivalent_umlaut_spelling_restores_full_reference(spelling):
    data=items('lin2 tong2 tong0 shi4 ta1 de0 '+spelling+' peng2 you0')
    mapped=map_nominal_canonical(data,'林彤彤是他的女朋友。')
    assert mapped is not None and [r['position'] for r in mapped]==list(range(9))


def test_old_valid_sequence_replays_including_erhua_and_pauses():
    data=items('pau chen2 dong1 you3 dianr3 leng3 paus')
    assert map_nominal_canonical(data,'陈东有点儿冷。')==map_nominal(data,'陈东有点儿冷。')
    assert map_nominal_canonical(data,'陈东有点儿冷。')[3]['char_span']==2


@pytest.mark.parametrize('values,reference',[
    ('wo3 meng0','我们'),('lin2 tong2 tong0 nü3','林彤彤女女'),
    ('lin2 tong2 tong2 tong0 nü3','林彤彤女'),('lin2 tong2 tong0 nu3','林彤彤女'),
    ('ta1 shi4 shei2','他是谁')])
def test_reading_changes_and_omissions_are_not_normalized_away(values,reference):
    assert map_nominal_canonical(items(values),reference) is None


def test_nasal_direction_is_not_an_equivalent_spelling():
    assert canonical_syllable('in4')!=canonical_syllable('ing4')
    assert canonical_syllable('an1')!=canonical_syllable('ang1')


def record(error='',auxiliary=''):
    row=lambda text:{'start':0.,'end':1.,'text':text}
    return {'tiers':{'NP':[row('lin2')],'ER':[row(error)],'Misc':[row('')],'IP':[row(auxiliary)]}}


def test_restoration_does_not_drop_auxiliary_errors_or_ambiguous_symbols():
    mapping=[{'tier_index':0,'position':0,'char_span':1}]
    normal,excluded=read_targets(record(),mapping)
    assert len(normal)==1 and normal[0]['actual_label']=='front' and not excluded
    targets,excluded=read_targets(record(auxiliary='*'),mapping)
    assert not targets and excluded[0]['reason']=='auxiliary_annotation_conflict'
    targets,excluded=read_targets(record(error='in{g-}'),mapping)
    assert not targets and excluded[0]['reason']=='unsupported_annotation'


def test_restored_explicit_substitution_keeps_source_label():
    targets,excluded=read_targets(record(error='in{ing}'),[{'tier_index':0,'position':0,'char_span':1}])
    assert not excluded and targets[0]['state']=='nasal_substitution'
    assert targets[0]['actual_label']=='back' and targets[0]['pure_nasal_pair'] is True


def restored_fixture():
    target={'actual_label':'back','expected_label':'front','expected_final':'in','position':0,'human_syllable':[0.,1.]}
    rec={'uid':'new','audio':'a.wav','speaker':'griffith:test','split':'external','reference':'林','core':'read_sentence','targets':[target]}
    row={**target,**{k:rec[k] for k in ('audio','speaker','split','reference','core')},'id':'new-pos0'}
    return {'records':[rec]},row


def test_restored_dataset_preserves_unavailable_target_and_cannot_fit():
    from probe_griffith_restored import validate_dataset
    manifest,row=restored_fixture()
    validate_dataset(manifest,{'rows':[],'excluded':[row]})
    with pytest.raises(ValueError,match='denominator'):
        validate_dataset(manifest,{'rows':[],'excluded':[]})
    with pytest.raises(ValueError,match='fitting partitions'):
        validate_dataset(manifest,{'rows':[{**row,'split':'train'}],'excluded':[]})
    with pytest.raises(ValueError,match='metadata changed'):
        validate_dataset(manifest,{'rows':[{**row,'actual_label':'front'}],'excluded':[]})


def test_cached_alignment_skips_empty_record_and_preserves_failed_target(monkeypatch,tmp_path):
    import asyncio
    import ise_probe
    import prepare_nasal_feature_data
    from probe_griffith_restored import align_cached
    manifest,row=restored_fixture();rec=manifest['records'][0]
    audio=tmp_path/'a.wav';audio.write_bytes(b'test')
    rec['audio']=str(audio);rec['targets'][0]['state']='nasal_substitution'
    rec['targets'].append({**rec['targets'][0],'position':1})
    manifest['records'].insert(0,{**rec,'uid':'empty','audio':'must-not-read.wav','targets':[]})
    manifest['limits']=[]
    calls=[]
    class Cache:
        async def call(self,audio,reference,**kwargs):
            calls.append(audio);return {}
    monkeypatch.setattr(ise_probe,'public_result',lambda result:result)
    monkeypatch.setattr(ise_probe,'target_at',lambda result,reference,pos:{'state':'not_flagged','position':pos})
    monkeypatch.setattr(prepare_nasal_feature_data,'interval',lambda obs,audio:None if obs['position'] else {'syllable':[0.,1.]})
    result=asyncio.run(align_cached(manifest,Cache()))
    assert calls==[str(audio)]
    assert [r['id'] for r in result['rows']]==['new-pos0']
    assert [r['id'] for r in result['excluded']]==['new-pos1']
    assert result['excluded'][0]['reason']=='unusable_cached_interval'


@pytest.mark.parametrize('absolute',[False,True])
def test_amendment_checks_absolute_and_relative_paths_without_accepting_other_edits(monkeypatch,tmp_path,absolute):
    import json
    import probe_griffith_restored as module
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(module,'FOLDER',tmp_path)
    source=tmp_path/'probe.py';source.write_text('original')
    backup=tmp_path/'original.py';backup.write_bytes(source.read_bytes())
    monkeypatch.setattr(module,'__file__',str(source))
    path=str(source) if absolute else 'probe.py'
    plan={'sources':{path:module.sha(source)}}
    (tmp_path/'plan.json').write_text(json.dumps(plan))
    source.write_text('skip empty records')
    amendment={'path':'probe.py','backup':str(backup),'before_sha256':module.sha(backup),'after_sha256':module.sha(source)}
    (tmp_path/'implementation-amendment.json').write_text(json.dumps(amendment))
    assert module.checked()==plan
    source.write_text('unrecorded change')
    with pytest.raises(ValueError,match='source changed'): module.checked()
    source.write_text('skip empty records');backup.write_text('altered original')
    with pytest.raises(ValueError,match='source changed'): module.checked()
