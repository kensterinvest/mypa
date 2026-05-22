#!/bin/sh
# Initialise the ntfy auth DB on first boot — creates admin user +
# mypa-publisher (write access to u-*). Idempotent: skips if users
# already exist.
#
# Run once by the ntfy container's entrypoint override before ntfy
# starts. Requires the ntfy binary in PATH.

set -e

: "${NTFY_ADMIN_USER:?NTFY_ADMIN_USER required}"
: "${NTFY_ADMIN_PASSWORD:?NTFY_ADMIN_PASSWORD required}"
: "${NTFY_PUBLISH_USER:?NTFY_PUBLISH_USER required}"
: "${NTFY_PUBLISH_PASSWORD:?NTFY_PUBLISH_PASSWORD required}"

# Make sure the auth.db directory exists and is writable
mkdir -p /var/lib/ntfy
chown ntfy:ntfy /var/lib/ntfy 2>/dev/null || true

# Has admin been created already?
if ntfy user list 2>/dev/null | grep -q "^user $NTFY_ADMIN_USER "; then
    echo "[ntfy-init] admin user already present; skipping bootstrap"
else
    echo "[ntfy-init] creating admin user $NTFY_ADMIN_USER"
    NTFY_PASSWORD="$NTFY_ADMIN_PASSWORD" ntfy user add --role=admin "$NTFY_ADMIN_USER"
fi

if ntfy user list 2>/dev/null | grep -q "^user $NTFY_PUBLISH_USER "; then
    echo "[ntfy-init] publisher already present; skipping"
else
    echo "[ntfy-init] creating publisher $NTFY_PUBLISH_USER"
    NTFY_PASSWORD="$NTFY_PUBLISH_PASSWORD" ntfy user add "$NTFY_PUBLISH_USER"
    ntfy access "$NTFY_PUBLISH_USER" "u-*" write
fi

echo "[ntfy-init] ready — handing off to ntfy serve"
exec ntfy serve
