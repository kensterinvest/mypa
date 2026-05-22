<div align="center">

<img src="site/assets/img/logo-mark.svg" width="84" alt="MyPA — the cyber [•] monogram on slate, in steel-cyan and coral">

# MyPA — My Personal Archive, for AI

**The memory layer underneath your AI. Self-hosted, encrypted, owned by you.**

[🌐 **Live site &amp; demo** →](https://mypa.z-tidus.com/) &nbsp;·&nbsp;
[📖 Quick start](#quick-start) &nbsp;·&nbsp;
[🛡️ Security policy](SECURITY.md) &nbsp;·&nbsp;
[📝 Changelog](CHANGELOG.md) &nbsp;·&nbsp;
[⚙️ Admin guide](docs/ADMIN_GUIDE.md) &nbsp;·&nbsp;
[👤 User guide](docs/USER_GUIDE.md)

[![CI](https://github.com/kensterinvest/mypa/actions/workflows/ci.yml/badge.svg)](https://github.com/kensterinvest/mypa/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-7CC4FF)](LICENSE)
![Version: v1.0.0](https://img.shields.io/badge/version-v1.0.0-FF6B5B)
![Status: production](https://img.shields.io/badge/status-production-A8E6B4)

</div>

---

## What is MyPA?

Modern AI has memory now — Claude, ChatGPT, Copilot all remember things
across chats. That memory is useful, but it lives on the vendor's servers,
is bound to one product, can be silently rewritten, doesn't reach outside
the chat, and disappears if you change provider or they change pricing.

**MyPA is the archive layer underneath.** A self-hosted SQLite-on-your-VPS
personal knowledge base — structured, queryable, encrypted at rest,
multi-user per install — that any AI speaking the open
[MCP protocol](https://modelcontextprotocol.io) can read and write.

Today Claude reads your archive. Tomorrow whatever's next does too.
The archive doesn't migrate; the AI does.

**See the live site for the full pitch + animated demo →
[mypa.z-tidus.com](https://mypa.z-tidus.com/)**

## Why it's different from native AI memory

| | Claude.ai memory | ChatGPT memory | MyPA |
|---|---|---|---|
| Carries context across chats | ✓ within Claude | ✓ within ChatGPT | ✓ across **any** MCP-AI |
| Structured queries (kind, date, tag) | freeform text | freeform text | ✓ kinds, fields, FTS5 |
| Append-only decision history | silently revised | silently revised | ✓ verbatim, forever |
| Pushes reminders to your phone | ✗ | ✗ | ✓ self-hosted ntfy |
| Multi-user (family / small org) | 5 × subscriptions | 5 × subscriptions | 1 install, isolated |
| Lives on your hardware | ✗ Anthropic cloud | ✗ OpenAI cloud | ✓ your VPS |
| Vendor can read your data | yes | yes | **no** |
| Moves with you to the next AI | ✗ Claude-only | ✗ ChatGPT-only | ✓ MCP is open |
| Family-of-5 cost / month | ~£75 | ~£80 | **~£10** (just the VPS) |

**Use both.** Native memory for conversational style. MyPA for the
durable, structured facts of your life.

## Features

- **Multi-tenant** — one install serves a family or small org, each user
  isolated; verified by tests at three layers (service / REST / MCP)
- **SQLCipher** AES-256 encryption at rest; backups equally opaque
- **OAuth 2.1 + PKCE** for Claude.ai connector login, with RFC 6749 §10.4
  refresh-token rotation and reuse detection
- **10 MCP tools**: `pa_add`, `pa_get`, `pa_list`, `pa_search`,
  `pa_describe_schema`, `pa_undo_last`, `pa_delete`, `pa_update`,
  `pa_complete`, `pa_add_reminder`, plus `pa_attach_image`,
  `pa_get_notify_prefs`, `pa_set_notify_prefs`
- **Push notifications** via self-hosted [ntfy](https://ntfy.sh), with
  authenticated publish + per-user read tokens (no spoofing)
- **REST API + Angular dashboard** for browsing
- **Image attachments** — content-addressed, deduplicated, user-scoped
- **MIT licensed**, end-to-end exportable as Markdown + YAML

## Quick start

You'll need: a Linux VPS (Hetzner, IONOS, DigitalOcean — ~£8-15/mo), a
domain pointed at it, root SSH.

```bash
# 1. Point your domain at the VPS:
#    Add A records for  mypa.example.com  and  ntfy.example.com  → your IP
#
# 2. Clone and install (installs caddy, sqlcipher, ntfy, python deps,
#    systemd units, sudoers, Let's Encrypt; configures auth on every layer):
git clone https://github.com/kensterinvest/mypa.git /opt/mypa
cd /opt/mypa
sudo bash setup.sh
#
# 3. Save the credentials it prints (BEARER_TOKEN_RW, SQLCIPHER_KEY,
#    OAUTH_JWT_SECRET, NTFY_ADMIN_PASSWORD, NTFY_PUBLISH_PASSWORD).
#    Losing SQLCIPHER_KEY = losing the database. No recovery.
#
# 4. Connect Claude.ai (desktop browser):
#    Settings → Connectors → + Add custom →
#    URL: https://mypa.example.com/mcp/sse → Sign in with email+password.
#    Your phone inherits the connector automatically.
```

Full walkthrough: [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md) and
[docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md).

## Architecture

```
   Claude.ai (mobile + desktop)         Web dashboard            Phone (ntfy)
              │                              │                       ▲
              │ OAuth 2.1 + JWT              │ email+password         │ push
              ▼                              ▼                       │
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Caddy on mypa.example.com:443                                       │
   │    /                        → static landing page                    │
   │    /app/*                   → Angular dashboard                      │
   │    /api/*, /auth/*          → mypa-api (FastAPI + OAuth)             │
   │    /mcp/*                   → mypa-mcp (MCP Streamable HTTP)         │
   │    /oauth/*, /.well-known/* → mypa-api (OAuth endpoints)             │
   └─────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
                  SQLCipher-encrypted SQLite at /var/lib/mypa/mypa.db
                  Blobs at /var/lib/mypa/blobs/
                  Nightly VACUUM INTO snapshots, 30d retention
                  Push via self-hosted ntfy.example.com (auth required)
```

## Documentation

| Doc | For |
|---|---|
| [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md) | Connecting Claude.ai mobile + desktop |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | ntfy setup, push notifications, mobile app config |
| [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | Operators — user management, backups, rotation, recovery |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | End users — dashboard + Claude usage |
| [SECURITY.md](SECURITY.md) | Vulnerability disclosure policy |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

## Development

```bash
git clone https://github.com/kensterinvest/mypa.git
cd mypa
python -m venv .venv
.venv/bin/pip install \
  "fastapi>=0.110" "uvicorn[standard]>=0.27" "mcp>=1.27" \
  "sqlalchemy>=2" "pydantic>=2.5" "pydantic-settings>=2" \
  "httpx>=0.27" "pyjwt[crypto]>=2.8" "slowapi" "apscheduler>=3.10" \
  "pytest>=8" "python-multipart>=0.0.9"
export TEST_NO_ENCRYPTION=true
export NTFY_USER_MGMT_ENABLED=false
export BEARER_TOKEN_RW=test
export BEARER_TOKEN_RO=test
export OAUTH_JWT_SECRET=test
PYTHONPATH=. pytest -q
```

56 tests cover the security boundaries: cross-user isolation, OAuth + DCR,
refresh-token rotation + reuse detection, login throttle, decision
append-only enforcement, attachment dedup + isolation, ntfy account
lifecycle.

## Repo layout

```
mypa/
├── mypa/             # FastAPI app + MCP server + OAuth + scheduler
├── migrations/       # 007 SQL migrations (001..007)
├── scripts/          # init_db, add_user, change_password, backfills
├── tests/            # 56 tests, pytest
├── deploy/           # systemd units, Caddyfile snippet, logrotate
├── docs/             # OAUTH_SETUP, ADMIN_GUIDE, USER_GUIDE, etc.
├── site/             # The static landing page deployed to mypa.z-tidus.com/
├── setup.sh          # Single-command installer
├── README.md         # this file
├── LICENSE           # MIT
├── SECURITY.md
└── CHANGELOG.md
```

## License

MIT — see [LICENSE](LICENSE). Use it. Fork it. Self-host it. Sell support
around it. Ship it inside your product. The code is yours.

## Acknowledgements

Built on the shoulders of:
[FastAPI](https://fastapi.tiangolo.com),
[SQLCipher](https://www.zetetic.net/sqlcipher/),
[ntfy](https://ntfy.sh),
[Caddy](https://caddyserver.com),
[Angular](https://angular.dev),
[Model Context Protocol](https://modelcontextprotocol.io).
