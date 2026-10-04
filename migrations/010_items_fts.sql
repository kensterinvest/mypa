-- 010 — full-text search over items (title, body, tags).
--
-- External-content FTS5 table: the text lives once, in `items`; the
-- index is kept in sync by triggers. `porter` stemming means "running"
-- finds "run"; remove_diacritics makes "cafe" find "café".
-- Search falls back to LIKE if this table is missing.

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, body, tags,
    content='items', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, body, tags)
    VALUES (new.id, new.title, new.body, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, body, tags)
    VALUES ('delete', old.id, old.title, old.body, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE OF title, body, tags ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, body, tags)
    VALUES ('delete', old.id, old.title, old.body, old.tags);
    INSERT INTO items_fts(rowid, title, body, tags)
    VALUES (new.id, new.title, new.body, new.tags);
END;

-- Index everything saved before this migration.
INSERT INTO items_fts(items_fts) VALUES ('rebuild');
