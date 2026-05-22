#!/usr/bin/env bash
# Docker entrypoint for MyPA images.
#
# Usage (set by docker-compose):
#   mypa-entrypoint api    → runs mypa.main:app on :8022
#   mypa-entrypoint mcp    → runs mypa.mcp_server:app on :8023
#
# Behaviour:
#   - applies pending DB migrations (only the api container does this)
#   - creates the admin user from MYPA_ADMIN_EMAIL + MYPA_ADMIN_PASSWORD
#     if no admin exists yet (idempotent)
#   - starts uvicorn

set -euo pipefail

ROLE="${1:-api}"

# Fail-fast on the env vars uvicorn / settings.py will need
: "${BEARER_TOKEN_RW:?BEARER_TOKEN_RW env var required}"
: "${BEARER_TOKEN_RO:?BEARER_TOKEN_RO env var required}"
: "${OAUTH_JWT_SECRET:?OAUTH_JWT_SECRET env var required}"
: "${PUBLIC_HOST:?PUBLIC_HOST env var required}"

# Reject .env.example placeholder values — a lazy operator who runs
# `docker compose up -d` without editing .env would otherwise boot a
# stack with `REPLACE-WITH-RANDOM-...` as the bearer token. Loud fail.
for var in BEARER_TOKEN_RW BEARER_TOKEN_RO OAUTH_JWT_SECRET SQLCIPHER_KEY \
           NTFY_ADMIN_PASSWORD NTFY_PUBLISH_PASSWORD MYPA_ADMIN_PASSWORD; do
    eval "v=\${$var:-}"
    case "$v" in
        REPLACE-WITH-*|change-this-*)
            echo "[mypa] FATAL: $var is still set to the .env.example placeholder."  >&2
            echo "[mypa]        Generate a real value and edit your .env file."       >&2
            echo "[mypa]        Suggestion: openssl rand -base64 48 | tr -d '\n=+/' | head -c 64"  >&2
            exit 1
            ;;
    esac
done

# Caddy-specific: surface a clear warning if LETSENCRYPT_EMAIL is
# unset or still example.com (Let's Encrypt has rate-limited that
# address; you'd hit a cryptic Caddy log error otherwise).
if [[ "${LETSENCRYPT_EMAIL:-}" == "" || "${LETSENCRYPT_EMAIL:-}" == *example.com ]]; then
    echo "[mypa] WARN: LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL:-(empty)} — Caddy may not be able to" >&2
    echo "[mypa]       get a TLS certificate. Set it to your real email in .env."                 >&2
fi

# Defaults — match bare-metal install conventions
export DB_PATH="${DB_PATH:-/var/lib/mypa/mypa.db}"
export BLOB_DIR="${BLOB_DIR:-/var/lib/mypa/blobs}"
export AUDIT_LOG_PATH="${AUDIT_LOG_PATH:-/var/log/mypa/mypa-mcp.log}"
export NOTIFY_SCHEDULER_ENABLED="${NOTIFY_SCHEDULER_ENABLED:-true}"

# In dev (no SQLCipher needed) operators set TEST_NO_ENCRYPTION=true
if [[ "${TEST_NO_ENCRYPTION:-false}" != "true" ]]; then
    : "${SQLCIPHER_KEY:?SQLCIPHER_KEY env var required (or set TEST_NO_ENCRYPTION=true for dev)}"
fi

# Only the api container runs migrations + admin bootstrap. mcp shares
# the same DB file via the named volume so by the time it starts the
# schema is ready.
if [[ "$ROLE" == "api" ]]; then
    echo "[mypa] applying migrations…"
    PYTHONPATH=/opt/mypa python /opt/mypa/scripts/apply_migrations.py

    if [[ -n "${MYPA_ADMIN_EMAIL:-}" && -n "${MYPA_ADMIN_PASSWORD:-}" ]]; then
        echo "[mypa] ensuring admin user exists…"
        PYTHONPATH=/opt/mypa python - <<PY
import os, sys
from mypa.db import session_factory
from mypa import users as ul

email = os.environ["MYPA_ADMIN_EMAIL"]
pw    = os.environ["MYPA_ADMIN_PASSWORD"]
name  = os.environ.get("MYPA_ADMIN_NAME", email.split("@")[0])

S = session_factory()
with S() as db:
    existing = ul.get_admin_user(db)
    if existing is not None:
        print(f"[mypa] admin already exists (id={existing.id}, email={existing.email}); skipping")
        sys.exit(0)
    try:
        u = ul.create_user(db, email, pw, name=name, is_admin=True, tz=os.environ.get("TZ", "Etc/UTC"))
        print(f"[mypa] created admin user {u.email} (id={u.id})")
    except ValueError as e:
        print(f"[mypa] admin create error: {e}")
PY
    fi
fi

# Launch the right uvicorn target
case "$ROLE" in
    api)
        echo "[mypa] starting mypa-api on :8022"
        exec uvicorn mypa.main:app \
            --host 0.0.0.0 --port 8022 \
            --proxy-headers --forwarded-allow-ips='*'
        ;;
    mcp)
        echo "[mypa] starting mypa-mcp on :8023"
        # mcp doesn't need migrations — api ran them — but give the api
        # a head start by sleeping briefly on first cold-boot.
        sleep 2
        exec uvicorn mypa.mcp_server:app \
            --host 0.0.0.0 --port 8023 \
            --proxy-headers --forwarded-allow-ips='*'
        ;;
    *)
        echo "[mypa] unknown role: $ROLE (expected: api | mcp)" >&2
        exit 1
        ;;
esac
