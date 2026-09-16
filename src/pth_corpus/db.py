"""SQLite connection and initial schema helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data/corpus.sqlite3")
SCHEMA_PATH = Path(__file__).with_name("migrations") / "001_initial.sql"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def connect_db(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled."""

    db_path = str(path)
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(path: str | Path = DEFAULT_DB_PATH) -> Path | str:
    """Apply pending schema migrations idempotently."""

    with connect_db(path) as connection:
        migrations = sorted(
            MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL CHECK (version >= 1),
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        current = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version"
            ).fetchone()[0]
        )
        for migration in migrations:
            version = int(migration.name[:3])
            if version <= current:
                continue
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT OR REPLACE INTO schema_version (id, version, applied_at)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                """,
                (version,),
            )
    return path
