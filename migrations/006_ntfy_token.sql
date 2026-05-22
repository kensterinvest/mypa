-- 006 — per-user ntfy credentials.
--
-- Each MyPA user now has a dedicated ntfy account named after their
-- topic (e.g. user "u-4281195b6832d817" with read access to topic
-- "u-4281195b6832d817" only). The password is stored here so the
-- dashboard / API can return it once at user creation for mobile-app
-- setup. Rotating notify_topic also rotates this column.

ALTER TABLE users ADD COLUMN notify_token TEXT;
