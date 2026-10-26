from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from ise_probe import public_result, target_at


def sample(second_error='1', second_alignment='0'):
    return public_result({'status':'ok','xml':f'''<read_sentence><word content="人人">
      <syll content="sil" rec_node_type="sil"/>
      <syll content="人" rec_node_type="paper"><phone is_yun="1" content="en" dp_message="0" perr_msg="0"/></syll>
      <syll content="人" rec_node_type="paper"><phone is_yun="1" content="en" dp_message="{second_alignment}" perr_msg="{second_error}"/></syll>
      </word></read_sentence>'''})


def test_repeated_character_is_located_by_complete_sequence_and_position():
    result = sample()
    assert target_at(result, '人人。', 0)['state'] == 'not_flagged'
    assert target_at(result, '人人。', 1)['state'] == 'flagged'
    assert target_at(result, '人人。', 1)['finals'][0]['syll_index'] == 1


def test_missing_changed_or_extra_reference_character_disables_mapping():
    result = sample()
    for text in ['人', '人林', '人人人']:
        assert target_at(result, text, 0)['state'] == 'unusable_alignment'
    assert target_at(result, '人人', 2)['state'] == 'unusable_alignment'


def test_omitted_or_tone_only_syllable_is_not_nasal_mispronunciation():
    assert target_at(sample('16','16'), '人人', 1)['state'] == 'unusable_alignment'
    assert target_at(sample('2'), '人人', 1)['state'] == 'not_flagged'


def test_parent_omission_is_not_overruled_by_phone_fields():
    result = public_result({'status':'ok', 'xml': '''<read_sentence><word content="人">
    <syll content="人" rec_node_type="paper" dp_message="16" beg_pos="10" end_pos="20">
    <phone is_yun="1" content="en" dp_message="0" perr_msg="0" beg_pos="12" end_pos="20"/>
    </syll></word></read_sentence>'''})
    observation = target_at(result, '人', 0)
    assert observation['state'] == 'unusable_alignment'
    assert observation['finals'][0]['syll_beg_pos'] == '10'
    assert observation['finals'][0]['syll_end_pos'] == '20'
