import pytest

from probe_same_tail_specificity import stage_budget, summary, validate_controls


def records():
    return [{'uid':'r','split':'external','targets':[{
        'position':0,'state':'same_tail_segmental_error',
        'label_source':'explicit_suffix_same_nasal_class',
        'actual_label':'front','expected_label':'front',
        'whole_pronunciation_correct':False,'evaluation_only':True}]}]


def test_controls_are_not_promoted_to_correct_words():
    assert validate_controls(records()) == {'r-pos0'}


@pytest.mark.parametrize('key,value',[
    ('state','normal_annotation'),('label_source','unverified'),
    ('actual_label','back'),('actual_label','other'),
    ('whole_pronunciation_correct',True),('evaluation_only',False)])
def test_corrupted_or_overstated_control_label_rejected(key,value):
    rows=records();rows[0]['targets'][0][key]=value
    with pytest.raises(ValueError):validate_controls(rows)


@pytest.mark.parametrize('change',['train','empty','duplicate'])
def test_training_empty_and_duplicate_controls_rejected(change):
    rows=records()
    if change=='train':rows[0]['split']='train'
    elif change=='empty':rows[0]['targets']=[]
    else:rows+=records()
    with pytest.raises(ValueError):validate_controls(rows)


def request(key='a',reference='字'):
    return {'audio':'fake.wav','reference':reference,'core':'read_sentence','key':key}


def test_budget_deduplicates_and_reuses_cached_failure_without_retry(tmp_path):
    (tmp_path/'a.json').write_text('{"status":"provider_error","code":48195}')
    got=stage_budget([request(),request(),request('b')],['a'],tmp_path)
    assert got['new_request_keys']==['b']
    assert got['maximum_total_attempts']==2 and got['maximum_additional_attempts']==1
    assert len(got['existing_caches'])==1 and len(got['requests'])==2


def test_reserved_missing_response_cannot_be_requested_again(tmp_path):
    with pytest.raises(ValueError,match='no retry'):
        stage_budget([request()],['a'],tmp_path)


def test_request_identity_collision_rejected(tmp_path):
    with pytest.raises(ValueError,match='Conflicting'):
        stage_budget([request(),request(reference='另')],[],tmp_path)


def test_per_stage_budget_is_bounded(tmp_path):
    with pytest.raises(ValueError,match='allowance'):
        stage_budget([request(str(i)) for i in range(101)],[],tmp_path)


def test_summary_retains_unknowns_and_only_reports_nasal_class_matches():
    got=summary([{'id':str(i),'expected_label':group,'decision':decision}
        for i,(group,decision) in enumerate([('front','change'),('front','unknown'),('back','match')])])
    assert got['all']=={'targets':3,'false_nasal_changes':1,'nasal_class_matches':1,'unknown':1,
                        'whole_word_correctness_assessed':False}
    assert got['back']['nasal_class_matches']==1 and got['front']['unknown']==1


@pytest.mark.parametrize('bad',['duplicate','unknown'])
def test_summary_rejects_silent_denominator_or_decision_change(bad):
    rows=[{'id':'a','expected_label':'front','decision':'match'}]
    if bad=='duplicate':rows+=rows
    else:rows[0]['decision']='correct_word'
    with pytest.raises(ValueError):summary(rows)
