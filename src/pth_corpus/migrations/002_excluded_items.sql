CREATE TABLE IF NOT EXISTS excluded_items (
    item_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES entries(item_id) ON DELETE CASCADE
);
