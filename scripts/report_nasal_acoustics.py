"""Write aggregate, shareable research evidence without audio or learner data."""
import argparse
from collections import Counter
import json
from pathlib import Path


def load_completed_report(path):
    report = json.loads(Path(path).read_text())
    if report.get("complete") is not True:
        raise ValueError("Inference report is incomplete; do not publish aggregate results")
    return report


def main(args):
    folder = Path(args.directory)
    report = {
        "scope": "Research screening only; production diagnosis is not enabled.",
        "reference_controls": {},
        "sources": [
            "https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft",
            "https://huggingface.co/thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2",
            "https://lml-elearning.eduhk.hk/about_g.aspx",
        ],
    }
    for kind in ("phoneme", "final"):
        data = json.loads((folder / (kind + "-reference-report.json")).read_text())
        report["reference_controls"][kind] = {k: data[k] for k in ("model", "count", "label_agreement", "abstained", "disagreed")}
    contexts = json.loads((folder / "final-context-report.json").read_text())["cells"]
    report["context_controls"] = [{"kind": r["kind"], "target": r["target"], "voice": r["voice"],
                                    "expected_minus_opposite": r["comparison"]["expected_minus_opposite"]} for r in contexts]
    corpus = folder / "eduhk"
    annotations = json.loads((corpus / "annotations.json").read_text())["rows"]
    crops = json.loads((corpus / "crops.json").read_text())
    inferred = load_completed_report(corpus / "final-report.json")
    rows = inferred["rows"]
    explicit = [r for r in rows if r["annotated_substitution"]]
    unmarked = [r for r in rows if not r["annotated_substitution"]]

    def metrics(selected):
        return {"targets": len(selected),
                "opposite_likelihood_higher": sum(r["comparison"]["expected_minus_opposite"] < 0 for r in selected),
                "opposite_best_including_omission": sum(r["comparison"]["best_hypothesis"] == "opposite" for r in selected),
                "greedy_supports_opposite_group": sum(r["greedy_target_group"] ==
                    ("front" if r["comparison"]["final"].endswith("ng") else "back") for r in selected)}

    report["public_learner_screening"] = {
        "speakers_in_pages": len({r["speaker"] for r in annotations}),
        "explicit_annotation_targets": sum(len(r["nasal_errors"]) for r in annotations),
        "recordings_downloaded": len(json.loads((corpus / "downloads.json").read_text())["recordings"]),
        "cropped_words": len(crops["rows"]),
        "excluded_word_candidates": dict(Counter(r["reason"] for r in crops["excluded"])),
        "explicit_errors_scored": metrics(explicit),
        "explicit_annotation_targets_not_scored": sum(len(r["nasal_errors"]) for r in annotations) - len(explicit),
        "explicit_errors_by_partition": {name: metrics([r for r in explicit if (r["speaker"] <= 20) == early])
                                           for name, early in [("speakers_1_20", True), ("speakers_21_40", False)]},
        "unmarked_targets_provisional_only": metrics(unmarked),
        "limitations": [
            "Automatic crop localisation is not yet manually audited. No learner accuracy claim.",
            "Unmarked means no vowel-deviation annotation, not certified correct nasal production.",
            "All 92 annotated targets remain in the denominator inventory; excluded crops are not successes.",
            "No thresholds were fitted. Raw CTC likelihood margins are not calibrated confidence.",
            "Speaker partitions are descriptive screening slices, not an untouched final acceptance set.",
            "Corpus recordings are retained only locally for research, not redistributed or used as teaching audio.",
        ],
    }
    phoneme_path = corpus / "phoneme-report.json"
    if phoneme_path.exists():
        phone_rows = load_completed_report(phoneme_path)["rows"]
        phone_errors = [r for r in phone_rows if r["annotated_substitution"]]
        report["public_learner_screening"]["phoneme_single_character_check"] = {
            "targets": len(phone_rows), "annotated_errors": len(phone_errors),
            "greedy_agrees_with_annotation": sum(r["observation"]["group"] == r["annotated_substitution"]["actual_group"] for r in phone_errors),
            "abstained_on_errors": sum(r["observation"]["group"] is None for r in phone_errors),
        }
    ise_path = corpus / "ise-comparison.json"
    if ise_path.exists():
        cells = json.loads(ise_path.read_text())["cells"]
        report["ise_public_error_spot_check"] = {
            "selected_controls": len(cells),
            "flagged_final_or_substitution": sum(r["ise_observation"]["state"] == "flagged" for r in cells),
            "selection": "Six known annotated errors, both directions in each of in/ing, en/eng, an/ang; includes two local-model raw-margin misses.",
            "limit": "Generic final error signals do not independently identify n/ng direction. No verified-correct controls in this six-call spot check.",
            "cells": [{"reference": r["reference"], "expected": r["annotation"]["expected_plain"],
                       "annotated_actual": r["annotation"]["actual_plain"],
                       "local_expected_minus_opposite": r["local_expected_minus_opposite"],
                       "ise_state": r["ise_observation"]["state"]} for r in cells],
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["public_learner_screening"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation")
    parser.add_argument("--output", default="handoff/nasal-acoustic-2026-10-26/report.json")
    main(parser.parse_args())
