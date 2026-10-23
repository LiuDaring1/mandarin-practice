"""Background reading jobs and local, conservative nasal-final practice hints.

Audio stays in memory only. History lives under the runtime's isolated progress
directory. A low final score is a practice suggestion, never an n/ng diagnosis.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import time

from .assessment import AssessmentError, AssessmentService, evaluation_mode, validate_wav

SAFE_ID = re.compile(r"[a-zA-Z0-9-]{8,100}\Z")
NASALS = {"an", "en", "in", "ang", "eng", "ing", "ong", "ian", "iang",
          "uan", "uang", "uen", "un", "ueng", "üan", "ün", "iong"}


def plain(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum())


def final_key(value: str) -> str:
    return re.sub(r"[0-5]$", "", value.lower()).replace("v", "ü").replace("u:", "ü").replace("uen", "un")


def nasal_final_evidence(phones: list[dict], expected: str) -> dict | None:
    """Match one complete final, including Tencent's medial + rime output.

    E.g. i4 + an -> ian, u1 + an -> uan, v2 + an -> üan. Tone marks
    may occur on the medial, not the last component. Keep all component scores
    instead of inventing an average; the nasal-containing last component is
    the observation. It still isn't a diagnosis of an n/ng substitution.
    """
    matches = []
    for start in range(len(phones)):
        for end in range(start + 1, min(start + 3, len(phones)) + 1):
            parts = phones[start:end]
            combined = "".join(final_key(p.get("phone", "")) for p in parts)
            if final_key(combined) != final_key(expected):
                continue
            if any(p.get("tag") != 0 or p.get("accuracy") is None for p in parts):
                continue
            matches.append(parts)
    if len(matches) != 1:
        return None
    parts = matches[0]
    return {"accuracy": parts[-1]["accuracy"],
            "basis": "final_score" if len(parts) == 1 else "nasal_component_score",
            "components": [{"phone": p["phone"], "accuracy": p["accuracy"]} for p in parts]}


def nasal_feedback(text: str, targets: list[dict], result: dict) -> list[dict]:
    # Paragraph mode has no dependable phoneme detail. Do not invent a score.
    if result.get("status") != "ok" or evaluation_mode(text) == 2:
        return []
    reference = plain(text)
    cursor, aligned = 0, {}
    for word in result.get("words", []):
        if word.get("tag") == 1:  # inserted speech consumes no reference text
            continue
        token = plain(word.get("text", ""))
        if not token or reference[cursor:cursor + len(token)] != token:
            return []  # ambiguous alignment, including repeated characters
        if len(token) == 1 and word.get("tag") == 0:
            aligned[cursor] = word
        cursor += len(token)
    if cursor != len(reference):
        return []
    feedback = []
    for target in targets:
        word = aligned.get(target["position"], {})
        evidence = nasal_final_evidence(word.get("phones", []), target["final"])
        if evidence is None:
            continue
        feedback.append({**target, **evidence, "practice": evidence["accuracy"] < 70,
                         "diagnosis": None})
    return feedback


class ReadingCoach:
    def __init__(self, service: AssessmentService, progress_dir: Path, *, nasal_review_enabled: bool = False):
        self.service = service
        # Live n/ng controls failed discrimination on 2026-10-23. Keep the
        # downstream queue gated until an independently validated scorer exists.
        self.nasal_review_enabled = nasal_review_enabled
        self.folder = progress_dir / "reading" / "attempts"
        self.tasks: set[asyncio.Task] = set()
        self.gate = asyncio.Semaphore(2)
        # A restart cannot safely replay a potentially billed submission.
        for row in self.records():
            if row["status"] == "pending":
                row["status"] = "interrupted"
                self.save(row)

    def records(self) -> list[dict]:
        if not self.folder.exists():
            return []
        rows = []
        for path in self.folder.glob("*.json"):
            try:
                row = json.loads(path.read_text())
                if SAFE_ID.fullmatch(row.get("attempt_id", "")):
                    rows.append(row)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(rows, key=lambda r: (r["created"], r["attempt_id"]))

    def save(self, row: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{row['attempt_id']}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(row, ensure_ascii=False))
        temp.chmod(0o600)
        temp.replace(path)

    def submit(self, *, attempt_id: str, session_id: str, kind: str,
               reference_id: str, text: str, targets: list[dict],
               audio: bytes, pass_no: int) -> dict:
        if not SAFE_ID.fullmatch(attempt_id) or not SAFE_ID.fullmatch(session_id) or pass_no not in (1, 2):
            raise AssessmentError("invalid_attempt", "朗读记录参数无效")
        validate_wav(audio)
        evaluation_mode(text)
        fingerprint = hashlib.sha256(
            f"{session_id}:{kind}:{reference_id}:{pass_no}:".encode() + audio
        ).hexdigest()
        path = self.folder / f"{attempt_id}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row["fingerprint"] != fingerprint:
                raise AssessmentError("invalid_attempt", "新的录音需要新的记录编号")
            return {"attempt_id": attempt_id, "status": row["status"]}
        if len(self.tasks) >= 48:
            raise AssessmentError("busy", "后台评测繁忙，本次仍可正常练习")
        row = {"attempt_id": attempt_id, "session_id": session_id, "kind": kind,
               "reference_id": reference_id, "text": text, "targets": targets,
               "pass_no": pass_no, "fingerprint": fingerprint, "created": time.time(),
               "status": "pending", "feedback": []}
        self.save(row)
        task = asyncio.create_task(self.process(row, audio))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {"attempt_id": attempt_id, "status": "pending"}

    async def process(self, row: dict, audio: bytes) -> None:
        try:
            async with self.gate:
                result = await self.service.assess(row["attempt_id"], row["text"], audio)
            row["status"] = result["status"]
            row["feedback"] = nasal_feedback(row["text"], row["targets"], result)
            if not self.nasal_review_enabled:
                for observation in row["feedback"]:
                    observation["practice"] = None  # store observations, not unvalidated labels
            # Keep only pedagogically used details; no audio or signed request URLs.
            row["completion"] = result.get("completion")
            # Retain normalized phone observations locally, so mapping fixes can
            # be audited without storing speech or paying to upload it again.
            row["provider_words"] = result.get("words", [])
        except asyncio.CancelledError:
            row["status"] = "interrupted"
            raise
        except AssessmentError as exc:
            row["status"] = exc.status
        except Exception:
            row["status"] = "unavailable"
        finally:
            self.save(row)

    async def shutdown(self) -> None:
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def weak_items(self, rows: list[dict] | None = None) -> list[dict]:
        if not self.nasal_review_enabled:
            return []
        latest, episodes = {}, {}
        for row in self.records() if rows is None else rows:
            for feedback in row.get("feedback", []):
                if feedback.get("practice") is None:
                    continue
                key = (row["kind"], row["reference_id"], feedback["position"], feedback["final"])
                episodes.setdefault(key, set())
                if feedback["practice"]:
                    episodes[key].add(row["session_id"])
                else:
                    episodes[key].clear()
                latest[key] = {**feedback, "kind": row["kind"], "reference_id": row["reference_id"],
                               "context": row["text"], "created": row["created"]}
        return sorted([{**value, "sessions": len(episodes[key])}
                       for key, value in latest.items() if value["practice"]],
                      key=lambda row: (-row["sessions"], -row["created"]))

    def retry_items(self, rows: list[dict] | None = None) -> list[dict]:
        latest = {(r["kind"], r["reference_id"]): r
                  for r in (self.records() if rows is None else rows) if r["status"] == "ok"}
        return [{"reference_id": r["reference_id"], "kind": r["kind"], "text": r["text"]}
                for r in latest.values()
                if r.get("completion") is not None and r["completion"] < 90]

    def summary(self, session_id: str) -> dict:
        rows = [r for r in self.records() if r["session_id"] == session_id]
        feedback = [f for r in rows for f in r.get("feedback", [])]
        retry_items = self.retry_items(rows)
        return {"session_id": session_id, "submitted": len(rows),
                "created": rows[0]["created"] if rows else None,
                "kind": rows[0].get("kind") if rows else None,
                "diagnostics_ready": self.nasal_review_enabled,
                "pending": sum(r["status"] == "pending" for r in rows),
                "assessed": sum(r["status"] == "ok" for r in rows),
                "unavailable": sum(r["status"] not in ("ok", "pending", "no_speech") for r in rows),
                "no_speech": sum(r["status"] == "no_speech" for r in rows),
                "target_observations": len(feedback), "weak": self.weak_items(rows)[:8],
                "possible_incomplete": len(retry_items),
                "retry_items": retry_items,
                "limited": sum(r["status"] == "ok" and not r.get("feedback") for r in rows)}
