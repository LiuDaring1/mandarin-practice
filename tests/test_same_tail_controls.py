import pytest

from prepare_same_tail_controls import same_tail_label,targets_for_record


@pytest.mark.parametrize('nominal,error,actual,label',[
    ('dun2','un{en}','den','front'),('zhang1','ang{eng}','zheng','back'),
    ('lun2','un{en} T2{3}','len','front'),('yuan2','uan{un}','yun','front'),
    ('peng2','eng{ing}','ping','back'),('chen2','en{in}','chin','front')])
def test_explicit_other_errors_preserve_only_nasal_class(nominal,error,actual,label):
    row=same_tail_label(nominal,error)
    assert row['actual_pinyin']==actual and row['actual_label']==row['expected_label']==label
    assert not row['whole_pronunciation_correct'] and row['evaluation_only']


@pytest.mark.parametrize('nominal,error',[
    ('chen2','n{ng}'),('wang2','ang{an}'),('chen2','en{ei}'),('hao3','ao{ou}'),
    ('chen2',''),('chen2','T2{1}'),('chen2','en{en}'),('chen2','in{en}'),
    ('chen2','en{g-}'),('chen2','en{in} *'),('dianr3','an{en}')])
def test_confusions_missing_nasal_uncertain_and_no_change_are_not_controls(nominal,error):
    assert same_tail_label(nominal,error) is None


def test_miscellaneous_annotation_blocks_label():
    assert same_tail_label('dun2','un{en}','uncertain') is None


def record(error='un{en}',extra=None):
    base={'start':0.,'end':1.}
    tiers={'NP':[{**base,'text':'dun2'}],'ER':[{**base,'text':error}],'Misc':[{**base,'text':''}]}
    if extra is not None:tiers['IP']=[{**base,'text':extra}]
    return {'tiers':tiers}


def test_whole_sequence_and_cross_tier_consistency_required():
    rows,reason=targets_for_record(record(extra='un{en}'),'顿')
    assert reason is None and len(rows)==1 and rows[0]['position']==0
    assert targets_for_record(record(),'顿顿')[0]==[]
    assert targets_for_record(record(extra='un{eng}'),'顿')[0]==[]
    broken=record();broken['tiers']['ER'][0]['end']=1.2
    assert targets_for_record(broken,'顿')[0]==[]


def test_ambiguous_error_tiers_are_not_used():
    r=record();r['tiers']['EI']=r['tiers']['ER']
    assert targets_for_record(r,'顿')[1]=='sequence_or_tier_mismatch'
