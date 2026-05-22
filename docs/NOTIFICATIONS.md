# MyPA Notifications (ntfy)

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
- A **subscribe URL** — looks like `https://ntfy.example.com/u-XXXXXXXXXXXXXXXX`
  (your operator can fetch yours by calling `GET /me/notify-prefs`)

### 1. Install the ntfy mobile app

| Platform | Link |
|---|---|
| iOS | https://apps.apple.com/app/ntfy/id1625396347 |
| Android | https://play.google.com/store/apps/details?id=io.heckel.ntfy |

(The app is free and open-source.)

### 2. Subscribe to your topic

1. Open the ntfy app → tap **+** (add subscription) → **Subscribe to topic**
2. Tap **Use another server** → enter your operator's ntfy URL, e.g.
   `https://ntfy.example.com`
3. **Topic:** paste the `u-XXXXXXXXXXXXXXXX` portion of your subscribe URL
   (just the topic name, not the full URL)
4. Tap **Subscribe**

### 3. Test it

In any Claude chat with the MyPA connector connected:

> *"Send me a MyPA test push"*

Or via curl with your JWT:

```bash
curl -X POST -H "Authorization: Bearer <YOUR_JWT>" \
  https://mypa.example.com/api/me/notify-test
```

You should see a notification arrive on your phone within ~1 second
(iOS may take up to ~30s if the app has been backgrounded for a while).

### 4. Adjust your preferences

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

### 5. If your subscribe URL leaks

Anyone with your subscribe URL can read your notifications (and, under
the current model, send fake ones). If you accidentally shared it,
rotate immediately:

```bash
curl -X POST -H "Authorization: Bearer <JWT>" \
  https://mypa.example.com/api/me/notify-topic/rotate
```

The response includes your new `subscribe_url`. Update the ntfy app on
each device. The old topic stops being used by MyPA but is **not
guaranteed deleted on the ntfy server** under the current model — see
the security section below.

---

## Security model and limitations

**Be honest about what this protects against.** The current default
deployment uses *unguessable topic names* as the only privacy
boundary. It is `secret-URL` security, not authenticated security.

| Threat | Protected against today? |
|---|---|
| Passive Internet scanning for topic names (16 hex chars, ~2^64 keyspace) | ✓ practically yes |
| Someone who learns your topic URL (logs, screenshot, accidental paste) | ✗ they can subscribe and see all your pushes in real time |
| Someone who learns your topic URL spoofing notifications | ✗ they can publish fake "Pick up Kepei NOW" or "Confirm £5000 transfer" messages to your phone, indistinguishable from real MyPA pushes |
| Topic rotation truly revoking the old topic | ✗ the old topic remains publish-and-subscribe-able on the ntfy server until the operator manually deletes it |
| Notification content private from your push provider | ✗ Apple (APNs) and Google (FCM) see message bodies in transit — this is true of every iOS/Android push system, not specific to ntfy |
| Operator with VPS root reading your last 12 hours of notifications | ✗ ntfy caches messages in `/var/cache/ntfy/cache.db` unencrypted |

**Implications.** If you self-host MyPA for your family today, your
notifications are private *as long as the subscribe URL doesn't leak*.
This is fine for "remind me about my dentist appointment" or "today:
3 todos." It is **not** fine if you'd be uncomfortable with anyone who
ever sees that URL also seeing all your future notifications, or
forging them.

**Workarounds you can apply today** (operator-side):
- Don't return `subscribe_url` from logs or non-authenticated endpoints
  (mypa-api only returns it from authenticated `GET /me/notify-prefs`)
- Keep `cache-duration` short — change `/etc/ntfy/server.yml` from 12h
  to e.g. 15m if you don't need offline catch-up
- Use lower-priority notifications without sensitive content (e.g.
  "3 things due today" instead of "Pick up prescription at Boots
  Pharmacy Kings Cross 14:00")

### Queued hardening (next focused work)

The following is planned to land before MyPA is publicly distributed
as a downloadable product:

1. **`auth-default-access: deny-all`** in ntfy server config
2. **Publisher token** — mypa-api authenticates publishes with a token
   stored in `/etc/mypa/env` as `NTFY_PUBLISH_TOKEN`
3. **Per-user subscribe tokens** — each user gets their own ntfy user
   account at creation time; mobile app subscribes with that user's
   credentials, not just a topic URL
4. **`rotate_notify_topic` actually revokes** — calls `ntfy access remove`
   on the old topic
5. **`setup.sh` installs ntfy with auth pre-configured** so operators get
   the secure model by default
6. **Documented iOS background-delivery tradeoff** — self-hosted ntfy
   without an upstream Firebase relay sometimes drops pushes when iOS
   aggressively closes the background socket; the alternatives are
   (a) configure ntfy with `upstream-base-url: https://ntfy.sh` to relay
   through their FCM/APNs servers (privacy tradeoff), or (b) accept
   occasional delivery delays

When these land, this document will be updated to remove the "✗" rows
above and the security model becomes "authenticated push, unguessable
topics + bearer tokens" instead of "unguessable topics only."

### What APNs / FCM see (relevant on every iOS/Android push system)

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
This section will be folded into `setup.sh` in the next iteration.

### 1. DNS

Add an A record `ntfy.<your-domain>` → your VPS IP.

### 2. Install ntfy

```bash
# Download official .deb (replace 2.11.0 with the current release)
ARCH=$(dpkg --print-architecture)
curl -fsSL "https://github.com/binwiederhier/ntfy/releases/download/v2.11.0/ntfy_2.11.0_linux_${ARCH}.deb" -o /tmp/ntfy.deb
sudo dpkg -i /tmp/ntfy.deb
```

### 3. Configure

Write `/etc/ntfy/server.yml`:

```yaml
base-url: "https://ntfy.<your-domain>"
listen-http: "127.0.0.1:9031"
behind-proxy: true
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"
attachment-cache-dir: "/var/cache/ntfy/attachments"
attachment-total-size-limit: "100M"
visitor-request-limit-burst: 60
visitor-message-daily-limit: 500
```

Create the cache dir and restart:

```bash
sudo install -d -m 0750 /var/cache/ntfy
sudo systemctl restart ntfy
sudo systemctl is-active ntfy   # → active
```

### 4. Caddy

Add to `/etc/caddy/Caddyfile`:

```
ntfy.<your-domain> {
    encode gzip zstd
    reverse_proxy 127.0.0.1:9031
}
```

Validate + reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

### 5. Wire MyPA

Add to `/etc/mypa/env`:

```
NTFY_BASE_URL=https://ntfy.<your-domain>
```

Restart `mypa-api` to pick up the env change:

```bash
sudo systemctl restart mypa-api
```

### 6. Apply migration 005

If you're upgrading an existing MyPA install (not running `setup.sh`
from scratch):

```bash
sudo -u mypa bash -c "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
  PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/apply_migrations.py"
```

This adds `users.tz`, `users.notify_topic`, `users.notify_prefs`,
`users.last_digest_at`.

### 7. Backfill existing users

New users created after migration 005 get a `notify_topic` automatically.
For pre-existing users (created before 005), assign topics:

```bash
sudo -u mypa bash -c "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
  PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python -c '
from mypa.db import session_factory
from mypa import users as ul
S = session_factory()
with S() as db:
    for u in ul.list_users(db):
        s = ul.get_notify_settings(db, u.id)
        if not s.get(\"topic\"):
            new = ul.rotate_notify_topic(db, u.id)
            print(f\"{u.email}: {new}\")
'"
```

### 8. Verify end-to-end

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
