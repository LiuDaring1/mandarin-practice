"""Align public word-reading recordings, retaining source labels and boundaries.

Alignment locates words; it does not assess pronunciation. Crops with dubious
timing are excluded. Original audio and public pages remain in the ignored cache.
Run after collecting annotations and downloading selected public audio links.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
from pypinyin import lazy_pinyin, Style


ALIGNER_REVISION = "0e1a68e91d815300c7c9754b2a7639378b23db15"
ASR_REVISION = "a8379a2e2f9e313c9292cdf1af4055ab56d50d55"


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def find_word(syllables, row):
    """Find a unique phonetic match in a free transcript, regardless of page order.

    Used only for locating this labelled research audio, never pronunciation
    judgement. Ambiguous/repeated or distant words are excluded, not guessed.
    """
    expected = lazy_pinyin(row["word"], style=Style.NORMAL)
    variants = [expected]
    actual = list(expected)
    for error in row["nasal_errors"]:
        positions = [i for i, p in enumerate(expected) if p == error["expected_plain"]]
        if len(positions) == 1:
            actual[positions[0]] = error["actual_plain"]
    variants.append(actual)
    candidates = []
    for start in range(len(syllables) - len(expected) + 1):
        sample = syllables[start:start + len(expected)]
        cost = min(sum(edit_distance(a, b) for a, b in zip(sample, variant)) for variant in variants)
        candidates.append((cost, start))
    if not candidates:
        return None
    candidates.sort()
    best = candidates[0]
    if best[0] > (1 if len(expected) == 1 else 2):
        return None
    if len(candidates) > 1 and candidates[1][0] == best[0]:
        return None
    return {"start": best[1], "length": len(expected), "pinyin_edit_cost": best[0]}


def main(args):
    from mlx_audio.stt.utils import load_model
    folder = Path(args.directory)
    rows = json.loads((folder / "annotations.json").read_text())["rows"]
    model_path = Path.home() / ".cache/huggingface/hub/models--mlx-community--Qwen3-ForcedAligner-0.6B-8bit/snapshots" / ALIGNER_REVISION
    model = None
    output = []
    excluded = []
    (folder / "alignments").mkdir(exist_ok=True)
    (folder / "crops").mkdir(exist_ok=True)
    sources = sorted((folder / "audio").glob("T*_T*.mp3"))
    # The public page can list words in a different order from the recording.
    # Transcribe audio without expected text, then align that free transcript.
    # Keep ASR and aligner in separate phases to limit accelerator memory use.
    asr = None
    for source in sources:
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        cache = folder / (source.name + ".asr-v2.json")
        if cache.exists() and json.loads(cache.read_text()).get("audio_sha256") == source_hash:
            continue
        if asr is None:
            asr = load_model(Path.home() / ".cache/huggingface/hub/models--mlx-community--Qwen3-ASR-1.7B-8bit/snapshots" / ASR_REVISION)
        result = asr.generate(str(source), language="Chinese", max_tokens=512, temperature=0)
        cache.write_text(json.dumps({"text": result.text, "audio_sha256": source_hash,
                                     "asr_revision": ASR_REVISION, "reference_prompt": False}, ensure_ascii=False))
        print(source.name, "free transcript ready", flush=True)
    del asr
    import gc
    import mlx.core as mx
    gc.collect()
    mx.clear_cache()
    for source in sources:
        speaker, task = map(int, source.stem.replace("T", "").split("_"))
        group = sorted([r for r in rows if r["speaker"] == speaker and r["task"] == task], key=lambda r: r["word_index"])
        transcription = json.loads((folder / (source.name + ".asr-v2.json")).read_text())["text"]
        text = "".join(ch for ch in transcription if "\u3400" <= ch <= "\u9fff")
        key = hashlib.sha256(source.read_bytes() + text.encode() + ALIGNER_REVISION.encode() + b"free-asr-v2").hexdigest()
        cache = folder / "alignments" / (key + ".json")
        if not cache.exists():
            if model is None:
                model = load_model(model_path)
            result = model.generate(str(source), text=text, language="Chinese")
            timestamps = [{"text": r.text, "start": r.start_time, "end": r.end_time} for r in result.items]
            cache.write_text(json.dumps({"key": key, "items": timestamps}, ensure_ascii=False, indent=2))
        timestamps = json.loads(cache.read_text())["items"]
        if "".join(t["text"] for t in timestamps) != text:
            raise ValueError("Aligner token identity mismatch")
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-nostdin", "-i", str(source), "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"])
        samples = np.frombuffer(raw, dtype="<i2")
        transcript_syllables = lazy_pinyin(text, style=Style.NORMAL)
        matches = {r["word_index"]: find_word(transcript_syllables, r) for r in group}
        claims = Counter((m["start"], m["length"]) for m in matches.values() if m is not None)
        for row in group:
            count = len(row["word"])
            syllables = lazy_pinyin(row["word"], style=Style.NORMAL)
            if not any(s.endswith(("n", "ng")) for s in syllables):
                continue
            match = matches[row["word_index"]]
            if match is None or claims[(match["start"], match["length"])] != 1:
                excluded.append({"speaker": speaker, "task": task, "word_index": row["word_index"], "reason": "ambiguous_or_distant_transcript_match"})
                continue
            times = timestamps[match["start"]:match["start"] + count]
            if any(t["end"] - t["start"] < .08 for t in times) or times[-1]["end"] - times[0]["start"] > max(4, count * 1.5):
                excluded.append({"speaker": speaker, "task": task, "word_index": row["word_index"], "reason": "suspect_alignment"})
                continue
            start = max(0, times[0]["start"] - .10)
            end = min(len(samples) / 16000, times[-1]["end"] + .10)
            if not 0 <= start < end <= len(samples) / 16000:
                raise ValueError("Out-of-range alignment")
            clip = folder / "crops" / f"s{speaker}-t{task}-w{row['word_index']}.wav"
            with wave.open(str(clip), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(samples[round(start * 16000):round(end * 16000)].tobytes())
            output.append({**row, "pinyin": syllables, "audio": str(clip), "source_audio": source.name,
                           "crop_start": start, "crop_end": end, "alignment": times,
                           "alignment_key": key, "alignment_reviewed_by_human": False,
                           "transcript_match": match, "matched_transcript": "".join(t["text"] for t in times)})
        print(source.name, "aligned characters", len(timestamps), "retained words", len(output), flush=True)
    report = folder / "crops.json"
    report.write_text(json.dumps({"rows": output, "excluded": excluded}, ensure_ascii=False, indent=2))
    report.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="data/derived/nasal-acoustic-validation/eduhk")
    main(parser.parse_args())
