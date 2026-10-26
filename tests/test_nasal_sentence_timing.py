from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_nasal_sentence_timing import character_interval,compare_intervals


def test_timing_mapping_requires_exact_position_and_does_not_divide_multi_character_spans():
    items=[{'text':'心','start':.2,'end':.5},{'text':'心','start':.8,'end':1.1}]
    assert character_interval(items,'心心',1,1.2)==[.8,1.1]
    assert character_interval(items,'星心',1,1.2) is None
    assert character_interval([{'text':'心心','start':.2,'end':1.1}],'心心',1,1.2) is None
    assert character_interval(items,'心心',1,1.) is None


def test_timing_agreement_detects_different_syllables_without_claiming_correct_pronunciation():
    assert compare_intervals([.2,.5],[.25,.55])['state']=='consistent'
    assert compare_intervals([.2,.5],[.8,1.1])['state']=='timing_conflict'
    assert compare_intervals(None,[.8,1.1])['state']=='unavailable'
    assert compare_intervals([.2,.5],[.3,.3])['state']=='unavailable'
