"""Independent phoneme-model check on single-character public learner crops."""
import argparse
import json
from pathlib import Path

from nasal_acoustics import AcousticModel, isolated_observation, ctc_log_probability, log_softmax, nasal_group


def main(args):
    folder = Path(args.directory)
    cells = json.loads((folder / "crops.json").read_text())["rows"]
    model = AcousticModel("phoneme", args.device)
    rows = []
    path = folder / "phoneme-report.json"
    for cell in cells:
        if len(cell["word"]) != 1 or (cell["vowel_annotations"] and not cell["nasal_errors"]):
            continue
        expected = nasal_group(cell["pinyin"][0])
        if expected is None:
            continue
        result = model.infer(cell["audio"], folder.parent / "logits")
        observation = isolated_observation(result["spans"], "phoneme")
        ids = [s["id"] for s in result["spans"]]
        prefix = ids[:-1] if observation["group"] is not None else ids
        probabilities = log_softmax(result["logits"])
        scores = {"front": ctc_log_probability(probabilities, prefix + [model.vocab["n"]]),
                  "back": ctc_log_probability(probabilities, prefix + [model.vocab["ŋ"]]),
                  "no_coda": ctc_log_probability(probabilities, prefix)}
        row = {"speaker": cell["speaker"], "task": cell["task"], "word_index": cell["word_index"],
               "word": cell["word"], "expected_group": expected,
               "annotated_substitution": cell["nasal_errors"][0] if len(cell["nasal_errors"]) == 1 else None,
               "tokens": [s["token"] for s in result["spans"]], "observation": observation,
               "scores": scores, "cache_key": result["key"]}
        rows.append(row)
        path.write_text(json.dumps({"complete": False, "scope": "Automatic crop localisation; needs audit", "rows": rows}, ensure_ascii=False, indent=2))
        path.chmod(0o600)
    path.write_text(json.dumps({"complete": True, "scope": "Automatic crop localisation; needs audit", "rows": rows}, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    explicit = [r for r in rows if r["annotated_substitution"]]
    print(json.dumps({"targets": len(rows), "explicit_errors": len(explicit),
                      "greedy_agrees_with_annotation": sum(r["observation"]["group"] == r["annotated_substitution"]["actual_group"] for r in explicit),
                      "abstained_on_errors": sum(r["observation"]["group"] is None for r in explicit)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation/eduhk")
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    main(parser.parse_args())
