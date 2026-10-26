"""Offline acoustic candidates for nasal research, not a production diagnosis.

Model inference never receives the expected text. No cloud calls, app startup,
learner recordings or progress writes. Use the separate research interpreter.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np


MODELS = {
    "phoneme": {
        "repo": "facebook/wav2vec2-xlsr-53-espeak-cv-ft",
        "revision": "2c733782da5604684829819a5eb744c193fe9398",
        "vocab": "vocab.json",
    },
    "final": {
        "repo": "thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2",
        "revision": "93c4b3f185f67b2f82135b34ca0397ddf8254de1",
        "vocab": "v2_1_final_vocabulary.json",
    },
}


def read_audio(path: Path) -> np.ndarray:
    """Decode locally to mono 16 kHz float PCM without altering the source."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
        capture_output=True, check=True,
    )
    samples = np.frombuffer(result.stdout, dtype="<f4").copy()
    if not 1600 <= len(samples) <= 16000 * 60:
        raise ValueError("Research input must be 0.1–60 seconds")
    if not np.isfinite(samples).all():
        raise ValueError("Non-finite waveform")
    return samples


def log_softmax(logits):
    values = np.asarray(logits, dtype=np.float64)
    shifted = values - values.max(axis=-1, keepdims=True)
    return shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))


def ctc_log_probability(log_probs, tokens, blank=0):
    """Sum all CTC paths for a candidate, including repeated-token blanks.

    This is an acoustic likelihood, not a calibrated correctness probability.
    Invalid or too-short paths return -inf; they must not become a passing score.
    """
    values = np.asarray(log_probs, dtype=np.float64)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Expected finite T x V log probabilities")
    tokens = list(tokens)
    if blank in tokens or any(t < 0 or t >= values.shape[1] for t in tokens):
        raise ValueError("Invalid CTC target")
    if not tokens:
        return float(values[:, blank].sum())
    if not len(values):
        return float("-inf")
    labels = np.array([blank] + [v for t in tokens for v in (t, blank)])
    scores = np.full(len(labels), -np.inf)
    scores[0] = values[0, blank]
    scores[1] = values[0, tokens[0]]
    skip = (labels[2:] != blank) & (labels[2:] != labels[:-2])
    for frame in values[1:]:
        previous = scores.copy()
        scores[1:] = np.logaddexp(previous[1:], previous[:-1])
        scores[2:] = np.logaddexp(scores[2:], np.where(skip, previous[:-2], -np.inf))
        scores += frame[labels]
    return float(np.logaddexp(scores[-1], scores[-2]))


def greedy_spans(logits, vocabulary, blank=0):
    probs = np.exp(log_softmax(logits))
    ids = probs.argmax(axis=-1)
    inverse = {v: k for k, v in vocabulary.items()}
    spans = []
    previous = None
    for i, token in enumerate(ids.tolist()):
        if token == previous and token != blank:
            spans[-1]["end_frame"] = i + 1
            spans[-1]["peak_posterior"] = max(spans[-1]["peak_posterior"], float(probs[i, token]))
        elif token != blank:
            spans.append({"token": inverse[token], "id": token, "start_frame": i,
                          "end_frame": i + 1, "peak_posterior": float(probs[i, token])})
        previous = token
    return spans


def nasal_group(final):
    if final.endswith("ng") or final == "ŋ":
        return "back"
    if final.endswith("n"):
        return "front"
    return None


def isolated_observation(spans, kind):
    """Conservative label for reference-only single-syllable controls."""
    if not spans:
        return {"group": None, "reason": "no_decoded_token"}
    if kind == "final" and len(spans) != 1:
        return {"group": None, "reason": "not_one_final"}
    token = spans[-1]["token"]
    group = nasal_group(token) if kind == "final" else {"n": "front", "ŋ": "back"}.get(token)
    return {"group": group, "reason": "decoded_nasal" if group else "no_terminal_nasal"}


class AcousticModel:
    def __init__(self, kind, device="mps"):
        import torch
        from transformers import Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC, Wav2Vec2Model

        self.kind = kind
        self.spec = MODELS[kind]
        self.path = Path.home() / ".cache/huggingface/hub" / (
            "models--" + self.spec["repo"].replace("/", "--")
        ) / "snapshots" / self.spec["revision"]
        self.vocab = json.loads((self.path / self.spec["vocab"]).read_text())
        self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(self.path, local_files_only=True)
        self.device = device
        if kind == "phoneme":
            self.model = Wav2Vec2ForCTC.from_pretrained(self.path, local_files_only=True)
        else:
            # Reconstruct the simple published architecture using library code.
            # Do not execute downloaded Python or enable trust_remote_code.
            from safetensors.torch import load_file
            config = json.loads((self.path / "config.json").read_text())
            class MultiHead(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.encoder = Wav2Vec2Model(Wav2Vec2Config.from_dict(config["wav2vec2_config"]))
                    width = config["wav2vec2_config"]["hidden_size"]
                    self.initial_head = torch.nn.Linear(width, config["initial_vocab_size"])
                    self.final_head = torch.nn.Linear(width, config["final_vocab_size"])
                    self.tone_head = torch.nn.Linear(width, config["tone_vocab_size"])

                def forward(self, **inputs):
                    hidden = self.encoder(**inputs).last_hidden_state
                    return self.final_head(hidden)

            self.model = MultiHead()
            self.model.load_state_dict(load_file(self.path / "model.safetensors"), strict=True)
        self.model.eval().to(device)

    def infer(self, audio, cache_dir):
        """Cache is keyed by waveform contents, pinned weights and preprocessing."""
        import torch
        samples = read_audio(Path(audio))
        key = hashlib.sha256(
            json.dumps(self.spec, sort_keys=True).encode() + b"pcm16k-f32-normalize-v1"
            + samples.tobytes()
        ).hexdigest()
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / (key + ".npz")
        if path.exists():
            with np.load(path, allow_pickle=False) as cached:
                logits = cached["logits"]
        else:
            inputs = self.extractor(samples, sampling_rate=16000, return_tensors="pt")
            with torch.inference_mode():
                output = self.model(**{k: v.to(self.device) for k, v in inputs.items()})
                logits = (output.logits if self.kind == "phoneme" else output)[0].float().cpu().numpy()
            temporary = path.with_suffix(".tmp.npz")
            np.savez_compressed(temporary, logits=logits)
            temporary.chmod(0o600)
            temporary.replace(path)
        return {"logits": logits, "sample_count": len(samples), "key": key,
                "spans": greedy_spans(logits, self.vocab)}
