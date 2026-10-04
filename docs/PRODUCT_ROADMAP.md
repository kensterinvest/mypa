# Product roadmap — from personal install to an app anyone can run

Goal: MyPA becomes a personal assistant memory that anyone can install,
that holds everything about their life, works with Claude as their
personal connector, and whose data **only the owner can read**.

## Where privacy stands today

| Property | Today |
|---|---|
| Encrypted at rest | Yes — SQLCipher AES-256 for the whole database; backups are equally encrypted. |
| Encrypted in transit | Yes — TLS via Caddy. |
| Per-user isolation | Yes — every query is scoped to the caller's `user_id`; tokens that map to no user are refused. |
| Who can read the data | Whoever holds `SQLCIPHER_KEY`, i.e. **the person running the server**. On a single-owner install, that is the owner. In a shared family install, the admin could read other members' data. |
| Claude | Sees what it reads through the connector, as with any connector. |

So "only the owner can read it" is **true for a one-person install** and
needs more work for shared installs.

## Phase A — easy install for one person (owner holds the key)

The simplest model that meets the privacy goal: **one install per person
or household, run by the owner**.

1. One-command installers: `docker compose` (exists), a Synology / Unraid
   template, and a guided `setup.sh` (exists).
2. **Managed tunnel option** (Cloudflare Tunnel / Tailscale Funnel) so
   people without a domain or open port can still connect Claude.
3. Key ceremony on first run: generate `SQLCIPHER_KEY`, show it once, and
   offer an encrypted recovery file. Lose it and the data is gone — by design.
4. First-run wizard: create an owner, connect Claude (`/mcp`), subscribe
   to ntfy push, pick a timezone, optionally enable the Gmail routine.
5. Export/delete-everything (`pa_export`, account deletion) so "your
   data is yours" is literally true.

## Phase B — shared installs with per-user keys

For a family server where the admin must *not* read members' data:

- **Envelope encryption**: each user gets a data key, wrapped with a key
  derived from their password (Argon2id). Item `title/body/data` are
  encrypted with it; the admin's DB key alone yields ciphertext.
- Trade-off to solve: background jobs (reminders, digests, expiry
  alerts) and Claude's OAuth sessions run when the user isn't typing a
  password. Options: keep a minimal unencrypted schedule table (time +
  item id, no content), and let an OAuth grant carry a wrapped session
  key that expires with the refresh token.
- Search over encrypted fields needs a per-user index kept inside the
  encrypted envelope (or a client-side index).

## Phase C — the most useful assistant

Ranked by daily value; items already shipped are marked ✓.

- ✓ Reliable reminders, repeating reminders, recurring todos, expiry alerts
- ✓ Ranked full-text search with filters on details (rating, cuisine…)
- ✓ Gmail sync routine; WhatsApp export import
- Richer morning summary that names tasks and today's events
- Decision check-ins ("six months on — how did the ABC buy go?")
- Links between people, places and decisions (`[[person:Alice]]`)
- Calendar sync both ways
- Search by meaning (local embeddings, stored encrypted)
- MCP resources/prompts: "today" context and a weekly review prompt
- Import from Google Keep, Todoist, Apple Notes

## Research notes (Oct 2026)

- Leading assistants compete on **memory shared across every surface**
  and on **acting** (email, calendar) rather than just chatting — MyPA's
  split (Claude acts, MyPA remembers) matches this.
  [Vellum](https://www.vellum.ai/blog/best-personal-ai-assistants-with-memory),
  [Zapier](https://zapier.com/blog/ai-personal-assistant/)
- WhatsApp has no official personal-account API or MCP; community
  servers log in as the user and sit outside WhatsApp's terms.
  [vorplabs](https://vorplabs.com/agent-tools/whatsapp-cli),
  [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)
- Privacy-first tools (Notesnook, AnyType, SiYuan) use zero-knowledge /
  end-to-end encryption with self-hostable sync — the bar for Phase B.
  [privacytools.io](https://privacytools.io/encrypted-notebooks)
