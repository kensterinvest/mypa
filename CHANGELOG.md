# Changelog

All notable changes to MyPA follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `LICENSE` (MIT) — license is no longer "planned"; it's the actual file
- `SECURITY.md` — vulnerability disclosure policy, scope, hardening defaults
- `CHANGELOG.md` (this file)
- GitHub Actions CI: `pytest -q` on push and PR to `main`
- `/auth/login` per-IP-per-email throttle: 5 failed attempts per 5-min
  window returns HTTP 429 (no info leak about which combinations are
  cached)
- Refresh-token rotation per RFC 6749 §10.4 / OAuth 2.1:
  - Every `/auth/refresh` and `/oauth/token` call with `grant_type=refresh_token`
    now returns a *new* refresh token; the old one is marked used
  - Replaying a used token revokes the entire token family
    (`reason = 'reuse'`) — both the attacker's copy and the legit
    successor die, forcing re-login

### Changed
- `disable_user()` now also `DELETE`s that user's refresh tokens —
  surgical revoke per user, no need to rotate `OAUTH_JWT_SECRET`
- Dashboard `tryRefresh()` stores the rotated refresh token (was
  silently dropping it; with rotation enabled that would have
  triggered family revoke on the next call)

### Migrations
- `migrations/007_refresh_token_rotation.sql`: adds `used_at`,
  `family_id`, `parent_id`, `reason` columns to `oauth_refresh_tokens`

## [0.1.0] — 2026-05-22

First tagged version. Documented for completeness — earlier work
landed without version tags.

### Features
- FastAPI REST + MCP server with OAuth 2.1 + PKCE for Claude.ai
  connectors
- SQLCipher-encrypted SQLite DB (AES-256, PBKDF2 256k iters)
- Multi-tenant user accounts with per-user item isolation, enforced
  at service, REST, and MCP layers
- 10 MCP tools (pa_add, pa_get, pa_list, pa_search, pa_describe_schema,
  pa_undo_last, pa_delete, pa_update, pa_complete, pa_add_reminder)
- Phase 3: image attachments — content-addressed dedup, user-scoped,
  safe `Content-Disposition: attachment` download
- Phase 4: notifications via self-hosted ntfy with auth enabled —
  publisher and per-user read-only accounts, true revocation on
  rotate/disable, two MCP tools (pa_get_notify_prefs, pa_set_notify_prefs)
- Angular dashboard: email + password login, JWT + refresh, items list
  with kind filter + search
- Productisation: `setup.sh` interactive installer, `deploy/` templates,
  LICENSE, ADMIN_GUIDE, USER_GUIDE, OAUTH_SETUP, NOTIFICATIONS,
  THREAT_MODEL docs
