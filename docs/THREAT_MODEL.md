# MyPA — threat model

Last updated: 2026-05-21. Covers single-deployment multi-user model:
each install (typically a family or small org) has an admin/operator and
1–10 users; each user's items + reminders are isolated by `user_id`.

## What MyPA stores

- **Personal life data** — todos, dates, places visited, preferences,
  contracts, account metadata, contacts, decisions with reasoning, free
  notes. **Encrypted at rest** with SQLCipher (AES-256-CBC + HMAC-SHA512,
  PBKDF2 256K iters).
- **Attachments** (blobs) — image bytes stored unencrypted on disk at
  `/var/lib/mypa/blobs/` (encrypted-at-backup-time via the secrets
  bundle). Phase 3+.
- **OAuth tokens + clients** — in the same encrypted DB.
- **Audit log** — JSON-lines per tool call at `/var/log/mypa-mcp.log`.
  Includes timestamps, IP, scope, tool name, redacted args.

## Trust boundaries

```
┌────────────────── Trust boundary ──────────────────┐
│                                                    │
│  Caddy (TLS terminate)  ←—  internet               │
│       │                                            │
│  mypa-api (FastAPI)         mypa-mcp (FastMCP)     │
│       │       \              /                     │
│       │        ▶ bearer/JWT auth middleware ◀      │
│       │              │                             │
│       │              ▼                             │
│       │   service layer (mypa/service.py)          │
│       │              │                             │
│       │              ▼                             │
│       └────────── DB (SQLCipher) ──────────────────│
│                                                    │
│  /etc/mypa/env  ← only root + mypa user can read   │
│                                                    │
└────────────────────────────────────────────────────┘
```

## Threats and mitigations

### High likelihood / high impact

| Threat | Mitigation |
|---|---|
| **User's password leaks** (phishing, weak password, breach of their password manager) | Affects ONLY that user's data — items are isolated by `user_id`. Other users unaffected. Operator can disable a compromised user via `UPDATE users SET disabled_at = datetime('now') WHERE email = '...'` — their existing JWT stays valid until expiry (1h max for access, 30d for refresh); for instant revocation rotate `OAUTH_JWT_SECRET`. |
| **Admin bearer token leaks** (the operator's `BEARER_TOKEN_RW`) | Maps to admin user → full RW access to ALL data including all users. Rotate immediately. Same procedure as OAUTH_SETUP.md. Existing user JWTs unaffected (signed with `OAUTH_JWT_SECRET`). |
| **One user attempts to read/mutate another's data via direct API** | Service layer enforces `user_id` filter on every query. `pa_get` returns 404 if item belongs to another user; `pa_delete`/`pa_update` reject silently with 404. Tested in `tests/test_multi_tenant.py`. |
| **OAuth phishing** (attacker tricks user into authorizing a malicious client) | Strict redirect_uri allow-list at DCR time. Authorize page shows redirect URL prominently with warning. All registrations audit-logged. |
| **Stolen SQLCipher DB file** (server compromise, leaked backup) | DB is opaque AES bytes without the key. Key lives only in `/etc/mypa/env` (mode 0600) and password manager. Encrypted backups stay safe. |
| **Stolen `/etc/mypa/env`** (root compromise) | Everything is compromised. There's no defence below root. Mitigate: SSH key-only auth, no password root login, audit log, push-notification on backup failure to detect intrusion. |

### Medium likelihood / medium impact

| Threat | Mitigation |
|---|---|
| **Token exfiltration via API abuse** | Rate limit 60/min per IP (slowapi). Audit log shows source IP per call. |
| **DB corruption** (power loss, disk failure) | Nightly VACUUM INTO snapshot at 03:30 UTC, 30-day retention. zt-alert fires on cron failure. |
| **JWT compromise** | 1-hour access token TTL. Refresh token can be revoked by deleting from `oauth_refresh_tokens`. Nuclear option: rotate `OAUTH_JWT_SECRET` (invalidates ALL JWTs). |
| **Lost SQLCipher key** | Key in password manager. Backed up via the encrypted secrets bundle at `/srv/backups/secrets/secrets.tar.gz.enc` (refresh after every key change). Without the key, ALL data is unrecoverable. |
| **Misconfigured `allowed_hosts`** (DNS rebinding) | DNS-rebind protection ON by default. Only domains in `transport_security.allowed_hosts` work. |

### Low likelihood / variable impact

| Threat | Mitigation |
|---|---|
| **Audit log gap** (write fails between commit + log) | Audit is best-effort, post-commit. For a single-user system this is acceptable. For multi-tenant: revisit (use SQLAlchemy event hooks for transactional audit). |
| **Large request DoS** | No request body cap today. Add `app.add_middleware(...)` with `max_content_length` if hit. |
| **Frontend XSS via item body** | Dashboard renders body as plain text (no innerHTML); markdown rendering (planned) MUST use a safe sanitizer (e.g. DOMPurify). |
| **OAuth scope creep** | Only two scopes: `mypa:read`, `mypa:write`. Mapped to RO/RW. JWT verification rejects anything else as denied. |

## What MyPA does NOT protect against

- **Compromised mypa process** — running service holds SQLCipher key
  in memory, so anyone with root or process-level access reads
  plaintext.
- **TLS downgrade if Caddy is misconfigured** — Caddy enforces HSTS by
  default; verify with `curl -I https://...`.
- **Image content sent to external APIs** — Phase 3 image extraction
  uploads image bytes to Anthropic. OFF by default; opt-in only.
- **Social engineering** — user typing their bearer into a phishing
  site that mimics MyPA's authorize page. Mitigated by domain checking
  (HTTPS lock + URL bar) but not eliminated.
- **Lost devices with active sessions** — JWT in Claude.ai persists
  for 30 days (refresh) and 1 hour (access). To revoke a specific
  device: rotate `OAUTH_JWT_SECRET`.

## Recovery scenarios

### Lost laptop, key intact in password manager

1. New machine: install Claude Code + OpenSSH + git
2. Restore SSH key from password manager → `~/.ssh/id_ed25519` (chmod 600)
3. `git clone deploy@vps:/srv/git/claude-backup.git ~/.claude`
4. Add Claude.ai connector again (per OAUTH_SETUP.md)

### Lost SQLCipher key

⛔ **All MyPA data lost.** Keep multiple copies (password manager +
encrypted secrets bundle + ideally a printed paper backup in a safe).

### Suspected breach

1. Rotate `BEARER_TOKEN_RW` (blocks future OAuth logins)
2. Rotate `OAUTH_JWT_SECRET` (invalidates every existing JWT)
3. Inspect audit log for anomalous IPs/tool calls
4. Revoke all OAuth clients: `DELETE FROM oauth_clients`
5. Re-add Claude.ai (it'll DCR again)

## Update cadence

This document should be revisited after every:

- New auth mechanism added (e.g. multi-tenant adds per-user passwords)
- New integration added (Telegram/Gmail/Calendar widen the attack surface)
- New 3rd-party API used (each new dependency = new trust assumption)
- Security advisor review or external audit
