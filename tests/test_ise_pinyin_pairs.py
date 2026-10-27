import pytest

from probe_ise_pinyin_pairs import compare_pair, opposite_pinyin, select_controls, summarize
from continue_ise_pinyin_pairs import permitted_format_failure
from resume_ise_pinyin_pairs import input_failure


@pytest.mark.parametrize('left,right', [('lin2','ling2'),('sheng1','shen1'),('wang2','wan2'),('guan1','guang1')])
def test_nasal_swap_preserves_initial_vowel_tone_and_is_reversible(left,right):
    assert opposite_pinyin(left) == right
    assert opposite_pinyin(right) == left


@pytest.mark.parametrize('value', ['lin', 'lín', 'lian2|liang2', 'hao3', 'lin2\n'])
def test_bad_or_noncontrast_pinyin_rejected(value):
    with pytest.raises(ValueError): opposite_pinyin(value)


def observation(state, bounds=(1.,1.4)):
    return {'state': state, 'bounds': {'syllable': list(bounds)}}


@pytest.mark.parametrize('a,b,want', [('flagged','not_flagged','change'),('not_flagged','flagged','match'),
    ('flagged','flagged','unknown'),('not_flagged','not_flagged','unknown')])
def test_differential_rule_does_not_treat_same_flags_as_correct(a,b,want):
    assert compare_pair(observation(a),observation(b))['decision'] == want


@pytest.mark.parametrize('bad', [{}, {'state':'rejected'}, {'state':'not_flagged','bounds':None}])
def test_unknown_or_rejected_cannot_produce_feedback(bad):
    assert compare_pair(bad,observation('flagged'))['decision'] == 'unknown'


def test_reference_dependent_alignment_abstains():
    result = compare_pair(observation('flagged'), observation('not_flagged',(1.5,1.9)))
    assert result['reason'] == 'reference_dependent_alignment' and result['decision'] == 'unknown'


def test_control_selection_is_deterministic_and_does_not_consult_api():
    common = {'expected_final':'en','nominal_pinyin':'chen2','reference':'陈东','speaker':'A'}
    error = {**common,'id':'error','pure_nasal_pair':True,'state':'nasal_substitution'}
    normals = [{**common,'id':str(i),'state':'normal_annotation','label_source':'published_consensus_no_segmental_error',
                'api_state':'not_flagged'} for i in range(4)]
    selected = select_controls([error]+normals)
    changed = [{**r,'api_state':'flagged'} for r in [error]+normals]
    assert [r['id'] for r in selected] == [r['id'] for r in select_controls(changed[::-1])]
    assert len(selected)==3 and len({r['id'] for r in selected})==3


def test_no_silent_unmatched_control_fallback():
    with pytest.raises(ValueError):
        select_controls([{'id':'error','pure_nasal_pair':True,'state':'nasal_substitution','expected_final':'en'}])


def test_summary_retains_unknowns_and_both_directions():
    rows = [{'role':'error','expected_label':'back','plain_state':'not_flagged','pair':{'decision':'unknown'}},
            {'role':'normal','expected_label':'front','plain_state':'flagged','pair':{'decision':'change'}}]
    result = summarize(rows)
    assert result['error_back']['targets']==result['error_back']['unknown']==1
    assert result['normal_front']['change']==1 and result['error_front']['targets']==0


@pytest.mark.parametrize('result', [{'status':'provider_error','code':11201},
    {'status':'provider_error','code':11200}, {'status':'transport_error','error_type':'TimeoutError'},
    {'status':'provider_error','code':10139}, {'status':'provider_error','code':'48195'}])
def test_continuation_cannot_swallow_quota_auth_network_or_unknown_errors(result):
    assert not permitted_format_failure(result)


def test_only_recorded_reference_format_error_can_be_retained_and_passed():
    assert permitted_format_failure({'status':'provider_error','code':48195})


@pytest.mark.parametrize('code',[48195,60114])
def test_recovery_keeps_known_per_request_failures(code):
    assert input_failure({'status':'provider_error','code':code})


@pytest.mark.parametrize('result',[{'status':'provider_error','code':11201},
    {'status':'provider_error','code':11200},{'status':'transport_error'},
    {'status':'provider_error','code':10139},{'status':'provider_error','code':'60114'}])
def test_recovery_still_stops_global_unknown_or_transport_errors(result):
    assert not input_failure(result)
