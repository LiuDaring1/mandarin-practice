"""Check CTC maths and abstention without downloading or invoking models."""
import itertools
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from nasal_acoustics import ctc_log_probability, greedy_spans, isolated_observation
from probe_nasal_context import compare_target, normalize_final


def collapsed(path):
    return [v for i, v in enumerate(path) if v != 0 and (i == 0 or path[i - 1] != v)]


@pytest.mark.parametrize("target", [[], [1], [1, 1], [1, 2], [2, 1, 2]])
def test_ctc_sum_matches_exhaustive_paths(target):
    probs = np.array([[0.4, 0.3, 0.3], [0.6, 0.3, 0.1], [0.2, 0.3, 0.5]])
    expected = sum(np.prod([probs[t, v] for t, v in enumerate(path)])
                   for path in itertools.product(range(3), repeat=3) if collapsed(path) == target)
    assert np.exp(ctc_log_probability(np.log(probs), target)) == pytest.approx(expected)


def test_impossible_ctc_target_is_not_success():
    assert ctc_log_probability(np.log([[0.5, 0.5]]), [1, 1]) == -np.inf
    with pytest.raises(ValueError):
        ctc_log_probability(np.log([[0.5, 0.5]]), [0])


def test_greedy_preserves_blank_separated_repetition():
    logits = np.array([[0, 9], [0, 8], [9, 0], [0, 9]])
    spans = greedy_spans(logits, {"<blank>": 0, "in": 1})
    assert [(s["start_frame"], s["end_frame"]) for s in spans] == [(0, 2), (3, 4)]
    assert isolated_observation(spans, "final")["group"] is None


def test_initial_n_is_not_treated_as_nasal_coda():
    assert isolated_observation([{"token": "n"}, {"token": "a"}], "phoneme")["group"] is None
    assert isolated_observation([], "final")["group"] is None
    assert isolated_observation([{"token": "i"}], "final")["group"] is None


def test_model_schema_apical_vowels_are_not_assumed_from_spelling():
    assert normalize_final("-i_front") == "iii"
    assert normalize_final("-i_back") == "ii"
    assert normalize_final("üe") == "ve"


def test_reference_swap_reverses_comparison_without_changing_audio():
    logits = np.array([[0, 7, 0, 0], [8, 0, 0, 0], [0, 0, 0, 8]])
    vocab = {"<blank>": 0, "in": 1, "ing": 2, "a": 3}
    front = compare_target(logits, vocab, ["in", "a"], 0)
    back = compare_target(logits, vocab, ["ing", "a"], 0)
    assert front["expected_minus_opposite"] > 0
    assert front["expected_minus_opposite"] == pytest.approx(-back["expected_minus_opposite"])


def test_impossible_comparison_cannot_generate_nan_confidence():
    with pytest.raises(ValueError, match="too short"):
        compare_target(np.array([[0, 7, 0]]), {"<blank>": 0, "in": 1, "ing": 2}, ["in", "in"], 0)
