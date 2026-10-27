"""Map public LATIC reference tokens to Hanzi without guessing expansions."""
import unicodedata

from pypinyin import Style, pinyin

from audit_latic_nasal_annotations import canonical


def is_hanzi(char):
    code = ord(char)
    return 0x3400 <= code <= 0x4dbf or 0x4e00 <= code <= 0x9fff or 0x20000 <= code <= 0x323af


def map_reference(text, tokens):
    """Reject ambiguous counts or reference-reading conflicts for the whole row.

    This validates the written reference, not what a speaker actually said.
    Punctuation and whitespace are skipped; numbers/Latin/symbols are not
    silently expanded or dropped. Retain raw-text and Hanzi-only positions.
    """
    characters = []
    for index,char in enumerate(text):
        if is_hanzi(char):
            characters.append((index,char))
        elif not (char.isspace() or unicodedata.category(char).startswith('P')):
            raise ValueError('Unsupported reference character')
    if len(characters)!=len(tokens) or not tokens:
        raise ValueError('Reference Hanzi/token count mismatch')
    result = []
    for position,((raw_position,char),token) in enumerate(zip(characters,tokens)):
        expected = canonical(token)
        possibilities = {canonical(value+'5') for value in pinyin(char,style=Style.NORMAL,heteronym=True)[0]}
        if expected not in possibilities:
            raise ValueError('Reference character/pronunciation conflict')
        result.append({'token_position':position,'position':position,'raw_text_position':raw_position,
                       'char':char,'expected_pinyin':expected})
    return result
