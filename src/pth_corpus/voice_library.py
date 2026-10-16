"""Optional immutable replacement audio library; original corpus stays read-only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading


def file_digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class VoiceLibrary:
    def __init__(self, data_root: Path):
        self.root = data_root.resolve()
        self.pointer = self.root / 'derived' / 'voice-conversion' / 'active.json'
        self._key = None
        self._manifest_path: Path | None = None
        self._manifest: dict = {}
        self._voices: dict[str, dict] = {}
        self._paths: list[Path] = []
        self._default_voice: str | None = None
        self._version: str | None = None
        self._error: str | None = None
        self._lock = threading.Lock()

    def _inside(self, value: str) -> Path:
        path = (self.root / value).resolve()
        path.relative_to(self.root)
        return path

    @staticmethod
    def _stamp(path: Path):
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def _load(self) -> None:
        with self._lock:
            try:
                if not self.pointer.exists():
                    self._manifest = {}
                    self._voices = {}
                    self._paths = []
                    self._default_voice = None
                    self._version = None
                    self._error = None
                    self._key = None
                    self._manifest_path = None
                    return
                self.pointer.resolve().relative_to(self.root)
                pointer_stamp = self._stamp(self.pointer)
                if self._manifest_path is not None:
                    try:
                        key = (pointer_stamp, tuple(self._stamp(p) for p in self._paths))
                        if key == self._key:
                            return
                    except OSError:
                        pass
                pointer = json.loads(self.pointer.read_text(encoding='utf-8'))
                if pointer['version'] not in (1, 2):
                    raise ValueError('Unsupported active voice library version')
                descriptors = pointer.get('voices') if pointer['version'] == 2 else {pointer.get('voice', 'news-female'): pointer}
                if not isinstance(descriptors, dict) or not descriptors:
                    raise ValueError('Invalid voice library choices')
                voices, paths = {}, []
                mapping = None
                for voice, descriptor in descriptors.items():
                    path = self._inside(descriptor['manifest'])
                    if file_digest(path) != descriptor['sha256']:
                        raise ValueError('Voice library manifest hash mismatch')
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    if manifest['version'] != 1 or not isinstance(manifest['clips'], dict):
                        raise ValueError('Invalid voice library manifest')
                    if manifest['clip_count'] != len(manifest['clips']):
                        raise ValueError('Voice library clip count mismatch')
                    current = {key: (entry['kind'], entry['original_relative_path'])
                               for key, entry in manifest['clips'].items()}
                    if mapping is not None and current != mapping:
                        raise ValueError('Voice libraries cover different original clips')
                    if pointer['version'] == 2 and any(
                            entry.get('voice') != voice for entry in manifest['clips'].values()):
                        raise ValueError('Voice library voice mismatch')
                    mapping = current
                    voices[voice] = manifest
                    paths.append(path)
                default = pointer.get('default_voice', next(iter(voices)))
                if default not in voices:
                    raise ValueError('Default voice is unavailable')
                self._voices, self._paths, self._default_voice = voices, paths, default
                self._manifest = voices[default]
                self._manifest_path = paths[0]
                self._version = file_digest(self.pointer)[:16]
                self._key = (pointer_stamp, tuple(self._stamp(p) for p in paths))
                self._error = None
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._manifest = {}
                self._voices = {}
                self._paths = []
                self._default_voice = None
                self._manifest_path = None
                self._version = None
                self._key = None
                self._error = str(exc)

    def replacement(self, clip_id: str, kind: str, original: Path,
                    voice: str | None = None) -> Path | None:
        self._load()
        selected_voice = self._default_voice if voice is None else voice
        manifest = self._voices.get(selected_voice, {})
        entry = manifest.get('clips', {}).get(clip_id)
        if entry is None:
            return None
        try:
            original_relative = original.resolve().relative_to(self.root).as_posix()
            if entry['kind'] != kind or entry['original_relative_path'] != original_relative:
                raise ValueError('Voice library original mapping mismatch: ' + clip_id)
            path = self._inside(entry['replacement'])
            if file_digest(path) != entry['sha256']:
                raise ValueError('Voice library clip hash mismatch: ' + clip_id)
            return path
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._error = str(exc)
            return None

    def status(self) -> dict:
        self._load()
        clips = self._manifest.get('clips', {})
        return {'active': bool(self._manifest), 'version': self._version,
                'clip_count': len(clips), 'error': self._error,
                'default_voice': self._default_voice,
                'voices': [{'id': voice, 'label': {'news-female': '新闻女声',
                            'news-male': '新闻男声'}.get(voice, voice),
                            'clip_count': len(manifest['clips'])}
                           for voice, manifest in self._voices.items()]}
