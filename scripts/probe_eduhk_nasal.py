"""Evaluate against public human-annotated nasal substitutions, not text labels.

Alignment is automatic and must be audited before calling this an accuracy
benchmark. Unmarked items are provisional controls, not certified correct speech.
"""
import argparse
import json
from pathlib import Path

from pypinyin.contrib.tone_convert import to_finals

from nasal_acoustics import AcousticModel, nasal_group
from probe_nasal_context import compare_target


def model_final(pinyin):
    if pinyin in ("zhi", "chi", "shi", "ri"):
        return "ii"
    if pinyin in ("zi", "ci", "si"):
        return "iii"
    return to_finals(pinyin, strict=True).replace("ü", "v")


def main(args):
    folder = Path(args.directory)
    cells = json.loads((folder / "crops.json").read_text())["rows"]
    model = AcousticModel("final", args.device)
    results = []
    omitted = []
    path = folder / "final-report.json"
    for cell in cells:
        syllables = cell["pinyin"]
        finals = [model_final(p) for p in syllables]
        if any(f not in model.vocab for f in finals):
            omitted.append({"speaker": cell["speaker"], "word_index": cell["word_index"], "reason": "unsupported_final"})
            continue
        inference = model.infer(cell["audio"], folder.parent / "logits")
        greedy = [s["token"] for s in inference["spans"]]
        for pos, final in enumerate(finals):
            if not nasal_group(final):
                continue
            opposite = final[:-1] if final.endswith("ng") else final + "g"
            if opposite not in model.vocab:
                continue
            matching_errors = [e for e in cell["nasal_errors"] if e["expected_plain"] == syllables[pos]]
            if cell["vowel_annotations"] and not matching_errors:
                continue
            if len(matching_errors) > 1 or syllables.count(syllables[pos]) > 1:
                continue
            observation = compare_target(inference["logits"], model.vocab, finals, pos)
            observed_group = nasal_group(greedy[pos]) if len(greedy) == len(finals) else None
            row = {"speaker": cell["speaker"], "task": cell["task"], "word_index": cell["word_index"],
                   "word": cell["word"], "target_position": pos, "expected_pinyin": syllables[pos],
                   "annotated_substitution": matching_errors[0] if matching_errors else None,
                   "label_kind": "explicit_nasal_substitution" if matching_errors else "no_vowel_deviation_annotation",
                   "greedy_finals": greedy, "greedy_target_group": observed_group,
                   "comparison": observation, "cache_key": inference["key"],
                   "alignment_reviewed_by_human": cell["alignment_reviewed_by_human"]}
            results.append(row)
            if matching_errors:
                print(json.dumps(row, ensure_ascii=False), flush=True)
        path.write_text(json.dumps({"complete": False, "scope": "Public annotations; automatic crop alignment still requires audit",
                                   "rows": results, "excluded": omitted}, ensure_ascii=False, indent=2))
        path.chmod(0o600)
    path.write_text(json.dumps({"complete": True, "input_words": len(cells),
                               "scope": "Public annotations; automatic crop alignment still requires audit",
                               "rows": results, "excluded": omitted}, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    errors = [r for r in results if r["annotated_substitution"]]
    print("ANNOTATED_ERRORS", len(errors), "opposite_likelihood_higher", sum(r["comparison"]["expected_minus_opposite"] < 0 for r in errors),
          "greedy_agrees_with_annotation", sum(r["greedy_target_group"] == r["annotated_substitution"]["actual_group"] for r in errors), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation/eduhk")
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    main(parser.parse_args())
