from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from prepare_griffith_nasal_probe import annotation_label, map_nominal, auxiliary_conflict


def test_explicit_nasal_substitutions_include_both_directions_and_mark_other_changes():
    front = annotation_label('chen2', 'n{ng} T2{1}')
    back = annotation_label('wang2', 'ang{an}')
    assert (front['expected_label'], front['actual_label'], front['pure_nasal_pair']) == ('front', 'back', True)
    assert (back['expected_label'], back['actual_label'], back['pure_nasal_pair']) == ('back', 'front', True)
    broader = annotation_label('zhang1', 'ang{en}')
    assert broader['actual_label'] == 'front'
    assert broader['pure_nasal_pair'] is False


def test_undecoded_errors_and_nominal_conflicts_never_become_positive_labels():
    for error in ['*', 'en{g-}', 'reading error', 'in{g-}T4{1}', 'T3{4]']:
        assert annotation_label('sheng1', error)['state'] == 'unsupported_annotation'
    assert annotation_label('wang2', 'an{ang}')['state'] == 'unsupported_annotation'
    assert annotation_label('chen2', '', 'reading error')['state'] == 'miscellaneous_annotation'
    assert annotation_label('chen2', 'T2{1}')['state'] == 'normal_annotation'
    assert annotation_label('dianr3', '')['state'] == 'not_supported_nasal'


def test_nominal_mapping_preserves_character_position_and_refuses_repetitions_or_omission():
    items = [{'text': s} for s in ['', 'chen2', 'dong1', 'pau', 'you3', 'dianr3', 'leng3', '']]
    mapping = map_nominal(items, '陈东有点儿冷')
    assert mapping[-1]['position'] == 5
    assert mapping[-2]['char_span'] == 2
    assert map_nominal(items + [{'text': 'leng3'}], '陈东有点儿冷') is None
    assert map_nominal([{'text': 'cheng2'}], '陈') is None
    assert map_nominal([{'text': 'chen2'}], '陈东') is None


def test_secondary_annotation_cannot_be_ignored_when_primary_error_tier_is_blank():
    target = {'start': 1., 'end': 2.}
    for tier, text in [('IP', '{g-}'), ('IP', 'un{en}'), ('ST', '*'), ('unknown-tier', 'uncertain')]:
        assert auxiliary_conflict(target, '', {tier: [{**target, 'text': text}]})
    assert not auxiliary_conflict(target, '', {'IP': [{**target, 'text': 'T2{1}'}]})
    assert not auxiliary_conflict(target, 'n{ng}', {'IP': [{**target, 'text': 'n{ng} T2{1}'}]})
    assert not auxiliary_conflict(target, '', {'IP': [{'start': 2., 'end': 3., 'text': '{g-}'}]})
