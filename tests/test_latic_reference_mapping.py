from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from latic_reference_mapping import map_reference


def test_repeated_hanzi_keep_distinct_token_and_raw_text_positions():
    values=map_reference('新，新闻。',['xin1','xin1','wen2'])
    assert [v['char'] for v in values]==['新','新','闻']
    assert [v['position'] for v in values]==[0,1,2]
    assert [v['raw_text_position'] for v in values]==[0,2,3]


def test_heteronym_reference_is_accepted_without_changing_requested_reading():
    values=map_reference('银行',['yin2','hang2'])
    assert values[1]['expected_pinyin']=='hang'


@pytest.mark.parametrize('text',['2026年','A年','一😊年'])
def test_numbers_latin_and_symbols_are_not_silently_dropped(text):
    with pytest.raises(ValueError,match='Unsupported'):map_reference(text,['nian2'])


@pytest.mark.parametrize('text,tokens',[('新闻',['xin1']),('新',['xin1','wen2']),('',[])])
def test_nonbijective_counts_are_rejected(text,tokens):
    with pytest.raises(ValueError,match='count'):map_reference(text,tokens)


def test_same_length_incorrect_character_sequence_is_rejected():
    with pytest.raises(ValueError,match='conflict'):map_reference('星闻',['xin1','wen2'])


def test_punctuation_and_space_do_not_create_phonetic_positions():
    values=map_reference('「新」\n 闻！',['xin1','wen2'])
    assert [(r['position'],r['raw_text_position']) for r in values]==[(0,1),(1,5)]


def test_unsupported_phonetic_token_does_not_get_guessed():
    with pytest.raises(ValueError,match='token'):map_reference('新',['unknown'])
