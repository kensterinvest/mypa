# Changelog

All notable changes to MyPA follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — connectors
- `pa_add` accepts `source` + `source_ref` (e.g. `"gmail"`, thread id).
  Saving the same pair again returns the existing item with
  `"duplicate": true`, so daily syncs can re-read overlapping mail safely.
- `pa_import_whatsapp`: archive a WhatsApp **Export chat** `.txt` as one
  searchable `chat` item per day (Android and iOS formats, dd/mm vs
  mm/dd auto-detected). Re-imports only add new messages. New `chat` kind.
- `docs/CONNECTORS.md` (how Gmail / Calendar / Drive / WhatsApp reach
  MyPA via Claude) and `docs/PRODUCT_ROADMAP.md` (install-for-anyone plan,
  owner-only encryption model).

### Fixed — reminder timing and queue health
- **Timezones were dropped on save.** SQLite stores wall time only, so
  `15:30+01:00` was saved as `15:30` and fired an hour late. All
  datetimes (`due_at`, reminder `fire_at`, `due_before` filters) are now
  converted to UTC before storage; naive inputs are read in the user's
  own `tz`. API/MCP output now carries an explicit `+00:00`.
  Items saved before this fix with a non-UTC offset keep their old
  (shifted) value.
- **Reminders fired early.** The dispatcher string-compared DB values
  (`2030-05-22 14:30`) with ISO strings (`2030-05-22T…`); since `' ' < 'T'`
  a reminder became due at 00:00 UTC on its date. The morning digest had
  the same bug (items due later today counted as "overdue"). Comparisons
  now use SQLite `julianday()`, which normalizes every stored format.
- **Stuck reminders blocked the queue.** Skipped reminders (no topic,
  realtime off, no user) are now closed out with a `last_error`; failed
  pushes are retried up to 5 times. Previously 100 such rows blocked all
  newer reminders, and re-enabling realtime replayed the backlog.
  Migration `008_reminder_delivery.sql` adds `attempts`/`last_error` and
  expires reminders more than a day overdue.
- Reminder `channel` now defaults to `ntfy` (Telegram delivery never existed).

### Security — access hardening
- **Read-only tokens can no longer write over MCP.** `BEARER_TOKEN_RO`
  and OAuth grants with only `mypa:read` were already blocked from REST
  writes, but every MCP write tool (`pa_add`, `pa_update`, `pa_delete`, …)
  ignored the scope. Write tools now return a read-only error.
- **Fail closed when a token maps to no user.** REST and MCP return 403
  instead of running unscoped (which exposed every user's items). Fresh
  installs must create an admin (`scripts/add_user.py`) before using the
  static bearer tokens.
- Ownerless legacy rows (`user_id IS NULL`) are no longer returned by
  `get` to every user; `scripts/backfill_admin_user.py` assigns them.
- Static bearer tokens are compared in constant time.
- The SQLCipher key is quote-escaped in `PRAGMA key`, matching the
  snapshot scripts.

### Changed — MCP tool surface
- New tools: `pa_list_reminders` and `pa_cancel_reminder` (snooze =
  cancel + re-add). `pa_get` now includes the item's pending reminders
  and attachments.
- `pa_list` gained `offset` and `order_by` (`updated` / `due` / `created`).
- `pa_search` matches every word in any order ("pizza london" finds
  "London's best pizza") instead of the exact phrase.
- `tag` filters match whole tags (`art` no longer matches `party`).
- `pa_update(due_at="")` clears a due date.
- Bad dates, comma tags and invalid notify prefs return an `error` that
  explains the fix instead of raising. Notify prefs (`tz`, hours, day)
  are validated in one place for REST and MCP.
- `pa_undo_last` only undoes saves from the last 10 minutes (it used to
  delete the newest item however old). Items saved via MCP are now
  `source="claude"`.
- Removed the `pa_extract_from_image` stub (it always failed).
- Fixed the stale "Telegram worker not yet active" note on reminders.
- **Weekly overdue catch-up now actually sends.** The
  `overdue_weekly_*` prefs had no job behind them. Migration
  `009_weekly_overdue.sql` adds `users.last_overdue_at`.
- README / USER_GUIDE no longer claim Markdown export or wiki-link
  resolution, which don't exist yet.

### Added — better search
- **Full-text search (FTS5).** Migration `010_items_fts.sql` adds a
  stemmed, accent-insensitive index over title/body/tags, kept in sync
  by triggers and backfilled on upgrade. Results are ranked (title hits
  above body hits) and words match as prefixes ("pizz" → "pizza").
  Falls back to word-by-word LIKE if the index is missing.
- **Filters on `data{}` fields** for `pa_list` and `pa_search`:
  `where=["cuisine=italian", "rating>=5"]`. Ops: `= != > >= < <= ~`
  (contains), case-insensitive text, dotted keys for nested fields.
  `pa_search` also takes `kind`.
- `scripts/apply_migrations.py` now splits SQL with SQLite's own parser
  (`mypa/migrate.py`), so triggers and `;` inside strings work.

### Added — recurrence and expiry alerts
- **Repeating reminders**: `pa_add_reminder(..., repeat="every 2 weeks")`
  (also daily, weekdays, weekly, fortnightly, monthly, quarterly, yearly,
  every N days/weeks/months/years). Occurrences are computed in the
  user's tz from the first one, so 9am stays 9am across DST and "monthly
  on the 31st" doesn't drift. After downtime, a repeating reminder sends
  once and resumes — no burst of missed occurrences.
- **Recurring todos**: a todo with `data.repeat` and a `due_at` creates
  its next occurrence when completed (`pa_complete` returns
  `next_occurrence`). Completing late never creates an already-overdue copy.
- **Expiry alerts**: pushes 30 / 7 / 1 days before any open item's
  `data` end date (`end`, `expires`, `renew_at`, `valid_until`, …) —
  contracts, warranties, passports. Includes the first line of the
  item's notes. Once per threshold per end date; renewing re-arms.
  New pref `expiry_alerts` (default on).
- Migration `011_recurrence_expiry.sql` adds `reminders.repeat`,
  `reminders.repeat_anchor` and the `expiry_alerts` table.

### Changed — MCP endpoint
- **Canonical MCP URL is now `https://<host>/mcp`** (Streamable HTTP).
  The old `https://<host>/mcp/sse` URL always spoke Streamable HTTP
  despite its name; it remains as an alias so existing connectors keep
  working, but new connectors should use `/mcp`. Classic SSE transport
  (deprecated in the MCP spec) is not served. Caddy configs
  (`deploy/Caddyfile.snippet`, `docker/caddy/Caddyfile`) gained a
  pass-through `handle /mcp` block — update your Caddyfile on upgrade.

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
