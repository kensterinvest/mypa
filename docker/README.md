# MyPA via Docker

Run the entire MyPA stack — API, MCP server, ntfy, Caddy with TLS — as
a single `docker compose` deployment. Suitable for:

- **NAS devices** with Docker / Container Manager (Synology, QNAP,
  Unraid, TrueNAS Scale)
- **Home servers** — Raspberry Pi 4/5, mini-PCs, refurbished SFFs
- **Cloud VPS** if you prefer Compose over the bare-metal `setup.sh`

If you'd rather install directly on Ubuntu without Docker, use
[`setup.sh`](../setup.sh) instead.

## Prerequisites

- Docker engine ≥ 24 and Docker Compose v2 (`docker compose ...`)
- Ports 80 and 443 reachable from the public internet (for Let's Encrypt)
- Two DNS A records pointing at this host's public IP:
  - `mypa.<your-domain>` — main MyPA URL
  - `ntfy.<your-domain>` — push notifications (optional but
    enabled by default; see "Disable ntfy" below to skip)

**Hardware**: 1 vCPU / 1 GB RAM / 10 GB disk is enough for a family
of 5. Comfortable: 2 vCPU / 2 GB RAM / 25 GB.

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/kensterinvest/mypa.git
cd mypa/docker

# 2. Configure
cp .env.example .env
# edit .env — at minimum set:
#   PUBLIC_HOST, NTFY_HOST, LETSENCRYPT_EMAIL
#   MYPA_ADMIN_EMAIL, MYPA_ADMIN_PASSWORD
#   the five REPLACE-WITH-RANDOM-* secrets
#
# Generate each random secret with:
#   openssl rand -base64 48 | tr -d "\n=+/" | head -c 64

# 3. Start the stack
docker compose up -d

# 4. Watch the logs while Caddy gets a cert (~30s)
docker compose logs -f caddy
# When you see "certificate obtained successfully" for both hostnames,
# you're live. Ctrl-C to detach.

# 5. Sanity check
curl https://${PUBLIC_HOST}/api/health
# → {"status":"ok",...}
```

## NAS specifics

### Synology

1. Install **Container Manager** (DSM 7.2+) from Package Center.
2. SSH into the NAS and `git clone https://github.com/kensterinvest/mypa.git` into a shared folder.
3. `cd mypa/docker && cp .env.example .env`, edit `.env` via the
   Synology File Station or SSH.
4. In Container Manager → Project → Create. Path: the `docker/` folder.
   Source: "Use existing docker-compose.yml". Build + start.

**Synology reverse proxy conflict**: if you're already using DSM's
reverse proxy on 443, either disable it on the MyPA host names or
remove the `ports` mapping for caddy in `docker-compose.yml` and let
the existing reverse proxy front MyPA (route 443 → port 80 on the
caddy container's internal IP).

### Unraid

The Compose stack is "Community Applications → Docker Compose Manager"
compatible. Drop the repo, set the project to the `docker/` folder,
edit `.env` in the Unraid UI, start. Caddy + ntfy + the two MyPA
containers will appear in the Docker tab.

### QNAP

QTS 5.0+ Container Station with Compose v2 support. Same flow as
Synology.

## What gets persisted

Named Docker volumes — survive container rebuilds:

| Volume | Holds |
|---|---|
| `mypa-data` | `/var/lib/mypa/mypa.db` (the encrypted DB) + blobs |
| `mypa-logs` | Audit log + uvicorn logs |
| `ntfy-cache` | ntfy message cache (12h retention) |
| `ntfy-data` | ntfy auth DB (users + ACL) |
| `caddy-data` | Let's Encrypt certificates and Caddy state |
| `caddy-config` | Caddy operational config |

**Backup**: snapshot the `mypa-data` and `caddy-data` volumes. Losing
`mypa-data` = losing your archive. Losing `caddy-data` = Caddy
re-fetches certificates (no data loss, brief downtime).

## Updating

```bash
cd mypa
git pull
cd docker
docker compose up -d --build
```

Migrations are applied automatically on next API container boot.

## Disable ntfy (no push notifications)

If you don't want notifications, edit `docker-compose.yml`:

1. Remove (or comment out) the `ntfy` service block
2. Remove `ntfy.example.com` from the Caddyfile
3. In `.env`, set `NTFY_USER_MGMT_ENABLED=false` and leave `NTFY_HOST=`
   blank
4. `docker compose up -d --force-recreate caddy mypa-api`

MyPA itself works fine without ntfy — see
[`docs/NOTIFICATIONS.md`](../docs/NOTIFICATIONS.md) for the rationale.

## Connect Claude.ai

After the stack is running, follow
[`docs/OAUTH_SETUP.md`](../docs/OAUTH_SETUP.md) — claude.ai → Settings
→ Connectors → + Add custom → URL `https://<your-PUBLIC_HOST>/mcp/sse`
→ sign in with the admin email + password from `.env`.

## Troubleshooting

```bash
# Watch all logs
docker compose logs -f

# Restart a specific service
docker compose restart mypa-api

# Re-bootstrap admin user (e.g. if password forgotten — delete user first)
docker compose exec mypa-api bash -c "PYTHONPATH=/opt/mypa python scripts/change_password.py you@example.com"

# Shell into mypa-api
docker compose exec mypa-api bash

# Manually trigger migration apply
docker compose exec mypa-api bash -c "PYTHONPATH=/opt/mypa python scripts/apply_migrations.py"
```

## Architecture notes

The compose stack mirrors the bare-metal install:

- All MyPA containers run as the unprivileged `mypa` user (uid 100ish)
- API and MCP share the same image (single Dockerfile) but run with
  different `command:` — saves rebuild time
- `caddy` image is a multi-stage build that pulls + builds the
  dashboard SPA from upstream at image-build time (override
  `DASHBOARD_REF` to pin a specific commit)
- Inter-service traffic stays on the `mypa-net` bridge network;
  only Caddy is exposed to the host
- ntfy has auth enabled by default; the init script provisions the
  admin + publisher users on first boot (idempotent on subsequent boots)
