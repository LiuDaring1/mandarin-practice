import sqlite3

import pytest

from pth_corpus.db import connect_db, init_db


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_init_db_creates_schema_and_enables_foreign_keys(tmp_path):
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)

    with connect_db(db_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "schema_version",
            "source_pages",
            "entries",
            "segments",
            "reviews",
            "runs",
            "excluded_items",
        } <= tables
        assert connection.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()[0] == 2

        assert {"item_id", "source_page_id", "page_position", "word_raw", "pinyin_raw", "pinyin_nfc"} <= _columns(connection, "entries")
        assert {
            "expected_items",
            "audio_url",
            "html_path",
            "html_sha256",
            "audio_path",
            "audio_sha256",
            "audio_codec",
            "audio_duration_ms",
            "audio_sample_rate",
            "audio_channels",
            "audio_bitrate",
            "fetch_status",
            "fetch_error",
        } <= _columns(connection, "source_pages")
        assert {
            "item_id",
            "clip_path",
            "clip_sha256",
            "algorithm_version",
            "advert_match",
            "confidence",
            "start_ms_raw",
            "end_ms_raw",
            "start_ms_adjusted",
            "end_ms_adjusted",
        } <= _columns(connection, "segments")
        assert {
            "item_id",
            "status",
            "revision",
            "issue_code",
            "original_start_ms",
            "original_end_ms",
            "adjusted_start_ms",
            "adjusted_end_ms",
            "clip_sha256",
            "reviewer",
            "timestamp",
        } <= _columns(connection, "reviews")


def test_foreign_keys_unique_ids_and_review_history(tmp_path):
    db_path = tmp_path / "corpus.sqlite3"
    init_db(db_path)
    with connect_db(db_path) as connection:
        connection.execute(
            "INSERT INTO source_pages "
            "(source_key, table_kind, page_no, url, expected_items) "
            "VALUES ('pthxx', 'table1', 1, 'http://example.test/01.html', 100)"
        )
        page_id = connection.execute("SELECT id FROM source_pages").fetchone()[0]
        connection.execute(
            "INSERT INTO entries "
            "(item_id, source_page_id, table_kind, page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc) "
            "VALUES ('t1-00001', ?, 'table1', 1, 1, '阿', 'ā', 'ā')",
            (page_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO entries "
                "(item_id, source_page_id, table_kind, page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc) "
                "VALUES ('t1-00001', ?, 'table1', 2, 2, '阿姨', 'āyí', 'āyí')",
                (page_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO entries "
                "(item_id, source_page_id, table_kind, page_position, global_seq, word_raw, pinyin_raw, pinyin_nfc) "
                "VALUES ('t1-00002', ?, 'table1', 2, 1, '阿姨', 'āyí', 'āyí')",
                (page_id,),
            )
        connection.execute(
            "INSERT INTO segments "
            "(item_id, algorithm_version, start_ms, end_ms) "
            "VALUES ('t1-00001', 'v0', 0, 500)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO segments (item_id, algorithm_version, start_ms, end_ms) "
                "VALUES ('t1-00001', 'v1', 600, 700)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO segments "
                "(item_id, algorithm_version, start_ms, end_ms, start_ms_adjusted) "
                "VALUES ('t1-00001', 'v1', 600, 700, 610)"
            )
        connection.execute(
            "INSERT INTO reviews (item_id, status, revision, reviewer) "
            "VALUES ('t1-00001', 'approved', 1, 'alice')"
        )
        connection.execute(
            "INSERT INTO reviews (item_id, status, revision, reviewer) "
            "VALUES ('t1-00001', 'needs_review', 2, 'alice')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO reviews (item_id, status, revision, reviewer) "
                "VALUES ('t1-00001', 'rejected', 2, 'bob')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO reviews "
                "(item_id, status, revision, adjusted_start_ms) "
                "VALUES ('t1-00001', 'pending', 3, 10)"
            )
        assert connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO segments (item_id, algorithm_version, start_ms, end_ms) "
                "VALUES ('missing-item', 'v0', 0, 100)"
            )
