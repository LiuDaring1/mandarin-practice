import pytest

from ise_interphonic_preflight import check_ledger, inspect_reference, interphonic_word
from ise_probe import public_result


def response(symbol='lin2', chars=('林', '业'), rejection='false', final_error='0'):
    return public_result({'status': 'ok', 'xml': (
        f'<read_word is_rejected="{rejection}"><word>'
        f'<syll content="{chars[0]}" symbol="{symbol}" rec_node_type="paper" dp_message="0">'
        f'<phone content="in" is_yun="1" dp_message="0" perr_msg="{final_error}"/>'
        '</syll>'
        f'<syll content="{chars[1]}" symbol="ye4" rec_node_type="paper" dp_message="0"/>'
        '</word></read_word>')})


def test_explicit_pinyin_changes_without_hanzi_change():
    assert interphonic_word('林业', ['lin2', 'ye4']) == '<customizer: interphonic>\n林业\nlin2|ye4'
    assert interphonic_word('林业', ['ling2', 'ye4']).splitlines()[1] == '林业'


@pytest.mark.parametrize('text,syllables', [('林业', ['lin2']), ('林1', ['lin2', 'yi1']),
    ('林\n业', ['lin2', 'ye4']), ('', []), ('林业', ['lin', 'ye4']),
    ('林业', ['lin2|ling2', 'ye4'])])
def test_reject_bad_payload_before_calls(text, syllables):
    with pytest.raises(ValueError):
        interphonic_word(text, syllables)


def test_reference_match_is_not_recognized_pronunciation():
    r = inspect_reference(response(symbol='ling2', final_error='1'), '林业', ['ling2', 'ye4'])
    assert r['reference_honored'] and r['state'] == 'flagged'
    assert not r['recognized_pronunciation_available']


def test_ignored_override_is_not_scored():
    r = inspect_reference(response(), '林业', ['ling2', 'ye4'])
    assert not r['reference_honored'] and r['state'] == 'reference_mismatch'
    assert not r['target_observation']['finals']


@pytest.mark.parametrize('r', [response(chars=('林', '林')), response(chars=('业', '林'))])
def test_full_character_sequence_required(r):
    assert not inspect_reference(r, '林业', ['lin2', 'ye4'])['reference_honored']


def test_rejection_is_preserved_even_when_reference_honored():
    r = inspect_reference(response(rejection='true'), '林业', ['lin2', 'ye4'])
    assert r['reference_honored'] and r['state'] == 'rejected'


def test_provider_failure_not_reference_match():
    r = inspect_reference({'status': 'provider_error'}, '林业', ['lin2', 'ye4'])
    assert r == {'state': 'unavailable', 'reference_honored': False}


@pytest.mark.parametrize('ledger', [[], ['changed'], ['a', 'other'], ['a', 'b', 'b'], ['a', 'b', 'c', 'd']])
def test_ledger_cannot_reset_retry_or_exceed_frozen_batch(ledger):
    with pytest.raises(ValueError):
        check_ledger(['a'], ledger, ['b', 'c'])


def test_ledger_accepts_only_frozen_append():
    assert check_ledger(['a'], ['a', 'b', 'c'], ['b', 'c']) == 2
