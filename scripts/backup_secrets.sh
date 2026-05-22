#!/usr/bin/env bash
# Operator script — create a fresh encrypted bundle of the current
# /etc/mypa/env (which now contains OAUTH_JWT_SECRET, NTFY passwords,
# SQLCIPHER_KEY, the bearer tokens, etc.).
#
# Why: the existing /srv/backups/secrets/secrets.tar.gz.enc on prod
# pre-dates the multi-tenant + ntfy work. If you ever lose /etc/mypa/env,
# you'd lose more than the encryption key — you'd lose the JWT signing
# secret + ntfy creds too. Refresh the bundle periodically.
#
# Safe to re-run. Output filename includes today's date so it sits
# alongside any older bundles (don't delete the old one until you've
# verified the new one is recoverable).
#
# Usage:
#   sudo bash /opt/mypa/scripts/backup_secrets.sh
#
# Output:
#   /srv/backups/secrets/secrets-YYYY-MM-DD.tar.gz.enc
#   + prints the new openssl password ONCE. SAVE IT in your password
#   manager. Lose it and the bundle is unrecoverable.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (or with sudo)" >&2
    exit 1
fi

OUT_DIR=/srv/backups/secrets
mkdir -p "$OUT_DIR"
chown deploy:deploy "$OUT_DIR" 2>/dev/null || true

DATE=$(date -u +%Y-%m-%d)
OUT_FILE="$OUT_DIR/secrets-${DATE}.tar.gz.enc"
TMP=$(mktemp -d)

# Files to bundle. /etc/mypa/env is the critical one; we also include
# /etc/sudoers.d/mypa-ntfy as a reminder of the runtime ACL.
cp /etc/mypa/env "$TMP/mypa.env"
if [[ -f /etc/sudoers.d/mypa-ntfy ]]; then
    cp /etc/sudoers.d/mypa-ntfy "$TMP/sudoers-mypa-ntfy"
fi

# Generate a strong bundle password
BUNDLE_PW=$(openssl rand -base64 30 | tr -d "\n=+/" | head -c 32)

# Create tarball + encrypt with AES-256
cd "$TMP"
tar -czf bundle.tar.gz mypa.env sudoers-mypa-ntfy 2>/dev/null || tar -czf bundle.tar.gz mypa.env
openssl enc -aes-256-cbc -salt -pbkdf2 -iter 250000 \
    -in bundle.tar.gz -out "$OUT_FILE" -pass "pass:$BUNDLE_PW"
chmod 0600 "$OUT_FILE"
chown deploy:deploy "$OUT_FILE" 2>/dev/null || true

cd /
rm -rf "$TMP"

echo
echo "================================================================"
echo "  Secrets bundle created."
echo "================================================================"
echo "  File:     $OUT_FILE"
echo "  Password: $BUNDLE_PW"
echo
echo "  SAVE THE PASSWORD ABOVE IN YOUR PASSWORD MANAGER NOW."
echo "  Without it the bundle is unrecoverable."
echo
echo "  To verify the bundle decrypts later:"
echo "    openssl enc -d -aes-256-cbc -pbkdf2 -iter 250000 \\"
echo "      -in $OUT_FILE -out /tmp/bundle.tar.gz -pass 'pass:<the-password>'"
echo "    tar -tzf /tmp/bundle.tar.gz   # should list mypa.env"
echo
echo "  Old bundles (if any) remain at $OUT_DIR/ — delete once you've"
echo "  verified this new one. Use 'ls -la' to find them."
echo "================================================================"
