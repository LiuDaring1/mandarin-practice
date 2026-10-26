from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from fit_nasal_context_probe import matching_rule,policy_observations,grouped


def sample(expected,actual,state,split='dev',cohort='new_sentence'):
    return {'id':'target','speaker':'one','split':split,'cohort':cohort,'condition':'fixture',
            'expected_label':expected,'actual_label':actual,'api_state':state}


def test_api_conflict_vetoes_positive_but_does_not_require_api_error_for_direction():
    rows=[sample('front','back','flagged'),sample('front','back','not_flagged')]
    observed=policy_observations(rows,np.array([[.9,.1,0],[.1,.9,0]]),.5,.3)
    assert observed[0]['candidate_nasal_match'] is False
    assert observed[1]['candidate_nasal_change'] is True
    assert observed[1]['candidate_nasal_match'] is False


def test_matching_margin_does_not_accept_held_out_data():
    for split in ['train','test','transfer','holdout','validation']:
        with pytest.raises(ValueError,match='development rows only'):
            matching_rule([sample('front','front','not_flagged',split)],np.array([[.9,.1,0]]))


def test_new_evaluation_counts_do_not_include_training_or_previously_seen_targets():
    rows=[sample('front','back','not_flagged','train'),sample('front','back','not_flagged','test'),
          sample('front','back','not_flagged','test','previous')]
    observations=policy_observations(rows,np.array([[.1,.9,0]]*3),.5,.3)
    report=grouped(observations)
    assert report['new_sentence_evaluation']['targets']==1
    assert report['new_sentence_evaluation']['correct_error_directions']==1
    assert report['test']['targets']==2
