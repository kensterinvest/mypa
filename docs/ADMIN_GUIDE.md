# MyPA Admin Guide

You are the **operator** of a MyPA deployment — the person who ran
`setup.sh` (or the manual install) on the VPS and owns
`/etc/mypa/env`. This guide covers the day-2 tasks: managing users,
backups, secret rotation, and recovery.

For first-time install, see the [README](../README.md) "Quick start".
For end-user onboarding, send them [USER_GUIDE.md](USER_GUIDE.md).

---

## Server requirements

**Minimum (one user, no photo attachments):**

| Resource | Value |
|---|---|
| CPU | 1 vCPU |
| RAM | 1 GB (with at least 1 GB swap recommended) |
| Disk | 10 GB SSD |
| OS | Ubuntu 22.04 LTS or 24.04 LTS |
| Network | Static IPv4, ports 22 / 80 / 443 open in cloud firewall AND OS UFW |
| Domain | Two DNS A records: `mypa.<your-domain>` and `ntfy.<your-domain>` (the second is only needed if you want push notifications) |

**Comfortable (family of 5, attachments, growing archive):**

| Resource | Value |
|---|---|
| CPU | 2 vCPU |
| RAM | 2 GB |
| Disk | 25 GB SSD |

**Tested providers & instance sizes:**

| Provider | Smallest instance that works | Approx. monthly cost |
|---|---|---|
| Hetzner Cloud | CX22 (2 vCPU, 4 GB) | €4.51 |
| IONOS | Linux S | £8 |
| DigitalOcean | Basic Droplet (1 vCPU, 1 GB) | $6 |
| Linode/Akamai | Nanode 1 GB | $5 |
| AWS Lightsail | $5/mo plan (512 MB → tight, recommend $7 for 1 GB) | $5-7 |

Other Linux distros work but `setup.sh` assumes `apt`. If you're on
RHEL/Fedora/Arch you'll be doing the package installs manually.

**Disk growth pattern:**
- Database file (`/var/lib/mypa/mypa.db`): grows slowly — typically &lt; 100 MB even after years for text-only use
- Attachments (`/var/lib/mypa/blobs/`): each image ~100 KB-2 MB; budget accordingly
- Snapshots (`/srv/backups/mypa-snapshots/`): 30 days × DB size + blobs

**No external dependencies after install** — no managed database, no
S3, no Anthropic API calls from MyPA itself (you'd hit Anthropic from
Claude.ai; MyPA never calls out).

---

---

## User management

Every command below is run on the VPS as the `mypa` system user.
The wrapper pattern `sudo -u mypa bash -c "set -a; source /etc/mypa/env; ..."` is required because the scripts read encryption + DB-path config from `/etc/mypa/env`.

### Create a user

```bash
sudo -u mypa bash -c \
  "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
   PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/add_user.py \
   alice@example.com --name 'Alice'"
```

Prints the user's id, email, and a **one-time auto-generated password**.
Share via your preferred secure channel (1Password share link, encrypted
DM, in-person). The password is **not stored in plain text anywhere** —
only its scrypt hash. If lost, use the change-password procedure below.

`--admin` flag promotes the new user (can later be used for an admin
UI; currently grants no extra runtime privilege beyond being the legacy
`sub="user"` JWT target).

### Change a user's password

Operator override (no current password needed — for recovery):

```bash
sudo -u mypa bash -c \
  "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
   PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/change_password.py \
   alice@example.com"
```

Prompts for the new password twice. **Existing JWTs continue to work
until they expire (1h max)** — to force immediate invalidation, rotate
`OAUTH_JWT_SECRET` (see "JWT secret rotation" below).

A user can also change their own password (with current-password
check) by SSHing to the box and running with `--self`, but in practice
they'll ask you — there's no in-product UI yet.

### Disable a user

```bash
sudo -u mypa sqlcipher /var/lib/mypa/mypa.db \
  "PRAGMA key='$SQLCIPHER_KEY'; \
   UPDATE users SET disabled_at = datetime('now') WHERE email = 'alice@example.com';"
```

