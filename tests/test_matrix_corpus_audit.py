import pytest

from audit_matrix_corpus import candidate_text, inventory


def test_missing_pairs_stay_in_expected_inventory():
    result = inventory(['SF01_CMN', 'SF01_CMN/Plain', 'SF01_CMN/Plain/00000.wav',
        'SF01_CMN/Plain/11111.wav', 'SF01_CMN/Lombard/00000.wav',
        'SM01_CMN/Plain/11111.wav', 'icra1.wav',
        'SF01_CMN/Plain/finalnoise_short_F01_Plain.wav'])
    assert result['expected_sentence_recordings'] == 8
    assert result['available_sentence_recordings'] == 4
    assert len(result['missing_recordings']) == 4
    assert result['by_group']['SM01_CMN/Lombard'] == 0
    assert len(result['auxiliary_audio']) == 2
    assert not result['human_actual_phone_annotations_imported']
    assert not result['filename_to_text_verified']
    assert not result['diagnostic_accuracy_measured']


@pytest.mark.parametrize('name', ['../SF01_CMN/Plain/00000.wav', '/absolute.wav',
    'SF01_CMN//Plain/00000.wav', 'SF01_CMN/Plain/unexpected.wav',
    'SF01_CMN\\Plain\\00000.wav'])
def test_unclassified_or_unsafe_path_is_rejected(name):
    with pytest.raises(ValueError):
        inventory([name])


def test_duplicate_or_empty_inventory_is_rejected():
    name = 'SF01_CMN/Plain/00000.wav'
    with pytest.raises(ValueError):
        inventory([name, name])
    with pytest.raises(ValueError):
        inventory(['icra1.wav'])


def test_candidate_decoder_preserves_leading_zero_and_column_order():
    table = [[f'{row}:{col};' for col in range(5)] for row in range(10)]
    assert candidate_text('00152', table) == '0:0;0:1;1:2;5:3;2:4;'
    for bad in ('0152', '00x52', '000000'):
        with pytest.raises(ValueError):
            candidate_text(bad, table)
    with pytest.raises(ValueError):
        candidate_text('00152', table[:-1])
