"""Cross-session item history with a soft avoidance window."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(iso: str, now: datetime) -> float:
    try:
        used = datetime.fromisoformat(iso)
    except ValueError:
        return float("inf")
    if used.tzinfo is None:
        used = used.replace(tzinfo=timezone.utc)
    return (now - used).total_seconds() / 86400.0


@dataclass
class HistoryStore:
    profile_id: str
    path: Path
    window_days: int = 7
    window_sessions: int = 7
    session_seq: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, profile_id: str, path: Path,
             window_days: int = 7, window_sessions: int = 7
             ) -> "HistoryStore":
        store = cls(
            profile_id=profile_id,
            path=path,
            window_days=window_days,
            window_sessions=window_sessions,
        )
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                store.session_seq = int(data.get("session_seq", 0))
                store.entries = list(data.get("entries", []))
            except (json.JSONDecodeError, OSError, ValueError):
                store.entries = []
        store._prune()
        return store

    def _prune(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        recent_session_cut = self.session_seq - self.window_sessions + 1
        kept = []
        for entry in self.entries:
            session_no = int(entry.get("session_no", 0))
            within_days = _days_ago(entry.get("used_at", ""), now) <= self.window_days
            within_sessions = session_no >= recent_session_cut
            if within_days and within_sessions:
                kept.append(entry)
        self.entries = kept

    def recent_item_ids(self) -> set[str]:
        self._prune()
        return {str(e["item_id"]) for e in self.entries}

    def add_session(self, session_id: str, item_ids: list[str],
                    now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.session_seq += 1
        for item_id in item_ids:
            self.entries.append(
                {
                    "item_id": item_id,
                    "session_id": session_id,
                    "session_no": self.session_seq,
                    "used_at": now.isoformat(),
                }
            )
        self._prune(now)

    def save(self) -> None:
        self._prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profile_id": self.profile_id,
            "session_seq": self.session_seq,
            "window_days": self.window_days,
            "window_sessions": self.window_sessions,
            "entries": self.entries,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
