"""Tencent SOE recording-mode adapter. Server-side credentials; transient audio.

Protocol: https://cloud.tencent.com/document/product/1774/107497
Only accounting units are persisted; recordings and provider results aren't logged.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import fcntl
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
import uuid
import wave

import numpy as np
from websockets.asyncio.client import connect


class AssessmentError(ValueError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def read_settings(data_root: Path) -> dict:
    path = data_root / "derived/assessment/config.json"
    settings = json.loads(path.read_text()) if path.is_file() else {}
    credentials = {}
    if settings.get("credential_file"):
        with open(settings["credential_file"], encoding="utf-8-sig", newline="") as fh:
            credentials = next(csv.DictReader(fh), {})
    return {
        "appid": os.getenv("TENCENTCLOUD_APP_ID", str(settings.get("appid", ""))),
        "secret_id": os.getenv("TENCENTCLOUD_SECRET_ID", credentials.get("SecretId", "")),
        "secret_key": os.getenv("TENCENTCLOUD_SECRET_KEY", credentials.get("SecretKey", "")),
        "score_coeff": float(settings.get("score_coeff", 2.0)),
        "limit_units": int(settings.get("limit_units", 1000)),
    }


def validate_wav(audio: bytes) -> float:
    try:
        with wave.open(io.BytesIO(audio), "rb") as fh:
            if (fh.getnchannels(), fh.getsampwidth(), fh.getframerate(), fh.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("format")
            frames = fh.getnframes()
            pcm = fh.readframes(frames)
            duration = frames / 16000
            if len(pcm) != frames * 2 or not 0.25 <= duration <= 59:
                raise ValueError("length")
    except (wave.Error, EOFError, ValueError):
        raise AssessmentError("invalid_audio", "录音须为 16kHz 单声道 WAV，时长 0.25–59 秒") from None
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
    # Conservative silence screen only. SOE decides whether this contains speech.
    if np.sqrt(np.mean(samples * samples)) < 0.002:
        raise AssessmentError("no_speech", "没有检测到朗读，请再读一次")
    return duration


def evaluation_mode(text: str) -> int:
    count = sum(ch.isalnum() for ch in text)
    if not 1 <= count <= 120:
        raise AssessmentError("unsupported", "这条内容超出评测长度，仍可正常跟读")
    return 0 if count == 1 else 1 if count <= 30 else 2


def signed_url(settings: dict, text: str, voice_id: str) -> str:
    now = int(time.time())
    params = {
        "secretid": settings["secret_id"], "timestamp": now, "expired": now + 300,
        "nonce": secrets.randbelow(9999999999) + 1, "server_engine_type": "16k_zh",
        "voice_id": voice_id, "voice_format": 1, "text_mode": 0,
        "ref_text": text, "eval_mode": evaluation_mode(text),
        "score_coeff": settings["score_coeff"], "sentence_info_enabled": 1, "rec_mode": 1,
    }
    host = f"soe.cloud.tencent.com/soe/api/{settings['appid']}"
    raw = host + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["signature"] = base64.b64encode(hmac.new(
        settings["secret_key"].encode(), raw.encode(), hashlib.sha1
    ).digest()).decode()
    return "wss://" + host + "?" + urlencode(params)


def check_message(message: dict) -> None:
    code = int(message.get("code", 0))
    if code:
        status, text = {
            4002: ("unavailable", "评测凭证验证失败"),
            4003: ("unavailable", "腾讯口语评测服务尚未开通"),
            4004: ("quota", "评测额度已用完，仍可正常跟读"),
            4005: ("quota", "评测服务暂不可用，仍可正常跟读"),
            4105: ("no_speech", "没有检测到朗读，请再读一次"),
            4108: ("no_speech", "没有检测到有效朗读，请再读一次"),
        }.get(code, ("unavailable", "这次评测未成功，请重试或继续跟读"))
        raise AssessmentError(status, text)


def normalize_result(result: dict) -> dict:
    def number(key, scale=1):
        value = result.get(key)
        return round(min(100, float(value) * scale), 1) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None
    words = []
    for row in result.get("Words") or []:
        accuracy = row.get("PronAccuracy")
        word = {"text": row.get("ReferenceWord") or row.get("Word", ""),
                      "accuracy": round(accuracy, 1) if isinstance(accuracy, (int, float)) and math.isfinite(accuracy) and accuracy >= 0 else None,
                      "tag": row.get("MatchTag", row.get("Tag", 0))}
        phones = []
        for phone in row.get("PhoneInfos") or []:
            score = phone.get("PronAccuracy")
            phones.append({"phone": phone.get("Phone", ""),
                           "accuracy": round(score, 1) if isinstance(score, (int, float)) and math.isfinite(score) and score >= 0 else None,
                           "tag": phone.get("MatchTag", 0)})
        if phones:
            word["phones"] = phones
        words.append(word)
    if number("PronCompletion", 100) == 0 and (not words or all(w["tag"] in (2, 4) for w in words)):
        return {"status": "no_speech", "message": "没有检测到有效朗读，请再读一次"}
    return {"status": "ok", "score": number("SuggestedScore"),
            "accuracy": number("PronAccuracy"), "fluency": number("PronFluency", 100),
            "completion": number("PronCompletion", 100), "words": words}


async def evaluate(settings: dict, text: str, audio: bytes) -> dict:
    """One connection and one upload; never retry a potentially billed request."""
    latest = None
    try:
        async with asyncio.timeout(20):
            async with connect(signed_url(settings, text, str(uuid.uuid4())),
                               open_timeout=8, close_timeout=2, max_size=2**20,
                               compression=None) as socket:
                check_message(json.loads(await socket.recv()))
                await socket.send(audio)
                await socket.send(json.dumps({"type": "end"}))
                async for raw in socket:
                    message = json.loads(raw)
                    check_message(message)
                    result = message.get("result")
                    if isinstance(result, str):
                        result = json.loads(result)
                    if isinstance(result, dict):
                        latest = result
                    if message.get("final") == 1:
                        break
                else:
                    raise AssessmentError("unavailable", "评测连接提前结束，请重读或继续")
    except AssessmentError:
        raise
    except Exception:
        # Do not return exception text: connection exceptions may contain signed URLs.
        raise AssessmentError("unavailable", "评测连接未成功，请重试或继续跟读") from None
    if latest is None:
        raise AssessmentError("unavailable", "未收到评测结果，请重读或继续")
    return normalize_result(latest)


class AssessmentService:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.disabled = False
        self.cloud_enabled = True
        self.lock = asyncio.Lock()
        self.cache: dict[str, tuple[str, dict]] = {}

    def settings(self) -> dict:
        try:
            return read_settings(self.data_root)
        except (OSError, ValueError, StopIteration):
            return {}

    def units_used(self) -> int:
        path = self.data_root / "derived/assessment/usage.json"
        if not path.is_file():
            return 0
        try:
            value = int(json.loads(path.read_text())["reserved_units"])
            return value if value >= 0 else 10**9
        except (OSError, ValueError, TypeError, KeyError):
            return 10**9  # damaged accounting must not silently reset the allowance

    def status(self) -> dict:
        if not self.cloud_enabled:
            return {"available": False, "configured": False, "cloud_enabled": False,
                    "recording_required": not self.disabled, "max_audio_sec": 59}
        settings = self.settings()
        configured = not self.disabled and all(settings.get(k) for k in ("appid", "secret_id", "secret_key"))
        required = not self.disabled and bool(configured or (self.data_root / "derived/assessment/config.json").exists())
        remaining = max(0, settings.get("limit_units", 0) - self.units_used())
        return {"available": bool(configured and remaining), "configured": bool(configured),
                "cloud_enabled": not self.disabled,
                "recording_required": required, "remaining_test_units": remaining, "max_audio_sec": 59}

    def reserve(self, units: int, limit: int) -> None:
        # The preview server and disposable recording QA can coexist on this Mac.
        # Reserve under a process lock as well as the in-process attempt lock.
        usage = self.data_root / "derived/assessment/usage.json"
        usage.parent.mkdir(parents=True, exist_ok=True)
        with usage.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            used = self.units_used()
            if used + units > limit:
                raise AssessmentError("quota", "本轮测试额度已用完，仍可正常跟读")
            temporary = usage.with_suffix(".tmp")
            temporary.write_text(json.dumps({"reserved_units": used + units}))
            temporary.replace(usage)

    async def assess(self, attempt_id: str, text: str, audio: bytes) -> dict:
        validate_wav(audio)
        mode = evaluation_mode(text)
        fingerprint = hashlib.sha256(text.encode() + audio).hexdigest()
        async with self.lock:
            if attempt_id in self.cache:
                digest, result = self.cache[attempt_id]
                if digest != fingerprint:
                    raise AssessmentError("invalid_attempt", "请为新的录音创建新的评测请求")
                return result
            settings = self.settings()
            if not self.status()["available"]:
                raise AssessmentError("unavailable", "评测暂不可用，仍可正常跟读")
            units = math.ceil(sum(ch.isalnum() for ch in text) / 20) if mode == 2 else 1
            self.reserve(units, settings["limit_units"])
            try:
                result = await evaluate(settings, text, audio)
            except AssessmentError as exc:
                result = {"status": exc.status, "message": str(exc)}
            self.cache[attempt_id] = (fingerprint, result)
            if len(self.cache) > 200:
                del self.cache[next(iter(self.cache))]
            return result
