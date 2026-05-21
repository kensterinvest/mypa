#!/usr/bin/env bash
# MyPA installer — interactive setup for a fresh VPS deployment.
#
# Usage:
#   sudo bash setup.sh
#
# Prerequisites (you handle these once before running setup.sh):
#   - Ubuntu 22.04 / 24.04 LTS VPS
#   - Root SSH access
#   - A domain pointing at the VPS (DNS A record)
#   - Ports 80, 443 open at the OS firewall AND the cloud-provider firewall
#   - Run on the VPS as root (`sudo -i` first or prefix with sudo)
#
# What this script does:
#   - Installs APT packages (Python venv, SQLCipher, Caddy)
#   - Creates the `mypa` system user + /opt/mypa /etc/mypa /var/lib/mypa
#   - Sets up Python venv + installs Python deps
#   - Prompts for PUBLIC_HOST + USER_NAME + TZ + LOCALE
#   - Generates random secrets, writes /etc/mypa/env (mode 0600)
#   - Initialises encrypted DB + applies migrations
#   - Installs systemd units + Caddy snippet + logrotate
#   - Starts services, prints credentials ONCE
#
# Idempotent: safe to re-run; existing values in /etc/mypa/env are preserved
# (it only prompts for missing ones).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR=/opt/mypa
ENV_FILE=/etc/mypa/env

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must run as root. Try:  sudo bash setup.sh"
    exit 1
fi

color() { printf "\033[1;%sm%s\033[0m\n" "$1" "$2"; }
say()   { color 36 "==> $1"; }
warn()  { color 33 "WARN: $1"; }
err()   { color 31 "ERR:  $1" >&2; }

# ---------- 1. APT packages ----------
say "Installing OS packages (apt)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3-venv python3-pip python3-dev \
    sqlcipher libsqlcipher-dev libssl-dev libffi-dev \
    build-essential curl ca-certificates

# Caddy from official repo if not present
if ! command -v caddy >/dev/null 2>&1; then
    say "Installing Caddy from official APT repo…"
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
else
    say "Caddy already installed (skipping)."
fi

# ---------- 2. System user + directories ----------
say "Creating mypa system user + directories…"
if ! id mypa >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/mypa \
        --shell /usr/sbin/nologin mypa
fi
install -d -m 755 -o mypa -g mypa "$TARGET_DIR"
install -d -m 750 -o mypa -g mypa /var/lib/mypa /var/lib/mypa/blobs /etc/mypa
touch /var/log/mypa-api.log /var/log/mypa-mcp.log /var/log/mypa-bot.log
chown mypa:mypa /var/log/mypa-*.log
chmod 640 /var/log/mypa-*.log

