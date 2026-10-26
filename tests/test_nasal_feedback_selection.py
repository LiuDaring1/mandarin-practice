from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from select_nasal_feedback_probe import fit_candidates, review_rule
from evaluate_nasal_feedback_probe import validate_holdout
from audit_nasal_feedback_conflicts import veto_conflict


def row(expected, actual, split='dev'):
    return {'id':'sample', 'speaker':'person', 'condition':'fixture', 'split':split,
            'expected_label':expected, 'actual_label':actual}


def test_review_selection_requires_both_directions_and_does_not_ignore_false_accusations():
    rows = [row('front','back'), row('front','back'), row('back','front'), row('front','front')]
    scores = np.array([[.1,.9,0], [.1,.9,0], [.9,.1,0], [.9,.1,0]])
    best, _ = review_rule(rows, scores)
    assert best['correct_error_directions'] == 3
    assert best['directions_by_expected'] == {'front':2, 'back':1}
    scores[-1] = [.1,.9,0]  # A false accusation with the same confidence as errors.
    assert review_rule(rows,scores)[0] is None
    assert review_rule([row('front','back')]*3,scores[:3])[0] is None


def test_held_out_rows_cannot_select_feedback_policy():
    for split in ['train','test','transfer']:
        with pytest.raises(ValueError,match='development rows only'):
            review_rule([row('front','back',split)],np.zeros((1,3)))
    for split in ['test','transfer']:
        with pytest.raises(ValueError,match='cannot receive'):
            fit_candidates(np.zeros((1,4,4,2)),[row('front','back',split)],'fixture')


def test_new_recording_of_fitting_speaker_is_not_an_independent_holdout():
    original=[{'speaker':'trained','split':'train'},{'speaker':'tuned','split':'dev'},
              {'speaker':'not-used','split':'test'}]
    for speaker in ['trained','tuned']:
        with pytest.raises(ValueError,match='shares a fitting/development speaker'):
            validate_holdout([{'speaker':speaker,'split':'holdout'}],original)
    validate_holdout([{'speaker':'not-used','split':'holdout'}],original)
    with pytest.raises(ValueError,match='holdout rows only'):
        validate_holdout([{'speaker':'new','split':'train'}],original)


def test_conflict_audit_only_removes_positive_claims_and_preserves_the_frozen_observation():
    observation={'candidate_nasal_match':True,'candidate_nasal_change':False,'predicted':'back'}
    for state in ['flagged','unavailable','ambiguous_target','unusable_alignment']:
        result=veto_conflict(observation,state)
        assert result['candidate_nasal_match'] is False
        assert result['candidate_nasal_change'] is False
        assert result['predicted']=='back'
    assert observation['candidate_nasal_match'] is True
    assert veto_conflict(observation,'not_flagged')['candidate_nasal_match'] is True
    assert veto_conflict({**observation,'candidate_nasal_match':False},'not_flagged')['candidate_nasal_match'] is False
