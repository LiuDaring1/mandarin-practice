"""Download only linked public recordings containing explicit nasal annotations.

Local research only; keep recordings under ignored data/derived. See the corpus
research-use statement at https://lml-elearning.eduhk.hk/about_g.aspx.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request

from lxml import html


def main(args):
    folder = Path(args.directory)
    rows = json.loads((folder / "annotations.json").read_text())["rows"]
    groups = sorted({(r["speaker"], r["task"]) for r in rows if r["nasal_errors"]})
    (folder / "audio").mkdir(exist_ok=True)

    def download(group):
        speaker, task = group
        doc = html.fromstring((folder / f"speaker-{speaker}.html").read_bytes())
        tag = "One" if task == 1 else "Two"
        sources = doc.xpath(f'//div[contains(@id,"Task{tag}AudioPanel")]//source/@src')
        if not sources:
            raise ValueError("Missing public audio link")
        url = urllib.parse.urljoin("https://lml-elearning.eduhk.hk/", sources[0])
        if urllib.parse.urlsplit(url).hostname != "lml-elearning.eduhk.hk":
            raise ValueError("Unexpected media host")
        path = folder / "audio" / Path(urllib.parse.urlsplit(url).path).name
        if not path.exists():
            temporary = path.with_suffix(".partial")
            with urllib.request.urlopen(url, timeout=30) as response, temporary.open("wb") as out:
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > 50_000_000:
                        raise ValueError("Unexpected recording size")
                    out.write(chunk)
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(temporary), "-f", "null", "-"], check=True, capture_output=True)
            temporary.replace(path)
        return {"speaker": speaker, "task": task, "source_url": url, "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}

    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        for result in executor.map(download, groups):
            results.append(result)
            (folder / "downloads.json").write_text(json.dumps({"research_use_only": True, "recordings": results}, indent=2))
            print("downloaded", result["filename"], len(results), "/", len(groups), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation/eduhk")
    main(parser.parse_args())
