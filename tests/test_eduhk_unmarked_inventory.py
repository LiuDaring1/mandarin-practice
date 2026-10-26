from pathlib import Path
import sys

from lxml import html
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from inventory_eduhk_unmarked import marked_positions, select_candidates


def test_annotations_do_not_shift_positions_and_any_color_excludes_target():
    node = html.fromstring('<span>新<span>星</span><font color="red">星读成新</font>新<font color="blue">轻声</font>星。</span>')
    chars, positions = marked_positions(node)
    assert chars=='新星新星'
    assert positions=={1, 2}


def test_annotation_before_first_character_is_not_silently_ignored():
    with pytest.raises(ValueError, match='preceding target'):
        marked_positions(html.fromstring('<span><font>错误</font>新</span>'))


def candidates():
    return [{'id': str(i), 'speaker': 'eduhk:1', 'split': 'train', 'expected_final': final}
            for i, final in enumerate(['an']*4+['ang']*4)]


def test_inventory_selection_is_order_invariant_and_caps_each_final():
    selected = select_candidates(candidates())
    assert selected==select_candidates(list(reversed(candidates())))
    assert len(selected)==4
    assert sum(r['expected_final']=='an' for r in selected)==2


def test_no_evaluation_speaker_or_pretended_actual_label_enters_inventory():
    rows = candidates(); rows[0]['split']='holdout'
    with pytest.raises(ValueError, match='training rows only'): select_candidates(rows)
    rows = candidates(); rows[0]['actual_label']='front'
    with pytest.raises(ValueError, match='verified actual label'): select_candidates(rows)


def test_cache_identity_matches_existing_probe_without_config_or_network(tmp_path):
    import asyncio
    import json
    import wave
    from align_eduhk_unmarked_cache import cache_path
    from ise_probe import IseProbe
    audio = tmp_path/'sample.wav'
    with wave.open(str(audio), 'wb') as wav:
        wav.setparams((1, 2, 16000, 1600, 'NONE', 'not compressed'))
        wav.writeframes(bytes(3200))
    cached = cache_path(audio.read_bytes(), '新', 'read_syllable', tmp_path)
    cached.parent.mkdir()
    cached.write_text(json.dumps({'status': 'synthetic_cached_test'}))
    probe = IseProbe(tmp_path, allow_paid=False)
    assert asyncio.run(probe.call(audio, '新'))=={'status': 'synthetic_cached_test'}
    with pytest.raises(RuntimeError, match='Uncached API request'):
        asyncio.run(probe.call(audio, '星'))
    assert not (tmp_path/'config.json').exists()
    assert not (tmp_path/'requests.json').exists()
