"""Disposable UI acceptance server. Never points at real prototype progress."""
from datetime import date, timedelta
from pathlib import Path
from tempfile import mkdtemp

import uvicorn
from pth_corpus.prototype_app import create_app

root = Path(__file__).resolve().parents[1]
scratch = Path(mkdtemp(prefix="pth-ui-qa-"))
app = create_app(root / "data", prototype_dir=scratch)


@app.get("/__qa/info")
def qa_info():
    return {"isolated": True, "progress_dir": str(scratch)}


@app.post("/__qa/make-review-due")
def make_review_due():
    """Simulate the next day's due list, only in this disposable server."""
    progress = app.state.runtime.discrim_progress()
    for mistake in progress._mistakes().values():
        mistake["nextReviewAt"] = (date.today() - timedelta(days=1)).isoformat()
    progress.save()
    return progress.state()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    print(f"Isolated UI QA progress: {scratch}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
