CREATE TABLE IF NOT EXISTS incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    severity    TEXT    NOT NULL DEFAULT 'unknown',
    service     TEXT    DEFAULT '',
    namespace   TEXT    DEFAULT '',
    symptoms    TEXT    DEFAULT '',
    root_cause  TEXT    DEFAULT '',
    resolution  TEXT    DEFAULT '',
    tags        TEXT    DEFAULT '[]',
    resolved    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS patterns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL UNIQUE,
    frequency   INTEGER DEFAULT 1,
    last_seen   TEXT    NOT NULL,
    example_ids TEXT    DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS context (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS incidents_fts
USING fts5(
    title, symptoms, root_cause, resolution,
    content='incidents', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS incidents_fts_insert
AFTER INSERT ON incidents BEGIN
    INSERT INTO incidents_fts(rowid, title, symptoms, root_cause, resolution)
    VALUES (new.id, new.title, new.symptoms, new.root_cause, new.resolution);
END;

CREATE TRIGGER IF NOT EXISTS incidents_fts_update
AFTER UPDATE ON incidents BEGIN
    INSERT INTO incidents_fts(incidents_fts, rowid, title, symptoms, root_cause, resolution)
    VALUES ('delete', old.id, old.title, old.symptoms, old.root_cause, old.resolution);
    INSERT INTO incidents_fts(rowid, title, symptoms, root_cause, resolution)
    VALUES (new.id, new.title, new.symptoms, new.root_cause, new.resolution);
END;
