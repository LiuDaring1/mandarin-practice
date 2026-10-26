from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from audit_nasal_pooling_boundaries import tail_coverage


def test_syllable_overlap_does_not_hide_tail_frames_pooled_after_target_ends():
    result = tail_coverage({'syllable': [0., .6], 'vowel': [.38, .6]}, [.296, .52], 16000)
    assert result['frames'] == 6
    assert result['frames_in_human_syllable'] == 2
    assert result['outside_fraction'] > .5
    inside = tail_coverage({'syllable': [.2, .6], 'vowel': [.3, .5]}, [.2, .6], 16000)
    assert inside['outside_fraction'] == 0
