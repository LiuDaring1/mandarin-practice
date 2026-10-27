import pytest

from probe_ise_pinyin_challenge import dictionary_bodies, merged_decision, select_challenge


def normal(id='n',state='flagged',source='published_consensus_no_segmental_error'):
    return {'id':id,'state':'normal_annotation','api_state':state,'label_source':source,
            'actual_label':'front','expected_label':'front'}


def mixed(id='e',pure=False):
    return {'id':id,'state':'nasal_substitution','api_state':'not_flagged',
            'label_source':'explicit_suffix_substitution','pure_nasal_pair':pure,
            'actual_label':'back','expected_label':'front'}


def test_selection_uses_stated_challenge_conditions_not_model_predictions():
    rows=[normal(),mixed(),normal('easy','not_flagged'),normal('weak',source='unverified'),mixed('pure',True)]
    got=select_challenge(rows)
    assert [r['id'] for r in got]==['e','n']
    assert [r['role'] for r in got]==['error','normal']
    assert select_challenge([{**r,'predicted':'other'} for r in rows])[0]['id']=='e'


def test_duplicate_challenge_is_rejected():
    with pytest.raises(ValueError):select_challenge([normal(),normal()])


@pytest.mark.parametrize('api,local,want',[
    ('change','change','change'),('change','unknown','change'),('unknown','change','change'),
    ('change','match','unknown'),('match','change','unknown'),('match','match','match'),
    ('match','unknown','unknown'),('unknown','match','unknown'),('unknown','unknown','unknown')])
def test_correction_union_conflicts_abstain_and_matches_require_both(api,local,want):
    assert merged_decision(api,local,'correction_union')==want


@pytest.mark.parametrize('api,local',[(a,b) for a in ('change','match','unknown') for b in ('change','match','unknown')])
def test_agreement_and_single_source_controls_are_exact(api,local):
    assert merged_decision(api,local,'agreement')==(api if api==local else 'unknown')
    assert merged_decision(api,local,'api')==api
    assert merged_decision(api,local,'local')==local


@pytest.mark.parametrize('a,b,mode',[('bad','match','api'),('match','bad','local'),('match','match','bad')])
def test_unknown_decision_or_policy_rejected(a,b,mode):
    with pytest.raises(ValueError):merged_decision(a,b,mode)


def test_dictionary_guard_distinguishes_spelling_from_supported_api_behavior():
    bodies=dictionary_bodies()
    assert {'lin','ling','xian','xiang','guan','guang','lv'}<=set(bodies)
    assert 'biang' not in bodies
    # Rare len is in this dictionary but the preceding API test rejected one
    # such reference: dictionary membership cannot imply provider support.
    assert 'len' in bodies