`authenticate()` rejects logins after this. **Existing JWTs and
refresh tokens keep working until expiry** — same as password change.
Rotate `OAUTH_JWT_SECRET` if you need immediate revocation.

### List users

```bash
sudo -u mypa sqlcipher /var/lib/mypa/mypa.db \
  "PRAGMA key='$SQLCIPHER_KEY'; SELECT id, email, name, is_admin, disabled_at FROM users;"
```

---

## Backups

Nightly snapshots are configured at install time (cron job runs at
03:00 UTC). Each snapshot uses `VACUUM INTO` to write an encrypted,
consistent copy of `/var/lib/mypa/mypa.db` to
`/srv/backups/mypa-snapshots/YYYY-MM-DD/`.

### Verify the cron is running

```bash
ls -lt /srv/backups/mypa-snapshots/ | head -5
# Today's date should appear at the top.
```

### Manual snapshot

```bash
sudo /usr/local/bin/mypa-snapshot.sh
```

### Restore from a snapshot

```bash
sudo systemctl stop mypa-api mypa-mcp
sudo -u mypa cp /srv/backups/mypa-snapshots/2026-05-20/mypa.db \
                /var/lib/mypa/mypa.db
sudo systemctl start mypa-api mypa-mcp
curl https://mypa.example.com/api/health  # should return 200
```

The snapshot is encrypted with the same `SQLCIPHER_KEY` as the live DB
— if you lose that key, the backup is unrecoverable. Keep it in your
password manager.

### Off-site backup (recommended)

Pull snapshots to a second machine periodically:

```bash
rsync -avz vps:/srv/backups/mypa-snapshots/ ~/mypa-backups/
```

Encrypt at rest on the second machine too (Borg, restic, age, or
filesystem-level LUKS).

---

## Secret rotation

`/etc/mypa/env` holds three load-bearing secrets. The rotation
procedures differ by blast radius.

### `BEARER_TOKEN_RW` (low impact)

Used by:
- Direct API clients (curl, custom scripts) holding the static bearer
- The OAuth /authorize page's legacy admin login (blank email + bearer
  as password)

