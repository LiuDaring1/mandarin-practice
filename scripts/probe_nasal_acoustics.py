"""Reference-control benchmark. Results must not be called learner accuracy."""
import argparse
import json
from pathlib import Path
import time

from nasal_acoustics import AcousticModel, MODELS, isolated_observation


def main(args):
    source = Path(args.source)
    inputs = json.loads((source / "local-asr-report.json").read_text())["cells"]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    model = AcousticModel(args.kind, args.device)
    print("Model loaded in", round(time.monotonic() - started, 2), "seconds", flush=True)
    rows = []
    for item in inputs:
        path = source / Path(item["audio"]).name
        started = time.monotonic()
        result = model.infer(path, output / "logits")
        observed = isolated_observation(result["spans"], args.kind)
        row = {"audio_id": path.stem, "label": item["spoken_label"],
               "expected_group": item["expected_group"], "voice": item["voice"],
               "observation": observed, "spans": result["spans"], "cache_key": result["key"],
               "seconds": time.monotonic() - started}
        rows.append(row)
        print(json.dumps({"label": row["label"], "voice": row["voice"],
                          "tokens": [s["token"] for s in row["spans"]],
                          "group": observed["group"]}, ensure_ascii=False), flush=True)
    summary = {"model": MODELS[args.kind], "reference_text_given_to_model": False,
               "scope": "Existing labeled reference and converted clips; NOT learner diagnostic accuracy.",
               "count": len(rows),
               "label_agreement": sum(r["observation"]["group"] == r["expected_group"] for r in rows),
               "abstained": sum(r["observation"]["group"] is None for r in rows),
               "disagreed": sum(r["observation"]["group"] not in (None, r["expected_group"]) for r in rows),
               "cells": rows}
    report = output / (args.kind + "-reference-report.json")
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    report.chmod(0o600)
    print(json.dumps({k: v for k, v in summary.items() if k != "cells"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=MODELS, required=True)
    parser.add_argument("--source", default="data/derived/nasal-validation-v2")
    parser.add_argument("--output", default="data/derived/nasal-acoustic-validation")
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    main(parser.parse_args())
