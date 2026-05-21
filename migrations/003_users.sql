-- 003_users.sql — multi-tenant within a single deployment.
-- Each MyPA install supports a family / small org. Operator-provisioned
-- accounts; per-user data isolation; OAuth issues JWTs with sub=user_id.

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    name            TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    last_login_at   DATETIME,
    disabled_at     DATETIME
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Add user_id to items + reminders. NULL initially; backfilled to admin user.
ALTER TABLE items     ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE reminders ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_items_user     ON items(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);
