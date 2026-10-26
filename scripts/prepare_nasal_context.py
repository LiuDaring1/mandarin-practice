"""Build reference-only context inputs using the existing corpus runtime.

Run with the project virtualenv. No paid probe calls or web app construction.
"""
import json
from pathlib import Path

from pth_corpus.sentence_reading import score_sentence
from validate_ise_stability import prepare_cells


def main():
    cells = [c for c in prepare_cells(Path("data/derived/ise-validation"))
             if c["kind"] != "single" and not c["cross_reference"]]
    for cell in cells:
        cell["features"] = score_sentence(cell["source_text"])
    output = Path("data/derived/nasal-acoustic-validation/context-inputs.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cells, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    print("Prepared reference contexts:", len(cells))


if __name__ == "__main__":
    main()
