PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_pages (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL,
    table_kind TEXT NOT NULL CHECK (table_kind IN ('table1', 'table2')),
    page_no INTEGER NOT NULL CHECK (page_no > 0),
    url TEXT NOT NULL,
    page_title TEXT,
    expected_items INTEGER CHECK (expected_items IS NULL OR expected_items >= 0),
    html_path TEXT,
    html_sha256 TEXT,
    audio_url TEXT,
    audio_path TEXT,
    audio_sha256 TEXT,
    audio_codec TEXT,
    audio_duration_ms INTEGER CHECK (audio_duration_ms IS NULL OR audio_duration_ms >= 0),
    audio_sample_rate INTEGER CHECK (audio_sample_rate IS NULL OR audio_sample_rate > 0),
    audio_channels INTEGER CHECK (audio_channels IS NULL OR audio_channels > 0),
    audio_bitrate INTEGER CHECK (audio_bitrate IS NULL OR audio_bitrate >= 0),
    fetch_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (fetch_status IN ('pending', 'fetched', 'failed', 'skipped')),
    fetch_error TEXT,
    http_status INTEGER,
    fetched_at TEXT,
    UNIQUE (table_kind, page_no),
    UNIQUE (source_key, url)
);

CREATE TABLE IF NOT EXISTS entries (
    item_id TEXT PRIMARY KEY
        CHECK (item_id GLOB 't[12]-[0-9][0-9][0-9][0-9][0-9]'),
    source_page_id INTEGER NOT NULL,
    table_kind TEXT NOT NULL CHECK (table_kind IN ('table1', 'table2')),
    source_local TEXT,
    page_position INTEGER NOT NULL CHECK (page_position > 0),
    global_seq INTEGER NOT NULL CHECK (global_seq > 0),
    word_raw TEXT NOT NULL CHECK (length(word_raw) > 0),
    pinyin_raw TEXT NOT NULL CHECK (length(pinyin_raw) > 0),
    pinyin_nfc TEXT NOT NULL CHECK (length(pinyin_nfc) > 0),
    FOREIGN KEY (source_page_id) REFERENCES source_pages(id) ON DELETE CASCADE,
    UNIQUE (table_kind, global_seq),
    UNIQUE (source_page_id, page_position)
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL,
    clip_path TEXT,
    clip_sha256 TEXT,
    algorithm_version TEXT NOT NULL,
    advert_match INTEGER CHECK (advert_match IS NULL OR advert_match IN (0, 1)),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    start_ms_raw INTEGER CHECK (start_ms_raw IS NULL OR start_ms_raw >= 0),
    end_ms_raw INTEGER CHECK (end_ms_raw IS NULL OR end_ms_raw >= 0),
    start_ms_adjusted INTEGER CHECK (start_ms_adjusted IS NULL OR start_ms_adjusted >= 0),
    end_ms_adjusted INTEGER CHECK (end_ms_adjusted IS NULL OR end_ms_adjusted > start_ms_adjusted),
    boundary_adjustment_ms INTEGER NOT NULL DEFAULT 0,
    CHECK (
        (start_ms_adjusted IS NULL AND end_ms_adjusted IS NULL)
        OR (
            start_ms_adjusted IS NOT NULL
            AND end_ms_adjusted IS NOT NULL
            AND end_ms_adjusted > start_ms_adjusted
        )
    ),
    FOREIGN KEY (item_id) REFERENCES entries(item_id) ON DELETE CASCADE,
    UNIQUE (item_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'needs_review')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    issue_code TEXT,
    original_start_ms INTEGER CHECK (original_start_ms IS NULL OR original_start_ms >= 0),
    original_end_ms INTEGER CHECK (original_end_ms IS NULL OR original_end_ms > original_start_ms),
    adjusted_start_ms INTEGER CHECK (adjusted_start_ms IS NULL OR adjusted_start_ms >= 0),
    adjusted_end_ms INTEGER CHECK (adjusted_end_ms IS NULL OR adjusted_end_ms > adjusted_start_ms),
    clip_sha256 TEXT,
    reviewer TEXT,
    notes TEXT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    FOREIGN KEY (item_id) REFERENCES entries(item_id) ON DELETE CASCADE,
    UNIQUE (item_id, revision),
    CHECK (
        (adjusted_start_ms IS NULL AND adjusted_end_ms IS NULL)
        OR (
            adjusted_start_ms IS NOT NULL
            AND adjusted_end_ms IS NOT NULL
            AND adjusted_end_ms > adjusted_start_ms
        )
    )
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    parameters_json TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_source_page ON entries(source_page_id);
CREATE INDEX IF NOT EXISTS idx_entries_global_seq ON entries(table_kind, global_seq);
CREATE INDEX IF NOT EXISTS idx_segments_item ON segments(item_id);
CREATE INDEX IF NOT EXISTS idx_reviews_item ON reviews(item_id);
CREATE INDEX IF NOT EXISTS idx_reviews_revision ON reviews(item_id, revision);
CREATE INDEX IF NOT EXISTS idx_runs_command ON runs(command);

INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 1);
