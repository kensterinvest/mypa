-- 007 — refresh token rotation (RFC 6749 §10.4, OAuth 2.1).
--
-- Adds the columns needed to detect refresh-token REUSE and revoke
-- the entire token family when reuse is detected. Pattern:
--   - On consume: mark used_at = now, issue a new token with the
--     same family_id.
--   - On consume of an already-used token (used_at IS NOT NULL):
--     revoke every token in the family (set revoked_at). Attacker
--     and legit holder both lose access; legit user re-logs in.
--
-- New columns:
--   used_at      : when this token was exchanged (NULL until consumed)
--   family_id    : groups successive rotations of the same logical session
--   parent_id    : the token this one was rotated FROM (debug/forensics)
--   reason       : why revoked, if revoked_at IS NOT NULL ('reuse', 'disable', 'logout', ...)

ALTER TABLE oauth_refresh_tokens ADD COLUMN used_at DATETIME;
ALTER TABLE oauth_refresh_tokens ADD COLUMN family_id TEXT;
ALTER TABLE oauth_refresh_tokens ADD COLUMN parent_id TEXT;
ALTER TABLE oauth_refresh_tokens ADD COLUMN reason TEXT;

CREATE INDEX IF NOT EXISTS idx_oauth_refresh_family ON oauth_refresh_tokens(family_id);
