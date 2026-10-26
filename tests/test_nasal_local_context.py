import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import fit_nasal_local_context as local


def test_excluded_targets_recover_original_labels_and_remain_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(local, 'BASE', tmp_path)
    monkeypatch.setattr(local, 'SOURCE', tmp_path / 'source')
    for folder in ('source', 'feedback-v3-holdout'):
        (tmp_path / folder).mkdir()
    (tmp_path / 'ise-word-calibration-input.json').write_text(json.dumps(
        {'cases': [{'id': 'word', 'local': {'final': 'ang'}}]}))
    (tmp_path / 'source/input.json').write_text(json.dumps({'records': []}))
    (tmp_path / 'feedback-v3-holdout/input.json').write_text(json.dumps({'recordings': [
        {'uid': 'sentence', 'targets': [{'position': 1, 'expected_label': 'front', 'actual_label': 'front'}]}]}))
    dataset = {'rows': [], 'excluded': [
        {'id': 'word', 'actual_label': 'front', 'condition': 'word_error'},
        {'id': 'normal', 'actual_label': 'back', 'condition': 'teacher_correct'},
        {'id': 'sentence-pos1', 'target_count': 1}]}
    rows = local.selected_rows(dataset)
    assert [r['expected_label'] for r in rows] == ['back', 'back', 'front']
    assert [r['actual_label'] for r in rows] == ['front', 'back', 'front']
    assert 'expected_label' not in dataset['excluded'][0]  # Do not rewrite historic evidence.
    dataset['excluded'].append({'id': 'unknown'})
    with pytest.raises(ValueError, match='no auditable label'):
        local.selected_rows(dataset)


def test_feedback_ranking_prioritizes_useful_error_directions_over_classification_accuracy():
    candidates = []
    for detected, matches, accuracy in [(1, 100, 1.), (2, 80, .8), (2, 90, .7)]:
        candidates.append({'context_ms': 150, 'layer': 24, 'regularization': .01,
            'development': {'correct_error_directions': detected, 'correct_nasal_matches': matches,
                            'balanced_label_accuracy': accuracy}})
    assert local.rank(candidates)[0] is candidates[2]
