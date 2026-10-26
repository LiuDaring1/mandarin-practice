"""Compare final-level acoustic likelihoods in natural words and sentences.

Expected text is used only after audio inference for competing CTC hypotheses.
These likelihood margins are research observations, not student scores.
"""
import argparse
import json
import math
from pathlib import Path

from nasal_acoustics import AcousticModel, ctc_log_probability, log_softmax


def normalize_final(final):
    # Published v2_1_target_schema: retroflex=ii, alveolar=iii.
    return {"-i_front": "iii", "-i_back": "ii"}.get(final, final.replace("ü", "v"))


def compare_target(logits, vocabulary, finals, position):
    expected = [normalize_final(f) for f in finals]
    final = expected[position]
    if final.endswith("ng"):
        alternate = final[:-1]
    elif final.endswith("n"):
        alternate = final + "g"
    else:
        raise ValueError("Target must be nasal")
    if alternate not in vocabulary:
        raise ValueError("No direct nasal contrast in this vocabulary")
    alternatives = {
        "expected": expected,
        "opposite": expected[:position] + [alternate] + expected[position + 1:],
        "omitted": expected[:position] + expected[position + 1:],
    }
    probs = log_softmax(logits)
    scores = {name: ctc_log_probability(probs, [vocabulary[f] for f in seq])
              for name, seq in alternatives.items()}
    if not all(math.isfinite(score) for score in scores.values()):
        raise ValueError("Audio is too short for one or more CTC candidates")
    return {"final": final, "opposite_final": alternate,
            "scores": scores, "expected_minus_opposite": scores["expected"] - scores["opposite"],
            "best_hypothesis": max(scores, key=scores.get)}


def main(args):
    folder = Path(args.folder)
    cells = json.loads((folder / "context-inputs.json").read_text())
    model = AcousticModel("final", args.device)
    rows = []
    for cell in cells:
        result = model.infer(cell["audio"], folder / "logits")
        chars = [ch for ch in cell["source_text"] if "\u3400" <= ch <= "\u9fff"]
        finals = cell["features"]["final_seq"].split()
        if len(chars) != len(finals) or chars.count(cell["target"]) != 1:
            raise ValueError("Target mapping is not unique")
        position = chars.index(cell["target"])
        comparison = compare_target(result["logits"], model.vocab, finals, position)
        row = {"kind": cell["kind"], "audio_id": cell["audio_id"], "voice": cell["voice"],
               "target": cell["target"], "target_position": position, "comparison": comparison,
               "greedy_finals": [s["token"] for s in result["spans"]], "cache_key": result["key"]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        out = folder / "final-context-report.json"
        out.write_text(json.dumps({"scope": "Reference controls; not learner accuracy", "cells": rows}, ensure_ascii=False, indent=2))
        out.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="data/derived/nasal-acoustic-validation")
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    main(parser.parse_args())
