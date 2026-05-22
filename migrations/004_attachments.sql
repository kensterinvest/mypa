-- 004 — attachments table. Content-addressed storage of uploaded files
-- (images now, potentially audio/PDF later). Blob bytes live on disk at
-- /var/lib/mypa/blobs/YYYY/MM/<sha256>.<ext>; this table is the index.
--
-- Per-user isolation enforced by user_id FK. item_id is nullable so an
-- upload can land before being linked to an item (useful when the
-- workflow is upload-first / classify-later).

CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id     INTEGER REFERENCES items(id) ON DELETE SET NULL,
    sha256      TEXT NOT NULL,
    mime        TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    path        TEXT NOT NULL,          -- relative to BLOB_DIR
    alt_text    TEXT,
    exif_json   TEXT,                   -- populated only when IMPLICIT_LOCATION_CAPTURE=true (nullable)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One copy of identical bytes per user (dedup within-user only — different
-- users uploading the same photo each get their own row, but the blob on
-- disk is still deduped because sha256 is content-addressed).
CREATE UNIQUE INDEX IF NOT EXISTS uq_attachments_user_sha ON attachments(user_id, sha256);
CREATE INDEX IF NOT EXISTS idx_attachments_item ON attachments(item_id);
CREATE INDEX IF NOT EXISTS idx_attachments_user ON attachments(user_id);
