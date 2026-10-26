from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_latic_nasal_annotations import canonical,compare,read_notations


def test_only_orthographic_umlaut_and_tone_changes_normalized():
    assert canonical('qvan2')==canonical('quan4')
    assert canonical('lv4')!=canonical('lu4')
    assert canonical('lin2')!=canonical('ling2')


def test_both_nasal_directions_retain_exact_token_positions():
    rows,reason=compare(['ta1','lin2','zheng1','tian1'],['ta1','ling2','zhen1','tian2'])
    assert reason is None
    assert [(r['token_position'],r['expected_label'],r['actual_label']) for r in rows]==[(1,'front','back'),(2,'back','front'),(3,'front','front')]


@pytest.mark.parametrize('actual,reason',[
    (['lin2','lin2'],'unequal_token_count'),(['ling2','ling2','lin2'],'other_segmental_change'),
    (['lin2','<STA/>','lin2'],'unsupported_token'),(['lin2','lan2','lin2'],'other_segmental_change')])
def test_ambiguous_or_other_errors_not_zipped_as_nasal_evidence(actual,reason):
    rows,observed=compare(['lin2','tian1','lin2'],actual)
    assert rows==[] and observed==reason


def test_duplicate_ids_are_not_silently_overwritten(tmp_path):
    path=tmp_path/'annotations.txt';path.write_text('000100001 lin2\n000100001 ling2\n')
    with pytest.raises(ValueError,match='Duplicate'):read_notations(path)


def test_corpus_speaker_is_checked(tmp_path):
    path=tmp_path/'annotations.txt';path.write_text('000990001 lin2\n')
    with pytest.raises(ValueError,match='speaker'):read_notations(path)
