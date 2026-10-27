from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from hubert_boundary_diagnostic import condition_bounds


def rows():
    return [{'id':str(i),'speaker':'s1','position':i,'actual_label':'front','expected_label':'back',
             'audio_sha256':'fixed-recording','bounds':{'syllable':[i,i+1],'vowel':[i+.2,i+.9]}} for i in range(3)]


def test_identity_join_keeps_reordered_boundary_rows_and_exclusions():
    current=rows();changed=deepcopy(current)
    changed[2]['bounds']={'syllable':[2.1,2.9],'vowel':[2.2,2.8]}
    result=condition_bounds(current,{'rows':[changed[2],changed[0]],'excluded':[changed[1]]})
    assert set(result)=={'0','2'} and result['2']==changed[2]['bounds']
    assert current[2]['bounds']!=result['2']


@pytest.mark.parametrize('key,value',[('speaker','s2'),('position',5),('audio_sha256','other-recording'),('actual_label','back'),('expected_label','front')])
def test_changed_audio_speaker_position_or_label_is_not_joined(key,value):
    current=rows();other=deepcopy(current);other[1][key]=value
    with pytest.raises(ValueError,match='conflict'):condition_bounds(current,{'rows':other,'excluded':[]})


def test_excluded_targets_still_have_identity_checked():
    current=rows();other=deepcopy(current);other[1]['actual_label']='other'
    with pytest.raises(ValueError,match='conflict'):condition_bounds(current,{'rows':[other[0],other[2]],'excluded':[other[1]]})


@pytest.mark.parametrize('case',['duplicate_current','duplicate_available','overlap','missing','extra','duplicate_excluded'])
def test_no_silent_target_loss_or_duplicated_denominator(case):
    current=rows();other={'rows':deepcopy(current),'excluded':[]}
    if case=='duplicate_current':current.append(deepcopy(current[0]))
    if case=='duplicate_available':other['rows'].append(deepcopy(current[0]))
    if case=='overlap':other['excluded'].append(deepcopy(current[0]))
    if case=='missing':other['rows'].pop()
    if case=='extra':other['rows'].append({**current[0],'id':'new'})
    if case=='duplicate_excluded':other={'rows':[current[0],current[2]],'excluded':[current[1],deepcopy(current[1])]}
    with pytest.raises(ValueError,match='membership'):condition_bounds(current,other)
