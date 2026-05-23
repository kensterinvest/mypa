# Changelog

All notable changes to MyPA follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — install paths
- **Docker support** — full compose stack at `docker/` directory.
  Single `docker compose up -d` brings up API + MCP + ntfy + Caddy
  with TLS. Multi-stage Dockerfile shared by `mypa-api` and `mypa-mcp`;
  Caddy image builds the Angular dashboard from upstream at image
  build. Designed for NAS (Synology Container Manager, QNAP Container
  Station, Unraid, TrueNAS Scale), Raspberry Pi, home servers, or any
  Docker host.
- `docker/README.md` — install guide with NAS-specific notes
  (Synology reverse-proxy conflict resolution, Unraid Community Apps
  workflow, QNAP Container Station)
- `docker/.env.example` — pre-templated with all required + optional
  env vars; tells you exactly what to set + how to generate secrets
- `docker/entrypoint.sh` — applies migrations on first run, bootstraps
  the admin user from `MYPA_ADMIN_EMAIL` + `MYPA_ADMIN_PASSWORD`,
  rejects unreplaced `REPLACE-WITH-*` placeholder secrets, warns on
  empty `LETSENCRYPT_EMAIL`

### Added — dashboard
- **Item detail page** at `/app/items/:id` — full record with kind
  badge, status pill, priority, tags, due-date. Markdown-rendered body
  (handles `## headings`, `**bold**`, `*italic*`, `` `code` ``). Data
  fields as key-value table. Mark-complete + Edit + Delete actions
  with confirmation
- **Item create page** at `/app/items/new` — kind dropdown, body with
  markdown hint, tags, status, priority, due_at datetime-local picker,
  advanced JSON data with parse validation
- **Item edit page** at `/app/items/:id/edit` — same form, pre-populated;
  decision-append-only override checkbox (audit-logged on server)
- **Global toast service** — automatic notifications on network errors,
  session expiry, and 5xx server responses. Per-component inline error
  messages still work in parallel for form context.

### Added — attachment hardening (5-layer defence)
- **Caddy `request_body max_size 10MB`** on `/api/attachments*` via
  named matcher inside the existing `/api/*` block (preserves
  `handle_path` stripping). Applied to both bare-metal Caddyfile and
  `docker/caddy/Caddyfile`.
- **FastAPI Content-Length pre-check** — rejects oversize declared
  uploads with HTTP 413 before reading the body
- **Streaming-read with byte-level cap** (`_read_upload_capped`) —
  chunks `file.read(64KB)` in a loop, raises 413 the moment the
  accumulated size crosses `MAX_UPLOAD_BYTES`. Defends against
  chunked Transfer-Encoding uploads with no `Content-Length` header.
- **Magic-byte MIME validation** — first 8-12 bytes of the upload are
  checked against known signatures (JPEG `FF D8 FF`, PNG `89 50 4E 47…`,
  GIF, WebP, HEIC, PDF, MP3, OGG, WAV, WebM). Declared `Content-Type`
  must match the detected magic; if not, HTTP 415.
- **Per-user quota** — lifetime byte cap (`MAX_USER_BYTES`, default
  1 GB). One `SUM(bytes) WHERE user_id = ?` per upload. HTTP 413 when
  exceeded.
- **Disk-space check** — `shutil.disk_usage(blob_dir)` before write;
  refuses with HTTP 507 (Insufficient Storage) if free space below
  `MIN_FREE_DISK_BYTES` (default 1 GB).
- **Per-(user|IP) rate limit** on `POST /attachments` — default
  `20/hour`, env-tunable as `ATTACHMENT_RATE_LIMIT`.

### Added — image processing
- **Image resize at ingest** — Pillow downscales JPEG / PNG / WebP
  uploads to `IMAGE_MAX_DIMENSION` (default 2048 px on longest edge,
  Lanczos resampling, 85% JPEG quality). Typical phone photo:
  ~85% disk saving.
- **EXIF stripping** — metadata (including GPS coordinates) is
  dropped during the re-encode. Even when not resizing, JPEGs are
  re-saved without EXIF if the rewrite is actually smaller than the
  original.
- GIF (potentially animated) and HEIC (needs `pillow-heif`) are
  stored as-is; PDF and audio are never touched.

### Added — audit + observability
- **REST auth middleware** now publishes `user_id`, `scope`, and IP
  to the audit ContextVars (previously only the MCP middleware did
  this). REST routes can now call `audit()` with the same user
  tracking the MCP surface already had.
- **Attachment upload audit log** — every outcome (success, 413,
  415, 507, 403, 400) writes a JSON line to `AUDIT_LOG_PATH`. Includes
  user_id, declared mime, bytes, sha256 prefix for successes.

