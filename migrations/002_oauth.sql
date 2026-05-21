-- 002_oauth.sql — OAuth 2.1 server tables (clients + codes + refresh tokens)

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id            TEXT PRIMARY KEY,
    client_secret_hash   TEXT NOT NULL,
    name                 TEXT NOT NULL,
    redirect_uris        TEXT NOT NULL,
    scopes               TEXT NOT NULL DEFAULT 'mypa:read mypa:write',
    created_at           DATETIME NOT NULL DEFAULT (datetime('now')),
    last_used_at         DATETIME
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code                 TEXT PRIMARY KEY,
    client_id            TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    redirect_uri         TEXT NOT NULL,
    code_challenge       TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL DEFAULT 'S256',
    scope                TEXT NOT NULL,
    user_subject         TEXT NOT NULL,
    expires_at           DATETIME NOT NULL,
    used_at              DATETIME
);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_client ON oauth_codes(client_id);

CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token_id             TEXT PRIMARY KEY,
    client_id            TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    scope                TEXT NOT NULL,
    user_subject         TEXT NOT NULL,
    issued_at            DATETIME NOT NULL DEFAULT (datetime('now')),
    expires_at           DATETIME NOT NULL,
    revoked_at           DATETIME
);
