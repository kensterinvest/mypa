-- 008 — reminder delivery bookkeeping.
--
-- Before this, a reminder that was skipped (no topic, realtime off, user
-- missing) or whose push failed stayed "due" forever. The dispatcher reads
-- the 100 oldest due rows per tick, so enough stuck rows blocked every
-- newer reminder.
--
--   attempts   : failed publish attempts; closed out after a few
--   last_error : why it was skipped / failed (NULL when delivered)

ALTER TABLE reminders ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reminders ADD COLUMN last_error TEXT;

-- Close out the stale backlog so upgrading doesn't blast old pushes.
UPDATE reminders
   SET fired_at = datetime('now'), last_error = 'expired: stale at migration 008'
 WHERE fired_at IS NULL
   AND julianday(fire_at) < julianday('now', '-1 day');
