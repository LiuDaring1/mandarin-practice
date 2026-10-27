import json

import numpy as np
import pytest

import run_matrix_validation as run
from train_nasal_feature_probe import observe


def row(uid='a', style='Plain', position=0):
    return {'id':uid,'style':style,'speaker':'speaker','code':'00000','position':position,
            'expected_label':'front','actual_label':None,'condition':'source_qc','split':'external'}


def output(r, change=False, match=False, predicted='front'):
    return {'id':r['id'],'actual':None,'expected':'front','predicted':predicted,
            'candidate_nasal_change':change,'candidate_nasal_match':match}


def test_outputs_keep_missing_targets_and_do_not_claim_accuracy():
    rows=[row('a'),row('b'),row('c'),row('d')]
    result=run.output_summary(rows,[output(rows[0],change=True),output(rows[1],match=True),output(rows[2])])
    assert result=={'selected':4,'scored':3,'unavailable':1,'correction_outputs':1,
                    'matching_outputs':1,'unknown_outputs':2,'actual_phone_accuracy_measured':False}


@pytest.mark.parametrize('mutation',[{'actual':'front'},{'expected':'back'},{'id':'unknown'},
                                    {'candidate_nasal_change':True,'candidate_nasal_match':True}])
def test_reject_mislabeled_or_invalid_output(mutation):
    r=row()
    with pytest.raises(ValueError):run.output_summary([r],[output(r)|mutation])


def test_duplicates_rejected():
    r=row()
    with pytest.raises(ValueError):run.output_summary([r,r],[])
    with pytest.raises(ValueError):run.output_summary([r],[output(r),output(r)])


def test_pairs_keep_missing_style_and_scored_unknown_separate():
    rows=[row('a'),row('b','Lombard'),row('c',position=1)]
    result=run.style_pairs(rows,[output(rows[0],match=True),output(rows[1],predicted='back')])
    assert result=={'selected_pairs':2,'both_scored':1,'raw_category_changed':1,
                    'plain_to_lombard_outputs':{'match -> unknown':1,'unavailable -> unavailable':1}}


def test_pair_identity_cannot_silently_overwrite_or_change_category():
    with pytest.raises(ValueError):run.style_pairs([row(),row('b')],[])
    with pytest.raises(ValueError):run.style_pairs([row(),row('b','Lombard')|{'expected_label':'back'}],[])


def test_no_actual_label_needed_for_frozen_prediction_logic():
    r=row();pred=observe([r],np.array([[1.,0.,0.]]),.1,.1)[0]
    assert pred['actual'] is None
    assert pred['candidate_nasal_match'] and not pred['candidate_nasal_change']


def test_selection_preserves_unknown_label_and_rejects_invented_label():
    record={'speaker':'s','style':'Plain','code':'00000','targets':[row()]}
    assert run.selected([record])[0]['actual_label'] is None
    record['targets'][0]['actual_label']='front'
    with pytest.raises(ValueError):run.selected([record])


def test_content_mismatch_does_not_request_api(tmp_path,monkeypatch):
    records=[{'audio':'first','reference':'原文','core':'read_sentence'},
             {'audio':'second','reference':'原文','core':'read_sentence'}]
    monkeypatch.setattr(run,'imported',lambda:({}, {'rows':[]}))
    monkeypatch.setattr(run,'imported',lambda:({'records':records},{'rows':[{'identity_ok':False},{'identity_ok':True}]}))
    monkeypatch.setattr(run,'new',lambda _:None)
    monkeypatch.setattr(run,'cache_key',lambda *_:'key')
    monkeypatch.setattr(run.runtime,'read',lambda _:[])
    monkeypatch.setattr(run.runtime,'sha',lambda _:'digest')
    captured={}
    def staged(requests,*_):
        captured['requests']=requests
        return {'new_request_keys':['key'],'maximum_total_attempts':1}
    monkeypatch.setattr(run,'stage_budget',staged)
    monkeypatch.setattr(run,'save',lambda *args:None)
    run.budget()
    assert [r['audio'] for r in captured['requests']]==['second']


def test_alignment_preserves_entire_selected_denominator(monkeypatch):
    # One content mismatch, one unusable interval, 152 usable targets.
    records=[]
    for i in range(154):
        records.append({'speaker':'s','style':'Plain','code':str(i),'audio':str(i),'audio_sha256':'x',
                        'reference':'文','core':'read_sentence','targets':[row(str(i))]})
    content={'rows':[{'identity_ok':i!=0} for i in range(154)]}
    responses={str(i):{'result':{},'cache_sha256':'x'} for i in range(1,154)}
    monkeypatch.setattr(run,'api_checked',lambda:None)
    monkeypatch.setattr(run,'imported',lambda:({'records':records},content))
    monkeypatch.setattr(run,'new',lambda _:None)
    monkeypatch.setattr(run.runtime,'read',lambda _:{'complete':True,'api_plan_sha256':'x','results':responses})
    monkeypatch.setattr(run.runtime,'sha',lambda _:'x')
    monkeypatch.setattr(run,'cache_key',lambda audio,*_:audio)
    monkeypatch.setattr(run,'align_target',lambda r,_:({**r,'reason':'bad'} if r['id']=='1' else r,r['id']!='1'))
    saved={};monkeypatch.setattr(run,'save',lambda name,value:saved.update({name:value}))
    run.align();data=saved['dataset.json']
    assert len(data['rows'])==152 and len(data['excluded'])==2
    assert {r['id'] for r in data['rows']+data['excluded']}=={str(i) for i in range(154)}
    assert all(r['actual_label'] is None for r in data['rows']+data['excluded'])


def test_completed_stage_or_internal_mirror_cannot_be_overwritten(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'FOLDER',tmp_path/'external');monkeypatch.setattr(run,'MIRROR',tmp_path/'internal')
    run.MIRROR.mkdir();(run.MIRROR/'plan.json').write_text('{}')
    with pytest.raises(ValueError):run.new('plan.json')
