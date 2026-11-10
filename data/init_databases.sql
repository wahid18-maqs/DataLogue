ATTACH DATABASE 'data/workbooks/workbooks.db' AS workbooks_db;
ATTACH DATABASE 'data/presentations/presentations.db' AS presentations_db;

CREATE TABLE IF NOT EXISTS uploads (
    id          TEXT PRIMARY KEY,
    file_name   TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    file_data   BLOB NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uploads_uploaded_at
    ON uploads(uploaded_at DESC);

CREATE TABLE IF NOT EXISTS workbooks_db.workbooks (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT 'local',
    file_name       TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL,
    storage_path     TEXT NOT NULL,
    file_data       BLOB,
    status          TEXT NOT NULL,
    sheets          TEXT NOT NULL DEFAULT '[]',
    active_sheet_id TEXT,
    error_reason    TEXT
);

CREATE INDEX IF NOT EXISTS workbooks_db.idx_workbooks_uploaded_at
    ON workbooks(uploaded_at DESC);

CREATE TABLE IF NOT EXISTS presentations_db.presentations (
    filename   TEXT PRIMARY KEY,
    workbook_id TEXT,
    sheet_id   TEXT,
    pptx_data  BLOB NOT NULL,
    plan_json  TEXT NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}',
    feedback_json TEXT NOT NULL DEFAULT '[]',
    stale INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

DETACH DATABASE workbooks_db;
DETACH DATABASE presentations_db;
