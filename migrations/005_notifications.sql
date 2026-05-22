-- 005 — per-user notification settings.
--
-- Each user gets:
--   - tz             : IANA timezone, used to compute "today" + digest hour
--   - notify_topic   : random 16-char identifier; the ntfy URL is
--                      https://ntfy.<host>/<notify_topic>. Privacy via
--                      unguessability — anyone with the topic can read,
--                      so don't share it. Rotatable.
--   - notify_prefs   : JSON. Default empty {} is interpreted by code as
--                      "all defaults", so we don't need backfill SQL to
--                      populate it.

ALTER TABLE users ADD COLUMN tz TEXT NOT NULL DEFAULT 'Etc/UTC';
ALTER TABLE users ADD COLUMN notify_topic TEXT;
ALTER TABLE users ADD COLUMN notify_prefs TEXT NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN last_digest_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_notify_topic ON users(notify_topic)
    WHERE notify_topic IS NOT NULL;
