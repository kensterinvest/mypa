# MyPA — personal AI hub

**Encrypted personal knowledge base + REST API + MCP server with OAuth 2.1.**
Designed to be deployed on your own VPS and used from any MCP client
(Claude.ai mobile/desktop, Claude Code, custom tools).

- **Storage**: SQLCipher-encrypted SQLite. Your data is opaque on disk.
- **Schema**: one flexible `items` table with 19+ kinds (todo, decision,
  preference, place, person, contract, event, …). Rich markdown bodies.
- **Auth**: bearer tokens (RW + RO) for direct use; full OAuth 2.1 + PKCE
  for Claude.ai connectors.
- **Transports**: REST (`/api/*`) and MCP Streamable HTTP (`/mcp/sse`).
- **Open source, multi-user per deployment** — designed for a family or
  small org. Admin provisions users via CLI; each user's items are
  isolated by `user_id`. Different families each install their own copy.

Docs:
- **[docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)** — connect Claude.ai
- **[docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)** — operators: add users, backups, rotation
- **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — end users: dashboard + Claude
- **[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)** — read before deploying

---

## Architecture at a glance

```
[ Claude.ai mobile/desktop ]                     [ Web dashboard ]
        │                                                │
        │ OAuth 2.1 + JWT bearer                         │ static bearer (RO)
        ▼                                                ▼
        ┌─────────────────────────────────────────────────────┐
        │  Caddy on z-tidus.com:443                            │
        │    /api/*        → mypa-api (uvicorn, FastAPI)       │
        │    /mcp/*        → mypa-mcp (uvicorn, MCP server)    │
        │    /oauth/*      → mypa-api                          │
        │    /.well-known/oauth-authorization-server → mypa-api│
        │    /             → /var/www/mypa-dashboard (SPA)     │
        └─────────────────────────────────────────────────────┘
                              │
                              ▼
                   SQLCipher-encrypted DB at /var/lib/mypa/mypa.db
                   Blobs at /var/lib/mypa/blobs/
```

---

## Quick start (deploy to your own VPS)

### Prereqs

- Ubuntu 24.04 LTS VPS with root SSH access
- Domain pointed at the VPS (A record)
- Ports 80, 443 open in your cloud firewall
- Caddy installed (`apt install caddy`)
- Python 3.12+, SQLCipher (`apt install sqlcipher libsqlcipher-dev`)

### Install

```bash
# 1. Clone the repo
git clone https://github.com/kensterinvest/mypa.git /opt/mypa
cd /opt/mypa

# 2. Create system user + dirs
sudo useradd --system --create-home --home-dir /var/lib/mypa \
  --shell /usr/sbin/nologin mypa
sudo install -d -m 750 -o mypa -g mypa /var/lib/mypa /etc/mypa
sudo install -d -m 755 -o mypa -g mypa /opt/mypa

# 3. Venv + deps
sudo -u mypa python3 -m venv /opt/mypa/.venv
sudo -u mypa /opt/mypa/.venv/bin/pip install \
  "fastapi>=0.110" "uvicorn[standard]>=0.27" "mcp>=1.27" \
  "sqlalchemy>=2" sqlcipher3-binary "pydantic>=2.5" "pydantic-settings>=2" \
  "psutil>=5.9" "httpx>=0.27" "python-telegram-bot>=21" \
  "anthropic>=0.40" "apscheduler>=3.10" "slowapi" "pyjwt[crypto]>=2.8"

# 4. Generate secrets + write env
RW=$(openssl rand -base64 36 | tr -d "\n=+/" | head -c 40)
RO=$(openssl rand -base64 36 | tr -d "\n=+/" | head -c 40)
KEY=$(openssl rand -base64 48 | tr -d "\n=+/" | head -c 64)
JWT=$(openssl rand -base64 48 | tr -d "\n=+/" | head -c 64)
sudo tee /etc/mypa/env > /dev/null <<EOF
PUBLIC_HOST=mypa.example.com
USER_NAME=alice
TZ=Europe/London
LOCALE=en-GB
BEARER_TOKEN_RW=${RW}
BEARER_TOKEN_RO=${RO}
SQLCIPHER_KEY=${KEY}
OAUTH_JWT_SECRET=${JWT}
DB_PATH=/var/lib/mypa/mypa.db
AUDIT_LOG_PATH=/var/log/mypa-mcp.log
EOF
sudo chmod 0600 /etc/mypa/env
sudo chown mypa:mypa /etc/mypa/env
# ⚠️ Save RW, KEY, JWT in your password manager NOW — RW is the OAuth login,
# KEY decrypts the DB, JWT signs all access tokens.

# 5. Initialize DB
cd /opt/mypa && sudo -u mypa bash -c \
  "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
   PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/init_db.py && \
   PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/apply_migrations.py"

# 6. systemd units (see deploy/ in repo)
sudo cp deploy/mypa-api.service deploy/mypa-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mypa-api mypa-mcp

# 7. Caddyfile (add to /etc/caddy/Caddyfile)
sudo tee -a /etc/caddy/Caddyfile > /dev/null <<'EOF'
mypa.example.com {
    encode gzip zstd
    handle /.well-known/oauth-authorization-server { reverse_proxy 127.0.0.1:8022 }
    handle /oauth/* { reverse_proxy 127.0.0.1:8022 }
    handle_path /mcp/* { reverse_proxy 127.0.0.1:8023 }
    handle_path /api/* { reverse_proxy 127.0.0.1:8022 }
    handle {
        root * /var/www/mypa-dashboard
        try_files {path} /index.html
        file_server
    }
}
EOF
sudo systemctl reload caddy
```