Rotation does NOT log out existing Claude.ai sessions (they hold JWTs,
which are signed by `OAUTH_JWT_SECRET` and don't reference the bearer).

```bash
NEW=$(openssl rand -base64 36 | tr -d "\n=+/" | head -c 40)
sudo sed -i "s|^BEARER_TOKEN_RW=.*|BEARER_TOKEN_RW=$NEW|" /etc/mypa/env
sudo systemctl restart mypa-api mypa-mcp
echo "New token: $NEW"  # save to password manager + update scripts
```

### `OAUTH_JWT_SECRET` (high impact — invalidates all sessions)

Used to sign every JWT (Claude.ai connector tokens + dashboard tokens).
Rotation **forces every connected device to re-authorize**.

Use this when:
- You suspect a JWT has been leaked
- You disabled or removed a user and need to invalidate their existing
  tokens immediately
- Per your own scheduled rotation policy

```bash
NEW=$(openssl rand -base64 48 | tr -d "\n=+/" | head -c 64)
sudo sed -i "s|^OAUTH_JWT_SECRET=.*|OAUTH_JWT_SECRET=$NEW|" /etc/mypa/env
sudo systemctl restart mypa-api mypa-mcp
```

Tell each user to re-connect their Claude.ai connector and re-login
to the dashboard.

### `SQLCIPHER_KEY` (catastrophic — full re-encryption required)

Don't rotate unless the key has been disclosed. To rotate:

```bash
# Decrypt-then-re-encrypt via sqlcipher CLI
sudo systemctl stop mypa-api mypa-mcp
sudo -u mypa sqlcipher /var/lib/mypa/mypa.db <<EOF
PRAGMA key='$OLD_KEY';
ATTACH DATABASE '/tmp/new.db' AS newdb KEY '$NEW_KEY';
SELECT sqlcipher_export('newdb');
DETACH DATABASE newdb;
EOF
sudo -u mypa mv /tmp/new.db /var/lib/mypa/mypa.db
sudo sed -i "s|^SQLCIPHER_KEY=.*|SQLCIPHER_KEY=$NEW_KEY|" /etc/mypa/env
sudo systemctl start mypa-api mypa-mcp
```

All existing snapshots remain encrypted with the OLD key — keep it
labeled in your password manager (e.g. `mypa SQLCIPHER_KEY (pre-2026-05-21)`)
until you no longer need to restore from those snapshots.

---

## Adding custom item kinds

Default kinds ship in `mypa/service.py` (`DEFAULT_KINDS` map). To add
your own without editing source:

```bash
sudo install -d -m 750 -o mypa /etc/mypa
sudo -u mypa tee /etc/mypa/kinds.yaml > /dev/null <<'YAML'
recipe:
  description: "A cooked dish you want to remember"
  data_example:
    cuisine: "italian"
    prep_min: 30
    rating: 5
travel_log:
  description: "Notes from a trip"
  data_example:
    country: "JP"
    dates: "2026-03-01..2026-03-14"
YAML
sudo systemctl restart mypa-api
```

`pa_describe_schema()` will now include `recipe` and `travel_log` in
its kind list, and any Claude/MCP client that has called
`pa_describe_schema` in its session will know to use them.

The custom config is **merged** with defaults; you can override a
default kind by giving it the same name in `kinds.yaml`.

---

## Monitoring

Logs:

```bash
sudo journalctl -u mypa-api -f       # API requests
sudo journalctl -u mypa-mcp -f       # MCP tool calls (audit)
sudo tail -f /var/log/mypa-mcp.log   # structured audit log
```

Health checks:

```bash
curl https://mypa.example.com/api/health         # process up
curl https://mypa.example.com/api/health/ready   # DB reachable
```

Both should return HTTP 200 with `{"status":"ok"|"ready",...}`.

---

## Disaster scenarios

| Scenario | Recovery |
|---|---|
| VPS dies / wiped | New VPS → restore `/etc/mypa/env` from password manager → restore latest `/srv/backups/mypa-snapshots/*/mypa.db` to `/var/lib/mypa/mypa.db` → install + start services |
| `/etc/mypa/env` lost (key gone) | DB unrecoverable. This is why you save `SQLCIPHER_KEY` and `OAUTH_JWT_SECRET` in your password manager *outside* the VPS. |
| User forgot their password | Operator runs `change_password.py` for them (no current-password check) and shares new password securely |
| Suspected JWT leak | Rotate `OAUTH_JWT_SECRET`; all sessions re-authorize |
| Suspected `BEARER_TOKEN_RW` leak | Rotate `BEARER_TOKEN_RW`; existing JWT sessions continue working (they're not the bearer) |
| Suspected SQLCipher key disclosure | Rotate `SQLCIPHER_KEY` (full re-encryption procedure above); old snapshots stay readable only with old key |
| Need to remove a user permanently | `UPDATE users SET disabled_at = datetime('now')` then `DELETE FROM items WHERE user_id = N` after retention period; rotate `OAUTH_JWT_SECRET` |

---

## Verifying multi-tenant isolation

After creating a second user, confirm isolation manually:

```bash
# As Alice
ALICE=$(curl -sS -X POST -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"<her-pw>"}' \
  https://mypa.example.com/api/auth/login | jq -r .access_token)
curl -sS -H "Authorization: Bearer $ALICE" https://mypa.example.com/api/items
# Should show ONLY Alice's items.

# Try to read another user's item by guessing ID
curl -sS -H "Authorization: Bearer $ALICE" https://mypa.example.com/api/items/1
# Should return 404 if item 1 belongs to someone else.
```

5 automated isolation tests run on every push (see
`tests/test_multi_tenant_isolation.py`).