# ---------- 3. Sync repo into /opt/mypa ----------
say "Syncing source into $TARGET_DIR…"
if [[ "$REPO_DIR" != "$TARGET_DIR" ]]; then
    # rsync if available, otherwise tar
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude='.venv' --exclude='__pycache__' \
              --exclude='.git' --exclude='*.pyc' --exclude='.pytest_cache' \
              "$REPO_DIR"/ "$TARGET_DIR"/
    else
        tar --exclude=.venv --exclude=__pycache__ --exclude=.git \
            --exclude='*.pyc' --exclude=.pytest_cache \
            -czf /tmp/mypa-setup.tar.gz -C "$REPO_DIR" .
        rm -rf "$TARGET_DIR"/*
        tar -xzf /tmp/mypa-setup.tar.gz -C "$TARGET_DIR"
        rm /tmp/mypa-setup.tar.gz
    fi
fi
chown -R mypa:mypa "$TARGET_DIR"

# ---------- 4. Python venv + deps ----------
say "Creating venv + installing Python deps (may take ~30s)…"
sudo -u mypa python3 -m venv "$TARGET_DIR/.venv"
sudo -u mypa "$TARGET_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u mypa "$TARGET_DIR/.venv/bin/pip" install --quiet \
    "fastapi>=0.110" "uvicorn[standard]>=0.27" "mcp>=1.27" \
    "sqlalchemy>=2" sqlcipher3-binary "pydantic>=2.5" "pydantic-settings>=2" \
    "psutil>=5.9" "httpx>=0.27" "python-telegram-bot>=21" \
    "anthropic>=0.40" "apscheduler>=3.10" slowapi "pyjwt[crypto]>=2.8"

# ---------- 5. /etc/mypa/env ----------
say "Configuring /etc/mypa/env…"

# Load existing env if present, otherwise start fresh.
declare -A E
if [[ -f "$ENV_FILE" ]]; then
    while IFS='=' read -r k v; do
        [[ -z "$k" || "$k" =~ ^# ]] && continue
        E["$k"]="$v"
    done < "$ENV_FILE"
fi

ask() {
    local key="$1" prompt="$2" default="${3:-}" current="${E[$1]:-}"
    if [[ -n "$current" ]]; then
        echo "  ${key}: keeping existing value"
        return
    fi
    if [[ -n "$default" ]]; then
        read -r -p "  $prompt [$default]: " value
        value="${value:-$default}"
    else
        read -r -p "  $prompt: " value
    fi
    E["$key"]="$value"
}

gen_secret() {
    openssl rand -base64 48 | tr -d "\n=+/" | head -c "${1:-40}"
}

ask PUBLIC_HOST "Public hostname (e.g. mypa.example.com)"
ask USER_NAME   "Your name (used for greetings)" "$(whoami)"
ask TZ          "Timezone" "Etc/UTC"
ask LOCALE      "Locale" "en-US"

# Secrets — auto-generate if missing
for key in BEARER_TOKEN_RW BEARER_TOKEN_RO; do
    if [[ -z "${E[$key]:-}" ]]; then
        E[$key]=$(gen_secret 40)
        echo "  $key: generated (will be printed below)"
    fi
done
for key in SQLCIPHER_KEY OAUTH_JWT_SECRET; do
    if [[ -z "${E[$key]:-}" ]]; then
        E[$key]=$(gen_secret 64)
        echo "  $key: generated (will be printed below)"
    fi
done

# Optional integrations — leave blank if not provided.
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID ANTHROPIC_API_KEY \
           GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET OPENAI_API_KEY; do
    [[ -z "${E[$key]:-}" ]] && E[$key]=""
done

# Behavior flags
[[ -z "${E[IMPLICIT_LOCATION_CAPTURE]:-}" ]] && E[IMPLICIT_LOCATION_CAPTURE]="false"
[[ -z "${E[IMAGE_EXTRACTION_ENABLED]:-}" ]]  && E[IMAGE_EXTRACTION_ENABLED]="false"
[[ -z "${E[OUTCOME_NUDGE_ENABLED]:-}" ]]     && E[OUTCOME_NUDGE_ENABLED]="false"
[[ -z "${E[DB_PATH]:-}" ]]                   && E[DB_PATH]="/var/lib/mypa/mypa.db"
[[ -z "${E[AUDIT_LOG_PATH]:-}" ]]            && E[AUDIT_LOG_PATH]="/var/log/mypa-mcp.log"
[[ -z "${E[BLOB_DIR]:-}" ]]                  && E[BLOB_DIR]="/var/lib/mypa/blobs"

# Write file
{
    echo "# MyPA configuration — generated $(date -u +%FT%TZ) by setup.sh"
    echo "# Mode 0600. Owned by mypa user. Contains secrets — do not commit."
    for key in PUBLIC_HOST USER_NAME TZ LOCALE \
               BEARER_TOKEN_RW BEARER_TOKEN_RO \
               SQLCIPHER_KEY OAUTH_JWT_SECRET \
               DB_PATH AUDIT_LOG_PATH BLOB_DIR \
               TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID \
               ANTHROPIC_API_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET \
               OPENAI_API_KEY \
               IMPLICIT_LOCATION_CAPTURE IMAGE_EXTRACTION_ENABLED \
               OUTCOME_NUDGE_ENABLED; do
        echo "$key=${E[$key]:-}"
    done
} > "$ENV_FILE"
chmod 0600 "$ENV_FILE"
chown mypa:mypa "$ENV_FILE"

# ---------- 6. Initialize DB ----------
say "Initialising encrypted DB + applying migrations…"
sudo -u mypa bash -c "set -a; source $ENV_FILE; set +a; cd $TARGET_DIR; \
    PYTHONPATH=$TARGET_DIR $TARGET_DIR/.venv/bin/python scripts/init_db.py && \
    PYTHONPATH=$TARGET_DIR $TARGET_DIR/.venv/bin/python scripts/apply_migrations.py"

# ---------- 7. systemd units ----------
say "Installing systemd units…"
cp "$TARGET_DIR/deploy/mypa-api.service" /etc/systemd/system/
cp "$TARGET_DIR/deploy/mypa-mcp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable mypa-api mypa-mcp >/dev/null

# ---------- 8. Caddy snippet ----------
say "Configuring Caddy site block for ${E[PUBLIC_HOST]}…"
SNIPPET=$(sed "s|MYPA_HOST|${E[PUBLIC_HOST]}|" "$TARGET_DIR/deploy/Caddyfile.snippet")
if ! grep -q "^${E[PUBLIC_HOST]} {" /etc/caddy/Caddyfile 2>/dev/null; then
    echo "" >> /etc/caddy/Caddyfile
    echo "$SNIPPET" >> /etc/caddy/Caddyfile
    say "Added MyPA block to /etc/caddy/Caddyfile"
else
    warn "/etc/caddy/Caddyfile already contains a block for ${E[PUBLIC_HOST]} — skipping"
fi
caddy validate --config /etc/caddy/Caddyfile >/dev/null
systemctl reload caddy

# ---------- 9. logrotate ----------
cp "$TARGET_DIR/deploy/logrotate.conf" /etc/logrotate.d/mypa
chmod 644 /etc/logrotate.d/mypa

# ---------- 10. Start services ----------
say "Starting services…"
systemctl restart mypa-api mypa-mcp
sleep 3

# ---------- 11. Verify ----------
say "Verifying…"
if curl -fsS "http://127.0.0.1:8022/health" >/dev/null; then
    color 32 "  ✓ mypa-api responding on :8022"
else
    err "mypa-api not responding"; exit 1
fi
if curl -fsS "http://127.0.0.1:8023/health" >/dev/null; then
    color 32 "  ✓ mypa-mcp responding on :8023"
else
    err "mypa-mcp not responding"; exit 1
fi
if curl -fsS "https://${E[PUBLIC_HOST]}/api/health" >/dev/null; then
    color 32 "  ✓ public HTTPS via Caddy reachable"
else
    warn "Public HTTPS not yet reachable — DNS may still be propagating or"
    warn "Let's Encrypt cert is being issued. Check 'journalctl -u caddy' in a minute."
fi

# ---------- 12. Print credentials ONCE ----------
echo
color 32 "================================================================"
color 32 "  MyPA setup complete. SAVE THESE NOW IN YOUR PASSWORD MANAGER."
color 32 "================================================================"
echo "  Public URL:        https://${E[PUBLIC_HOST]}/"
echo "  REST API:          https://${E[PUBLIC_HOST]}/api/"
echo "  MCP endpoint:      https://${E[PUBLIC_HOST]}/mcp/sse"
echo "  OAuth discovery:   https://${E[PUBLIC_HOST]}/.well-known/oauth-authorization-server"
echo
echo "  BEARER_TOKEN_RW (full access — also used as OAuth login password):"
echo "    ${E[BEARER_TOKEN_RW]}"
echo "  BEARER_TOKEN_RO (read-only — paste in dashboard):"
echo "    ${E[BEARER_TOKEN_RO]}"
echo "  SQLCIPHER_KEY (DB encryption — LOSE THIS = lose all data):"
echo "    ${E[SQLCIPHER_KEY]}"
echo "  OAUTH_JWT_SECRET (signs all OAuth JWTs):"
echo "    ${E[OAUTH_JWT_SECRET]}"
echo
color 32 "================================================================"
echo "  Next: see docs/OAUTH_SETUP.md to register Claude.ai as a connector."
echo "================================================================"