### Added — operator tooling
- `scripts/backup_secrets.sh` — creates a fresh openssl-encrypted
  bundle of `/etc/mypa/env` at `/srv/backups/secrets/secrets-DATE.tar.gz.enc`.
  Generates and prints the bundle password ONCE; old bundles stay in
  place until manually removed.

### Added — landing site (`site/`)
- **Cyber visual identity** — slate background, steel-cyan + coral
  accents, Geist display font, JetBrains Mono headers, dot-grid
  background, `[•]` brand monogram
- **Animated connection-hub hero** — SVG + GSAP MotionPath; MyPA at
  centre, six satellite nodes (claude, mcp, ntfy, calendar, dashboard,
  telegram), inbound/outbound pulses across the links; respects
  `prefers-reduced-motion`
- **7-scene animated demo** showing Claude × MyPA across kinds:
  capture variety, decision-with-outcome (append-only), morning
  digest push, morning briefing Q&A, travel intelligence, cross-MCP
  capture (Hotels.com books, MyPA remembers), cross-kind recall
- **Compound-advantage section** — "What changes when AI can reason
  over your archive": longitudinal reasoning, proactive surfacing,
  cross-AI orchestration, hybrid agency
- **Install-paths panel** — Docker vs bare-metal side-by-side with
  actual install commands inline
- **Server-spec panel** — minimum / comfortable / network + DNS
- **FAQ updates** — Synology/QNAP/Unraid, Raspberry Pi, "when do I
  need to reconnect the connector?", "why ntfy and not Claude's own
  notifications?", "is this for me?"

### Changed — security posture
- `/auth/login` per-IP-per-email throttle: 5 failed attempts per
  5-min window → HTTP 429
- **Refresh-token rotation** per RFC 6749 §10.4 / OAuth 2.1: every
  `/auth/refresh` and `/oauth/token` call with `grant_type=refresh_token`
  returns a new refresh token; the old one is marked used. Replaying
  a used token revokes the entire family (reason `'reuse'`).
- `disable_user()` now also `DELETE`s that user's refresh tokens
- Dashboard `tryRefresh()` stores the rotated refresh token
- **MCP `user_id` propagation** — middleware now sets `user_id` on the
  audit context var so every MCP tool call uses the correct scope
- Authenticated ntfy — `auth-default-access: deny-all` enforced; admin
  + `mypa-publisher` accounts provisioned via `setup.sh`; per-user
  ntfy account created with read-only access to the user's own topic;
  `rotate_notify_topic` and `disable_user` truly revoke the ntfy
  account (not just stop using it)

### Changed — repos
- `kensterinvest/mypa` and `kensterinvest/mypa-dashboard` made **public**
- `THREAT_MODEL.md` **removed** from the public repo (`git rm`) — kept
  local-only at `D:\dev\mypa-private\`. The detailed attack-surface
  map was a defender's checklist that reads as an attacker's roadmap
  on a public repo. `SECURITY.md` keeps the disclosure policy + scope
  but drops the "Hardening defaults" enumeration.
- Site has no public links to the threat model; the security section
  on the landing page points to `SECURITY.md` only

### Migrations
- `migrations/004_attachments.sql` — `attachments` table
- `migrations/005_notify_topic.sql` — `users.notify_topic`,
  `notify_token`, per-user notification ownership
- `migrations/006_attachment_audit.sql` — audit-related fields
  (depending on the actual file structure)
- `migrations/007_refresh_token_rotation.sql` — `used_at`, `family_id`,
  `parent_id`, `reason` columns on `oauth_refresh_tokens`

### Tests
- 76 backend tests (was 41 at the start of this work) — added 35
  covering: attachment limits + magic bytes, image resize + EXIF
  stripping, login throttle, refresh-token rotation, disable-user
  revocation, ntfy account lifecycle, dashboard CRUD via API,
  cross-user isolation at REST + MCP layers

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
- Image attachments — content-addressed dedup, user-scoped, safe
  `Content-Disposition: attachment` download
- Notifications via self-hosted ntfy with auth enabled — publisher
  and per-user read-only accounts, true revocation on rotate/disable,
  two MCP tools (pa_get_notify_prefs, pa_set_notify_prefs)
- Angular dashboard: email + password login, JWT + refresh, items list
  with kind filter + search
- Productisation: `setup.sh` interactive installer, `deploy/` templates,
  LICENSE, ADMIN_GUIDE, USER_GUIDE, OAUTH_SETUP, NOTIFICATIONS docs
