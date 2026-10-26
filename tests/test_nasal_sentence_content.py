from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_nasal_sentence_content import fold_nasal,locate_targets


def test_nasal_confusion_is_allowed_for_location_but_not_turned_into_a_label():
    assert fold_nasal('xin')==fold_nasal('xing')
    assert fold_nasal('cong')=='cong'
    result=locate_targets([fold_nasal('xin')],[fold_nasal('xing')])
    assert result['targets'][0]['state']=='unique_match'
    assert 'correct' not in result['targets'][0]


def test_repeated_token_with_possible_omission_has_no_guessed_position():
    result=locate_targets(['neng','neng'],['neng'])
    assert [r['state'] for r in result['targets']]==['ambiguous','ambiguous']
    assert all(r['deletion_is_optimal'] for r in result['targets'])


def test_context_anchor_and_missing_target_remain_distinct():
    result=locate_targets(['wo','xin','ni','xin'],['wo','xin','ni','xin'])
    assert result['targets'][3]['possible_observed_positions']==[3]
    assert result['targets'][3]['state']=='unique_match'
    result=locate_targets(['wo','xin','ni'],['wo','ni'])
    assert result['targets'][1]['state']=='not_matched'
    assert result['targets'][1]['deletion_is_optimal']
    assert all(r['state']=='not_matched' for r in locate_targets(['xin'],[])['targets'])
