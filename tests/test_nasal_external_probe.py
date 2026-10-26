from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from evaluate_nasal_external_probe import content_gate


def test_ambiguous_content_vetoes_both_claims_without_manufacturing_a_nasal_label():
    for original in [dict(candidate_nasal_change=True, candidate_nasal_match=False, predicted='back'),
                     dict(candidate_nasal_change=False, candidate_nasal_match=True, predicted='front')]:
        for state in ('ambiguous', 'not_matched', 'unavailable'):
            gated = content_gate(original, state)
            assert gated['candidate_nasal_change'] is False
            assert gated['candidate_nasal_match'] is False
            assert gated['predicted'] == original['predicted']
        gated = content_gate(original, 'unique_match')
        assert gated['candidate_nasal_change'] == original['candidate_nasal_change']
        assert gated['candidate_nasal_match'] == original['candidate_nasal_match']
