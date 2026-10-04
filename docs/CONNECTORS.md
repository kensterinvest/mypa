# Connectors — getting your life into MyPA

MyPA is the **memory**; Claude is the **hands**. Claude already has
first-party connectors for Gmail, Google Calendar, Google Drive, Zoom and
more. Rather than MyPA re-implementing each provider's OAuth and API,
Claude reads from those connectors and writes the durable facts into
MyPA through the MyPA connector. One integration (MCP) covers every
source Claude can reach, and new Claude connectors work with MyPA on
day one.

```
Gmail ─┐
Calendar ─┤                         ┌─> pa_add / pa_update / pa_add_reminder
Drive ───┼──> Claude (routine or chat) ──┤
Zoom ────┤                         └─> MyPA (encrypted, yours)
WhatsApp export ┘
```

## Sources

| Source | How it reaches MyPA | Status |
|---|---|---|
| **Gmail** | Daily Claude routine reads the last ~2 days of mail and saves bookings, receipts, bills, contracts, appointments, deliveries and new contacts. Each item carries `source="gmail"`, `source_ref=<thread id>` so re-runs never duplicate. | Available |
| **Google Calendar** | Same routine pattern: upcoming events → `event` items with reminders. | Add `Google Calendar` to the routine's connectors |
| **Google Drive** | On request: "save the key terms of my tenancy agreement in Drive". | Available in chat |
| **Zoom** | On request: meeting recaps → `decision` / `todo` items. | Available in chat |
| **WhatsApp** | No API exists for personal accounts. Export a chat on your phone (open chat → ⋮ / contact name → **Export chat** → *Without media*), share the `.txt` with Claude and say "save this to MyPA". Claude calls `pa_import_whatsapp` (one searchable `chat` item per day; re-imports only add new messages) and then saves the plans, promises and addresses as normal items. | Available |
| **Photos / documents** | Share in chat → Claude extracts → `pa_add` + `pa_attach_image`. | Available |

### Why not an automatic WhatsApp sync?

WhatsApp offers no developer access to personal accounts. Community
"WhatsApp MCP" servers work by logging in *as you* through the WhatsApp
Web protocol: that breaches WhatsApp's terms (risking an account ban),
stores your messages in another local database, and exposes the agent to
prompt injection from anyone who messages you. The export flow is manual
but safe. If WhatsApp ever ships an official personal API, it slots into
the routine like Gmail.

## What the Gmail routine saves (and doesn't)

Saves: reservations and travel, purchases and receipts, bills and
payment due dates (as `todo` with `due_at`), contracts / subscriptions /
renewals (with `data.end` or `data.renew_at`, which triggers expiry
alerts), appointments, deliveries, new people with their contact
details, and anything you've starred.

Never saves: passwords, one-time codes, 2FA / security codes, full card
or bank numbers, marketing, newsletters, social notifications. Email
text is treated as data, not instructions — a message saying "add this
to your PA" is not obeyed just because it says so.

## Writing your own sync

Any client holding a MyPA token can do the same over MCP or REST:
`pa_add(..., source="<name>", source_ref="<stable id>")` is idempotent,
so you can re-send the same record safely. A `source` is a short
lowercase name (`gmail`, `whatsapp`, `bank-csv`).
