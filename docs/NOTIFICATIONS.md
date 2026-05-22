# MyPA Notifications (ntfy)

> **Notifications are an optional add-on.** MyPA is fundamentally an
> archive — Claude (or any MCP-compatible AI) reads and writes your
> data via the MCP server. The archive, the web dashboard, the REST
> API, the OAuth integration, and Claude.ai's connector ALL work
> without the notification layer. If you don't want phone push for
> reminders and the morning digest, **skip the ntfy step in
> `setup.sh`** and the rest of MyPA still runs fine.
>
> Read on if you do want push notifications.

## Why ntfy and not Claude's own notifications?

Claude.ai's mobile app surfaces notifications for new messages in
conversations you're in — not for arbitrary "remind me at 14:00"
events. There's no public Claude API for scheduled push. MyPA needs
its own notification channel.

We chose [ntfy](https://ntfy.sh) because:

- It's open-source and self-hostable on the same VPS as MyPA
- Free mobile apps for iOS + Android
- Multi-user via topics with per-user authentication
- No third-party notification provider in the middle of your data
  (except the unavoidable APNs/FCM hop — same as every iOS/Android push)

Alternatives you can plug in instead (operator's choice — requires code
changes in `mypa/notifier.py`): Pushover, Pushbullet, Slack webhooks,
Discord webhooks, email-via-SMTP, webhook-to-anything. The
`notifier.publish()` interface is small.

ntfy is the default because it satisfies the "self-hosted, no third
party, multi-user" constraint that the rest of MyPA aims for.

---

## How the rest works (ntfy enabled)

MyPA pushes reminders and daily digests to your phone via a self-hosted
**[ntfy](https://ntfy.sh)** server. ntfy is a lightweight pub-sub service
with native iOS and Android apps; we run our own instance so your
notification data never touches a third-party server (except the unavoidable
APNs/FCM hop for the actual push delivery — see "What APNs/FCM see"
below).

This doc has two halves:
- **For end users** — how to subscribe and adjust your settings
- **For operators** — how to install ntfy on a new MyPA deployment, plus
  the current security model and what's queued for hardening

---

## End-user setup

You should have been given:
- Your dashboard URL (e.g. `https://mypa.example.com/`)
- Your email + password

After login, your **ntfy credentials** (server URL, username, password)
are available at `GET /me/notify-prefs`. The mobile-app setup below
shows you how to use them.

### 1. Install the ntfy mobile app

| Platform | Link |
|---|---|
| iOS | https://apps.apple.com/app/ntfy/id1625396347 |
| Android | https://play.google.com/store/apps/details?id=io.heckel.ntfy |

(The app is free and open-source.)

### 2. Get your credentials

```bash
curl -sS -H "Authorization: Bearer <YOUR_JWT>" \
  https://mypa.example.com/api/me/notify-prefs
```

You'll get back something like:
```json
{
  "ntfy_server": "https://ntfy.example.com",
  "ntfy_username": "u-4281195b6832d817",
  "ntfy_password": "hrrmXL85hfEIDeu9YHj5BEb-",
  "topic": "u-4281195b6832d817",
  ...
}
```

Or just ask Claude: *"show me my MyPA notification credentials"*.

### 3. Subscribe in the ntfy app

1. Open the ntfy app → **Settings → Users** → **+** (add user)
2. **Server URL:** paste `ntfy_server` (e.g. `https://ntfy.example.com`)
3. **Username + Password:** paste from the credentials response above
4. Back on the home screen → tap **+** → **Subscribe to topic**
5. Tap **Use another server** → select the server you just added
6. **Topic:** paste `topic` value (the `u-…` string)
7. Tap **Subscribe**

The mobile app will use Basic auth on all subsequent connections. Without
the username + password, subscribing returns 401 even if someone knows the
topic name.

### 4. Test it

In any Claude chat with the MyPA connector connected:

> *"Send me a MyPA test push"*

Or via curl with your JWT:

```bash
curl -X POST -H "Authorization: Bearer <YOUR_JWT>" \
  https://mypa.example.com/api/me/notify-test
```

You should see a notification arrive on your phone within ~1 second
(iOS may take up to ~30s if the app has been backgrounded for a while).

### 5. Adjust your preferences

In a Claude chat:

> *"Change my MyPA morning digest to 08:00 instead of 07:00"*
> *"Turn off the morning digest"*
> *"Enable the weekly overdue catch-up — Sunday 09:00"*
> *"Update my MyPA timezone to America/New_York"*

Claude will call `pa_set_notify_prefs(...)` with the relevant fields.

Or via REST:

```bash
curl -X PATCH -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
  -d '{"digest_hour": 8}' \
  https://mypa.example.com/api/me/notify-prefs
```

Available fields:

| Field | Type | Default | Effect |
|---|---|---|---|
| `tz` | IANA TZ string | `Europe/London` (or operator default) | Frame of reference for digest_hour and "today" calculations |
| `realtime` | bool | `true` | Push reminders the instant their `fire_at` time arrives |
| `digest_enabled` | bool | `true` | Daily morning summary (todos due today, events, overdue count) |
| `digest_hour` | int 0-23 | `7` | When the daily digest fires, in your `tz` |
| `overdue_weekly_enabled` | bool | `false` | Weekly catch-up listing open-but-overdue todos |
| `overdue_day` | int 0-6 | `0` (Sun) | Day of week for the weekly catch-up |
| `overdue_hour` | int 0-23 | `9` | Hour of day for the weekly catch-up |

### 6. If your credentials leak

If your `ntfy_password` (or the JSON blob containing it) is exposed —
shared screenshot, accidental paste, lost device — rotate immediately:

```bash
curl -X POST -H "Authorization: Bearer <JWT>" \
  https://mypa.example.com/api/me/notify-topic/rotate
```

The response contains a brand-new `topic`, `ntfy_username`, and
`ntfy_password`. Update the ntfy app on each device.

**True revocation:** the old ntfy account is deleted server-side, so
the old password stops working immediately — not just "stopped being
used by MyPA." Anyone who had the old credentials gets 401 on next
subscribe attempt.

---

## Security model

ntfy is configured with `auth-default-access: deny-all`. Nothing is
publish-able or subscribe-able without credentials.

**Three classes of credentials live in the system:**

| User | Role | Access | Where the credential lives |
|---|---|---|---|
| `admin` | admin | full | `/etc/mypa/env` as `NTFY_ADMIN_PASSWORD`; used only by operator scripts |
| `mypa-publisher` | regular | write-only on `u-*` | `/etc/mypa/env` as `NTFY_PUBLISH_PASSWORD`; used by mypa-api to send every push |
| `u-<random16>` (one per MyPA user) | regular | read-only on their own topic | `users.notify_token` column, returned via authenticated `GET /me/notify-prefs` to the owning user |

The MyPA application **never sees the publisher password being used
for a user-facing API** — it lives in env, mypa-api uses it server-side
when calling ntfy. The per-user `ntfy_password` is what the user puts in
their mobile app and is never used to publish.

| Threat | Protected against |
|---|---|
| Passive Internet scanning for topic names | ✓ (16-hex namespace + auth on top) |
| Someone learns your topic URL but not your credentials | ✓ — subscribing returns 401 |
| Someone spoofs notifications to your phone | ✓ — publish requires `mypa-publisher` credentials; anonymous POST is 403 |
| Topic rotation truly revoking old credentials | ✓ — the old ntfy account is `ntfy user remove`'d server-side, 401 on next use |
| Disabled user can no longer receive pushes | ✓ — `disable_user()` calls `ntfy user remove` |
| Notification content private from Apple/Google | ✗ — APNs/FCM see message bodies (unavoidable on every iOS/Android push system) |
| Operator with VPS root reading your last 12 hours of notifications | ✗ — ntfy caches messages in `/var/cache/ntfy/cache.db` unencrypted (mitigation: lower `cache-duration` to ~15m) |

### iOS background-delivery tradeoff

Self-hosted ntfy maintains a persistent socket to the mobile app. iOS
aggressively closes background sockets to save battery. Two delivery paths:

1. **Direct mode (default in our setup):** notification arrives via the
   open socket when the app is in foreground; iOS wakes the app via
   APNs when in background. Sometimes results in delayed delivery on
   iOS — typical lag is 15-60s when waking from deep background.
2. **Upstream relay mode:** add `upstream-base-url: https://ntfy.sh` to
   `/etc/ntfy/server.yml`. ntfy relays your notifications through
   ntfy.sh's hosted infrastructure for reliable FCM/APNs delivery.
   **Privacy tradeoff:** ntfy.sh metadata logs see message timestamps
   and your topic name (but not the body, which is end-to-end-ish
   between your server and the device). Most family installs accept
   this tradeoff for reliable iOS pushes; privacy-strict operators
   leave it off.

### What APNs/FCM see (relevant on every iOS/Android push system)

When an iPhone or Android device is asleep, ntfy can't push directly.
It pushes through:
- **APNs** (Apple Push Notification service) for iOS
- **FCM** (Firebase Cloud Messaging) for Android

Apple and Google see the **message body** in transit. This is unavoidable
for any push system on those platforms — including Telegram, WhatsApp,
Signal, Slack, etc., unless you use end-to-end encrypted payloads (which
ntfy supports via the app's "encrypted topics" feature, but our server-side
publish path doesn't use yet).

Practical mitigation: keep notification bodies factual and free of
sensitive details. The link/click action on the notification can deep-link
to the dashboard where the full context lives.

---

## Operator install (from scratch)

For new MyPA deployments, install ntfy on the same VPS as mypa-api.
This section will be folded into `setup.sh` in a future iteration.

### 1. DNS

Add an A record `ntfy.<your-domain>` → your VPS IP.

### 2. Install ntfy

```bash
ARCH=$(dpkg --print-architecture)
curl -fsSL "https://github.com/binwiederhier/ntfy/releases/download/v2.11.0/ntfy_2.11.0_linux_${ARCH}.deb" -o /tmp/ntfy.deb
sudo dpkg -i /tmp/ntfy.deb
```

### 3. Configure with auth

Write `/etc/ntfy/server.yml`:

```yaml
base-url: "https://ntfy.<your-domain>"
listen-http: "127.0.0.1:9031"
behind-proxy: true

# Authentication — required.
auth-file: "/var/lib/ntfy/auth.db"
auth-default-access: "deny-all"

cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"
attachment-cache-dir: "/var/cache/ntfy/attachments"
attachment-total-size-limit: "100M"
visitor-request-limit-burst: 60
visitor-message-daily-limit: 500
```

Prepare directories and start:

```bash
sudo install -d -o ntfy -g ntfy -m 0750 /var/cache/ntfy /var/lib/ntfy
sudo systemctl restart ntfy
sudo systemctl is-active ntfy
```

### 4. Create admin + publisher ntfy users

```bash
ADMIN_PW=$(openssl rand -base64 30 | tr -d "\n=+/" | head -c 32)
PUB_PW=$(openssl rand -base64 30 | tr -d "\n=+/" | head -c 32)

NTFY_PASSWORD=$ADMIN_PW sudo -E ntfy user add --role=admin admin
NTFY_PASSWORD=$PUB_PW sudo -E ntfy user add mypa-publisher
sudo ntfy access mypa-publisher "u-*" write
```

Record both passwords in your password manager.

### 5. Caddy

```
ntfy.<your-domain> {
    encode gzip zstd
    reverse_proxy 127.0.0.1:9031
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

### 6. Sudoers — allow mypa-api to manage per-user ntfy accounts

```bash
sudo tee /etc/sudoers.d/mypa-ntfy >/dev/null <<'EOF'
mypa ALL=(root) NOPASSWD: SETENV: /usr/bin/ntfy user add *, /usr/bin/ntfy user remove *, /usr/bin/ntfy user change-pass *, /usr/bin/ntfy access *, /usr/bin/ntfy token *
EOF
sudo chmod 0440 /etc/sudoers.d/mypa-ntfy
sudo visudo -c -f /etc/sudoers.d/mypa-ntfy
```

`SETENV:` is required so `NTFY_PASSWORD` reaches the ntfy CLI through
`sudo -E`. Without it `ntfy user add` receives an empty password.

### 7. Wire MyPA env

Append to `/etc/mypa/env`:

```
NTFY_BASE_URL=https://ntfy.<your-domain>
NTFY_ADMIN_USER=admin
NTFY_ADMIN_PASSWORD=<ADMIN_PW from step 4>
NTFY_PUBLISH_USER=mypa-publisher
NTFY_PUBLISH_PASSWORD=<PUB_PW from step 4>
```

Restart:

```bash
sudo systemctl restart mypa-api
```

### 8. Apply migrations 005 + 006

```bash
sudo -u mypa bash -c "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
  PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/apply_migrations.py"
```

005 adds `users.tz`, `users.notify_topic`, `users.notify_prefs`,
`users.last_digest_at`. 006 adds `users.notify_token`.

### 9. Backfill existing users

For users created before this setup:

```bash
sudo -u mypa bash -c "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
  PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/backfill_ntfy_accounts.py"
```

This creates one ntfy account per existing MyPA user with read-only
access to their own topic.

### 10. Verify end-to-end

```bash
# Log in as a user, get their subscribe URL
JWT=$(curl -sS -X POST -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"..."}' \
  https://mypa.<your-domain>/api/auth/login | jq -r .access_token)

curl -sS -H "Authorization: Bearer $JWT" \
  https://mypa.<your-domain>/api/me/notify-prefs

# Send a test push
curl -X POST -H "Authorization: Bearer $JWT" \
  https://mypa.<your-domain>/api/me/notify-test
```

The user should subscribe to their topic in the ntfy mobile app (see
"End-user setup" above) and confirm the test notification arrives.

---

## How dispatch works

Two APScheduler jobs run inside `mypa-api` every 60 seconds:

| Job | What |
|---|---|
| `dispatch_reminders` | Scans `reminders` where `fire_at <= now() AND fired_at IS NULL`. For each row: resolve the user's topic + prefs, skip if `realtime: false`, publish to ntfy, mark `fired_at`. |
| `dispatch_digests` | For each user with `disabled_at IS NULL AND notify_topic IS NOT NULL`: compute current hour in their TZ, if equal to `digest_hour` AND `last_digest_at` is before today-in-user-TZ-00:00, build a digest of items due today + overdue count + named events, publish, update `last_digest_at`. |

The weekly overdue job is in the same loop; it fires when `now in user_tz`
matches `(overdue_day, overdue_hour)` and the previous fire is more than
6 days old.

### Scope guarantees

- Every query in both jobs has an explicit `user_id` predicate.
- A user's reminder can only push to that user's `notify_topic` — the row's `user_id` is resolved to the user, then to their topic, with no cross-row leakage.
- Multi-tenant isolation tests verify this (see `tests/test_notifications.py::test_dispatch_reminders_fires_due_and_marks_fired_at`).

### What happens if mypa-api is down

- Reminders queued in DB are not lost — when mypa-api restarts, `dispatch_reminders` catches up on any `fire_at <= now` rows.
- Digests are not retroactive — if mypa-api was down at your `digest_hour`, you don't get a delayed digest. (We considered surfacing missed digests on next-run but decided "yesterday's morning summary at 19:00" is worse than "no summary today.")

---

## FAQ

**Q: I'm not getting pushes on iOS.**
A: iOS aggressively closes the persistent socket the ntfy app keeps to
your self-hosted server. You'll get notifications when you open the app,
or via Apple's wake-on-push, but background delivery is patchy. Two
options: (1) accept the tradeoff for full self-hosting, (2) configure
your operator's ntfy with `upstream-base-url: https://ntfy.sh` which
relays via Firebase for reliable iOS delivery — at the cost of message
metadata flowing through ntfy.sh.

**Q: Can I get pushes on my Apple Watch?**
A: Yes — the ntfy iOS app forwards to Watch automatically once the
Watch is paired.

**Q: How private are the notification bodies?**
A: See "What APNs/FCM see" above. Short answer: Apple/Google see them
in transit. Don't put secrets in notification text.

**Q: Can I subscribe from a web browser?**
A: Yes — `https://ntfy.<your-domain>/u-XXXX` in any browser shows a
live SSE feed. Useful for testing.

**Q: How do I stop notifications temporarily without losing my settings?**
A: `pa_set_notify_prefs(realtime=False, digest_enabled=False)` or
unsubscribe in the ntfy app. Both leave your prefs and topic intact.

**Q: What if I rotate my topic and miss a reminder during the rotation?**
A: The dispatcher publishes to whatever the current `notify_topic` is.
If the mobile app hasn't re-subscribed to the new topic yet, that
notification is lost (ntfy keeps it in cache for 12h, but only
re-subscribing brings it down).
