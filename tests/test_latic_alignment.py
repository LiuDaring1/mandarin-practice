from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_latic_alignment import inventory,unique_mapping


def test_insertion_does_not_shift_nasal_target():
    targets,excluded,_,reason=inventory(['wo3','xin1','hao3'],['a1','wo3','xing1','hao3'])
    assert reason is None and not excluded
    assert targets[0]['token_position']==1 and targets[0]['actual_token_position']==2
    assert targets[0]['expected_label']=='front' and targets[0]['actual_label']=='back'


def test_other_segmental_errors_elsewhere_do_not_discard_unique_target():
    targets,excluded,_,reason=inventory(['wo3','xing1','hao3'],['wo3','xin1','gao3'])
    assert reason is None and not excluded
    assert targets[0]['state']=='pure_nasal_substitution_notation'


def test_deleted_target_is_not_invented_from_neighbor():
    targets,excluded,_,_=inventory(['wo3','xin1','hao3'],['wo3','hao3'])
    assert not targets and excluded[0]['reason']=='deleted_or_ambiguous_alignment'


def test_repeated_tokens_preserve_alignment_ambiguity():
    mapping,_=unique_mapping(['xin1','xin1'],['xing1'])
    assert mapping==[None,None]


def test_insertion_between_repetitions_is_ambiguous():
    mapping,_=unique_mapping(['xin1'],['xin1','xin1'])
    assert mapping==[None]


def test_local_ambiguity_does_not_discard_unique_other_target():
    mapping,_=unique_mapping(['a1','a1','wo3','xin1','hao3'],['a1','wo3','xing1','hao3'])
    assert mapping==[None,None,1,2,3]


def test_substitution_adjacent_to_insertion_is_not_assumed_unique():
    targets,excluded,_,_=inventory(['wo3','xin1','hao3'],['wo3','a1','xing1','hao3'])
    assert not targets and excluded[0]['reason']=='deleted_or_ambiguous_alignment'


def test_neighboring_repeat_deletion_can_make_target_substitution_ambiguous():
    assert unique_mapping(['a1','a1','xin1','hao3'],['a1','xing1','hao3'])[0]==[None,None,None,2]


def test_initial_substitution_is_not_pure_nasal_or_normal():
    targets,excluded,_,_=inventory(['shan1'],['san1'])
    assert not targets and excluded[0]['reason']=='other_segmental_change'


def test_tone_only_change_and_umlaut_convention_are_not_coda_errors():
    targets,excluded,_,_=inventory(['xvn1','xiang1'],['xun2','xiang3'])
    assert not excluded and len(targets)==2
    assert all(t['state']=='normal_notation' for t in targets)


def test_unclear_phonetic_token_keeps_utterance_outside_inventory():
    targets,excluded,cost,reason=inventory(['xin1'],['<unk>'])
    assert not targets and not excluded and cost is None and reason=='unsupported_token'


@pytest.mark.parametrize('left,right,expected',[([],[],[]),(['xin1'],[],[None]),([],['xin1'],[])])
def test_empty_sequences(left,right,expected):
    assert unique_mapping(left,right)[0]==expected


def test_optimal_mapping_matches_independent_exhaustive_edit_paths():
    from itertools import product
    def paths(left,right,i=0,j=0):
        if i==len(left) and j==len(right): return [(0,())]
        result=[]
        if i<len(left): result += [(1+cost,(None,)+mapping) for cost,mapping in paths(left,right,i+1,j)]
        if j<len(right): result += [(1+cost,mapping) for cost,mapping in paths(left,right,i,j+1)]
        if i<len(left) and j<len(right):
            result += [(int(left[i]!=right[j])+cost,(j,)+mapping) for cost,mapping in paths(left,right,i+1,j+1)]
        return result
    sequences=[list(items) for length in range(4) for items in product(['xin1','xing1'],repeat=length)]
    for left in sequences:
        for right in sequences:
            exhaustive=paths(left,right);best=min(cost for cost,_ in exhaustive)
            optimal=[mapping for cost,mapping in exhaustive if cost==best]
            expected=[]
            for i in range(len(left)):
                options={mapping[i] for mapping in optimal}
                expected.append(next(iter(options)) if len(options)==1 and None not in options else None)
            assert unique_mapping(left,right)==(expected,best)
