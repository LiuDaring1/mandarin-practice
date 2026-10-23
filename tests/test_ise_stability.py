"""Prevent score/phoneme ambiguities from becoming false diagnostic evidence."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from ise_probe import public_result
from validate_ise_stability import target_observation

@pytest.mark.parametrize('error,alignment,state',[
    ('0','0','not_flagged'),('1','0','flagged'),('2','0','not_flagged'),
    ('3','0','flagged'),('0','128','flagged'),('128','128','flagged'),
    ('16','16','unusable_alignment'),('128','0','unusable_alignment')])
def test_target_fields_not_confused_with_tone_or_missing(error,alignment,state):
    result={'status':'ok','nodes':[{'tag':'phone','is_yun':'1','word_content':'零','perr_msg':error,'dp_message':alignment}]}
    assert target_observation(result,'零')['state']==state

def test_multi_character_word_uses_syllable_identity():
    result=public_result({'status':'ok','xml':'<read_word><word content="零件"><syll content="零" symbol="ling2"><phone content="ing" is_yun="1" perr_msg="0" dp_message="0"/></syll><syll content="件"><phone content="ian" is_yun="1" perr_msg="1" dp_message="0"/></syll></word></read_word>'})
    observed=target_observation(result,'零')
    assert observed['state']=='not_flagged'
    assert len(observed['finals'])==1 and observed['finals'][0]['syll_symbol']=='ling2'

def test_rejection_missing_and_duplicate_are_not_correct():
    assert target_observation({'status':'provider_error'},'零')['state']=='unavailable'
    assert target_observation({'status':'ok','nodes':[]},'零')['state']=='ambiguous_target'
    assert target_observation({'status':'ok','nodes':[{'is_rejected':'true'}]},'零')['state']=='rejected'
    n={'is_yun':'1','word_content':'零','perr_msg':'0','dp_message':'0'}
    assert target_observation({'status':'ok','nodes':[n,n]},'零')['state']=='ambiguous_target'
