"""Six public annotated-error controls using the already configured ISE probe."""
import argparse
import asyncio
import json
from pathlib import Path

from ise_probe import IseProbe, public_result
from suntone_probe import private_json
from validate_ise_stability import target_observation


async def run(args):
    folder = Path("data/derived/nasal-acoustic-validation/eduhk")
    crops = json.loads((folder / "crops.json").read_text())["rows"]
    local = json.loads((folder / "final-report.json").read_text())["rows"]
    # Two directions for in/ing, en/eng, an/ang; includes local model misses.
    selected = [(10, 1, 28), (15, 1, 23), (11, 1, 5), (15, 1, 26), (13, 1, 19), (13, 2, 6)]
    probe = IseProbe(Path("data/derived/ise-validation"), allow_paid=args.allow_paid, max_calls=80)
    results = []
    for key in selected:
        row = next(r for r in local if (r["speaker"], r["task"], r["word_index"]) == key and r["annotated_substitution"])
        crop = next(r for r in crops if (r["speaker"], r["task"], r["word_index"]) == key)
        reference = row["word"].replace("恆", "恒")
        core = "read_syllable" if len(reference) == 1 else "read_word"
        result = public_result(await probe.call(crop["audio"], reference, core=core))
        observed = target_observation(result, reference[row["target_position"]])
        public = {"speaker": row["speaker"], "task": row["task"], "word_index": row["word_index"],
                  "reference": reference, "annotation": row["annotated_substitution"],
                  "local_expected_minus_opposite": row["comparison"]["expected_minus_opposite"],
                  "ise_status": result["status"], "ise_observation": observed,
                  "alignment_reviewed_by_human": False}
        results.append(public)
        private_json(folder / "ise-comparison.json", {"cells": results})
        print(json.dumps(public, ensure_ascii=False), flush=True)
        if result["status"] != "ok":
            raise RuntimeError("ISE failed; stopped without automatic retries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-paid", action="store_true")
    asyncio.run(run(parser.parse_args()))
