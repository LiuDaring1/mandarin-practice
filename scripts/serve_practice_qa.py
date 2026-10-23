"""Disposable practice QA with local microphone checks and no cloud assessment."""
import argparse
from pathlib import Path
from tempfile import mkdtemp

import uvicorn
from pth_corpus.prototype_app import create_app

root = Path(__file__).resolve().parents[1]
scratch = Path(mkdtemp(prefix="pth-practice-qa-"))
app = create_app(root / "data", prototype_dir=scratch)

@app.get("/__qa/info")
def info():
    return {"isolated": True, "progress_dir": str(scratch), "provider": "local_only"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8779)
    args = parser.parse_args()
    print(f"Isolated local-reading QA progress: {scratch}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
