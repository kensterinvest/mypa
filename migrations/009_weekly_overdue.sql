-- 009 — weekly overdue catch-up bookkeeping.
--
-- The overdue_weekly_* prefs existed since 005 but no job read them.
-- last_overdue_at records when the weekly push last went out so it
-- fires at most once per user-local day.

ALTER TABLE users ADD COLUMN last_overdue_at TEXT;