Verify:

```bash
curl https://mypa.example.com/api/health
# → {"status":"ok",...}
curl https://mypa.example.com/.well-known/oauth-authorization-server
# → OAuth discovery metadata
```

### Connect Claude.ai

See [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md) for the full walkthrough.
TL;DR: claude.ai → Settings → Connectors → Custom →
URL = `https://mypa.example.com/mcp/sse` → connect → paste your
`BEARER_TOKEN_RW` on the authorize page.

---

## MCP tools

| Tool | Use |
|---|---|
| `pa_describe_schema()` | List all kinds + casual-capture mapping hints |
| `pa_add(kind, title, body, data, tags, due_at, context)` | Save new item |
| `pa_get(item_id)` | Fetch one |
| `pa_list(kind, status, due_before, tag, limit)` | Filtered list |
| `pa_search(q, limit)` | Free-text search across title/body/tags |
| `pa_update(item_id, fields..., allow_history_rewrite)` | Partial update; decision items append-only by convention |
| `pa_complete(item_id)` | Mark done |
| `pa_delete(item_id, confirm=True)` | Hard delete (destructive — require confirm) |
| `pa_undo_last(source)` | Soft-undo most recent save |
| `pa_add_reminder(item_id, fire_at, message)` | Schedule reminder (Telegram delivery pending Phase 2) |

---

## Configuration

Every secret, identity, and integration credential comes from
`/etc/mypa/env`. See `mypa/settings.py` for all fields with defaults.

Key knobs:

| Env var | Purpose | Default |
|---|---|---|
| `PUBLIC_HOST` | Hostname Caddy serves on | `mypa.z-tidus.com` |
| `BEARER_TOKEN_RW` | Full-access static bearer | required |
| `BEARER_TOKEN_RO` | Read-only static bearer | required |
| `SQLCIPHER_KEY` | DB encryption key | required (unless `TEST_NO_ENCRYPTION=true`) |
| `OAUTH_JWT_SECRET` | HS256 signing key for OAuth JWTs | required for OAuth |
| `TELEGRAM_BOT_TOKEN` / `_CHAT_ID` | Outbound reminders (Phase 2) | optional |
| `ANTHROPIC_API_KEY` | Claude vision image extraction (Phase 3) | optional |
| `GOOGLE_CLIENT_ID` / `_SECRET` | Gmail + Calendar (Phase 4-5) | optional |
| `IMPLICIT_LOCATION_CAPTURE` | Capture location from EXIF / browser | `false` (privacy default) |

---

## Roadmap

| Phase | What | Status |
|---|---|---|
| 1 | Core API + SQLCipher DB + MCP (10 tools) | ✅ shipped |
| 1.5 | Nightly snapshot via VACUUM INTO | ✅ shipped |
| OAuth | OAuth 2.1 + PKCE for Claude.ai connectors | ✅ shipped |
| MCP CRUD | pa_delete, pa_update, pa_complete, pa_add_reminder | ✅ shipped |
| Dashboard | Angular SPA (email/password login + items list) | ✅ shipped |
| Multi-tenant | users table + per-user OAuth + isolation tests + admin CLI | ✅ shipped |
| Productization | LICENSE, setup.sh, deploy/ templates, kinds.yaml loader | ✅ shipped |
| 2 | Telegram bot — bidirectional capture + reminders | planned |
| 3 | Image-to-record via Claude vision | planned |
| 4 | Gmail integration | planned |
| 5 | Calendar two-way sync | planned |
| Dashboard polish | Item detail, markdown rendering, calendar view | planned |

---

## Development

```bash
git clone https://github.com/kensterinvest/mypa.git
cd mypa
python -m venv .venv
.venv/bin/pip install -e .[dev]   # or per-package pip install ...
export TEST_NO_ENCRYPTION=true     # Windows: no SQLCipher wheel
pytest -q
```

34 tests covering items CRUD, OAuth flow, DCR validation, decision
append-only enforcement, RW/RO token scoping, and multi-tenant
user isolation.

---

## License

MIT (planned, finalised before v1 release).
