"""Isolated Suntone probe. No APP integration; never logs signed URLs or credentials."""
from __future__ import annotations
import asyncio
import base64
from datetime import datetime, timezone
from email.utils import format_datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import websockets

HOST = 'cn-east-1.ws-api.xf-yun.com'
PATH = '/v1/private/s8e098720'


def signed_url(config, date=None):
    date = date or format_datetime(datetime.now(timezone.utc), usegmt=True)
    origin = f'host: {HOST}\ndate: {date}\nGET {PATH} HTTP/1.1'
    signature = base64.b64encode(hmac.new(config['api_secret'].encode(), origin.encode(), hashlib.sha256).digest()).decode()
    authorization = f'api_key="{config["api_key"]}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
    return f'wss://{HOST}{PATH}?' + urlencode({'host': HOST, 'date': date, 'authorization': base64.b64encode(authorization.encode()).decode()})


def parameters(reference, core='word', **extra):
    return {'lang': 'cn', 'core': core, 'refText': reference, 'phoneme_output': 1,
            'scale': 100, 'precision': 1, 'slack': 0, 'vad': 0,
            'attachAudioUrl': 0, 'getParam': 0,
            'result': {'encoding': 'utf8', 'compress': 'raw', 'format': 'plain'}, **extra}


def frames(config, params, audio):
    # The service rejects an empty final audio packet.
    if len(audio) < 2:
        raise ValueError('Audio must contain at least two bytes')
    parts = [audio[i:i+1280] for i in range(0, len(audio), 1280)]
    if len(parts) == 1:
        midpoint = len(audio) // 2
        parts = [audio[:midpoint], audio[midpoint:]]
    for seq, chunk in enumerate(parts):
        status = 0 if seq == 0 else 2 if seq == len(parts)-1 else 1
        yield {'header': {'app_id': config['app_id'], 'status': status},
               'parameter': {'st': params},
               'payload': {'data': {'encoding': 'lame', 'sample_rate': 16000, 'channels': 1,
                                    'bit_depth': 16, 'status': status, 'seq': seq,
                                    'audio': base64.b64encode(chunk).decode(), 'frame_size': 0}}}


def private_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


async def evaluate(config, params, audio):
    async with asyncio.timeout(45):
        async with websockets.connect(signed_url(config), open_timeout=15, max_size=8_000_000) as ws:
            async def send():
                for packet in frames(config, params, audio):
                    await ws.send(json.dumps(packet, ensure_ascii=False))
                    await asyncio.sleep(.04)
            sender = asyncio.create_task(send())
            decoded = []
            try:
                async for message in ws:
                    envelope = json.loads(message)
                    header = envelope.get('header', {})
                    if header.get('code', 0):
                        message = str(header.get('message', ''))
                        for secret in config.values():
                            message = message.replace(str(secret), '[redacted]')
                        return {'status': 'provider_error', 'code': header['code'], 'message': message}
                    body = envelope.get('payload', {}).get('result', {})
                    if body.get('text'):
                        result = json.loads(base64.b64decode(body['text']).decode('utf8'))
                        decoded.append(result)
                        if result.get('eof') == 1:
                            return {'status': 'ok', 'payload': result}
                    if header.get('status') == 2 or body.get('status') == 2:
                        if decoded:
                            return {'status': 'ok', 'payload': decoded[-1]}
                        return {'status': 'missing_result'}
                return {'status': 'connection_closed'}
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)


class Probe:
    def __init__(self, directory, *, allow_paid=False, max_calls=64):
        self.directory = Path(directory)
        self.allow_paid, self.max_calls = allow_paid, max_calls

    async def call(self, audio_path, reference, core='word', **extra):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / 'probe.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another probe owns the request ledger; no call made') from None
            return await self._call_locked(audio_path, reference, core, **extra)
        finally:
            os.close(fd)

    async def _call_locked(self, audio_path, reference, core='word', **extra):
        audio = Path(audio_path).read_bytes()
        params = parameters(reference, core, **extra)
        key = hashlib.sha256(b'nonempty-final-v1' + json.dumps(params, sort_keys=True, ensure_ascii=False).encode() + audio).hexdigest()
        cache = self.directory / 'cache' / f'{key}.json'
        if cache.exists():
            return json.loads(cache.read_text())
        if not self.allow_paid:
            raise RuntimeError('Uncached API request requires --allow-paid')
        ledger_path = self.directory / 'requests.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        if len(ledger) >= self.max_calls:
            raise RuntimeError('Local request cap reached; no call made')
        if key in ledger:
            raise RuntimeError('Previously reserved call has no result; refusing automatic retry')
        config = json.loads((self.directory / 'config.json').read_text())
        ledger.append(key); private_json(ledger_path, ledger)
        try:
            result = await evaluate(config, params, audio)
        except Exception as exc:
            # Exception text may contain the signed URL. Keep only a safe class/status.
            result = {'status': 'transport_error', 'error_type': type(exc).__name__}
            response = getattr(exc, 'response', None)
            if response is not None:
                result['http_status'] = getattr(response, 'status_code', None)
        private_json(cache, result)
        return result


def public_result(response):
    """Allowlist only pronunciation fields, excluding session IDs, audio URLs, params."""
    if response['status'] != 'ok':
        return {k: response[k] for k in ('status', 'code', 'error_type', 'http_status') if k in response}
    result = response['payload'].get('result', {})
    allowed = ('overall', 'pronunciation', 'tone', 'integrity', 'fluency', 'duration', 'kernel_version', 'resource_version')
    out = {'status': 'ok', **{k: result[k] for k in allowed if k in result}, 'words': []}
    for word in result.get('words', []):
        fields = ('word', 'pinyin', 'tone', 'readType', 'span', 'scores', 'charType')
        row = {k: word[k] for k in fields if k in word}
        row['phonemes'] = [{k: p[k] for k in ('phone', 'phoneme', 'pronunciation', 'span', 'tone_index') if k in p} for p in word.get('phonemes', [])]
        out['words'].append(row)
    return out
