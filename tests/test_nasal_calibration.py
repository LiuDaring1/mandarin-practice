import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from report_nasal_calibration import completed_rows, consensus


def row(**updates):
    window = {'state':'observed', 'best_token':'ang', 'opposite':'ang',
              'decoded_tokens':['ang'], 'best_minus_runner_up':2.0}
    window.update(updates)
    return {'ise_observation':{'state':'flagged'}, 'windows':{'syllable_0.0':window}}


def test_consensus_requires_api_and_specific_decoded_counterpart():
    assert consensus(row(), 1)
    assert not consensus(row(), 3)
    assert not consensus(row(best_token='iang'))
    assert not consensus(row(decoded_tokens=['a','ang']))
    assert not consensus(row(state='unknown'))
    candidate = row()
    candidate['ise_observation']['state'] = 'not_flagged'
    assert not consensus(candidate)


def test_incomplete_and_duplicate_reports_cannot_be_summarized(tmp_path):
    path = tmp_path/'report.json'
    path.write_text(json.dumps({'complete':False, 'cases':[]}))
    with pytest.raises(ValueError, match='unfinished'):
        completed_rows(path)
    path.write_text(json.dumps({'complete':True, 'cases':[{'id':'same'},{'id':'same'}]}))
    with pytest.raises(ValueError, match='Duplicate'):
        completed_rows(path)
