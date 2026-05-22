# MyPA User Guide

You've been given access to a MyPA instance by your family/org's
operator. This guide shows you how to log in and connect Claude.

You should have received:
- A **dashboard URL** — e.g. `https://mypa.example.com/`
- Your **email** (the one the operator registered)
- A **one-time password** — change it after first login if you want

---

## 1. Web dashboard

Visit your dashboard URL. You'll land on a login page:

```
┌────────────────────────────────────┐
│   MyPA — Sign in                   │
│                                    │
│   Email:    [_________________]    │
│   Password: [_________________]    │
│                                    │
│   [ Sign in ]                      │
│                                    │
│   ▼ Advanced (API base URL)        │
└────────────────────────────────────┘
```

Sign in with the email + password the operator gave you.

After login you'll see:
- **Items** — everything you've saved, with filters by kind (todo,
  preference, place, decision, etc.)
- **Search** — full-text across titles, bodies, tags
- Your name + a **Sign out** button in the top right

The dashboard is **read + write**: you can add and edit items here.
But most of the action happens through Claude.

⚠️ **Security note:** signing in stores a token in your browser's
localStorage. Don't sign in on a device you don't trust. **Sign out**
when you're done on a shared computer.

---

## 2. Connect Claude.ai (mobile + desktop)

This is where MyPA gets useful: any conversation with Claude can now
read from and write to your personal knowledge base.

**On a desktop browser** (mobile inherits — you don't need to repeat
this on your phone):

1. Open **claude.ai** → **Settings → Connectors**
2. **+ Add custom connector**
3. Fill in:
   - **Name:** `MyPA` (or whatever)
   - **URL:** `https://mypa.example.com/mcp/sse` (use your actual URL)
   - Leave OAuth Client ID / Secret blank
4. Click **Connect**

A new tab opens with a MyPA login form. **Verify the redirect URL on
the page is `https://claude.ai/...`** — if it points somewhere else,
close the tab. Then enter your email + password, click
**Sign in & Authorize**.

The connector now shows **Connected**. Your mobile Claude app
automatically picks it up — no separate setup on the phone.

---

## 3. Using MyPA from Claude

In any chat, ask Claude to use MyPA. Natural language works — you
don't need to say "call pa_add":

| What you say | What happens |
|---|---|
| "Pizza is so good, please remember" | Saved as `preference` with sentiment `love` |
| "Pizza Express on King's Road was amazing yesterday" | Saved as `place` with rating 5 |
| "I bought 100 shares of ABC at $2 — I think it's undervalued because X, Y, Z" | Saved as `decision` with the full reasoning preserved (decisions are append-only — your original thinking is never overwritten) |
| "My IONOS contract ends May 2027" | Saved as `contract` |
| "What restaurants have I rated 5?" | Search → list of `place` items with rating ≥ 5 |
| "Why did I buy 100 shares of ABC?" | Recalls your decision + reasoning |
| "What's on my todo list this week?" | Filters todos with `due_at` in next 7 days |

The casual-capture phrases — "remember", "please remember", "save
this", "help me remember" — are explicit save signals. Claude will
read them back to you ("Saved as `preference` — Pizza. Want to
change?") so you can correct if it picked the wrong kind.

To **undo** the last save: just say "undo that" — Claude will call
`pa_undo_last` for you.

---

## 4. Tips

- **Decisions are special.** When you record reasoning ("bought X
  because Y"), the body is preserved permanently — even if you later
  update the item, the original `body` stays. Use this for any choice
  whose value compounds with hindsight (purchases, investments, career
  moves, parenting calls).
- **Wiki-links connect items.** In Claude or the dashboard, you can
  link items in body text: `[[person:Alice]]`, `[[place:Hummingbird]]`,
  `[[item:42]]`. These are resolved at read time.
- **One source, many devices.** Whatever you save from your phone
  shows up on Claude desktop and the web dashboard, and vice versa.
- **Privacy boundary.** Other people in your family/org install have
  separate accounts; they cannot see your items, and you cannot see
  theirs. Only the operator has visibility into all data (via direct
  DB access on the server).

---

## 5. Changing your password

There's no in-product password-change UI yet. Ask your operator to
run the change-password script with the email of your account; they
won't need to know your current password.

If you forget your password, the operator can reset it the same way.

---

## 6. Do I need to reconnect the Claude connector when things change?

**Almost never.** Items you save show up in Claude's next response
instantly — no reconnect needed. Same for any edits or deletes.

The only time you'll need to reconnect:
- Your operator added new MCP tools and you want to use them in this
  conversation. Open a fresh chat, or disconnect/reconnect the
  connector once.
- Your operator rotated the JWT signing secret (rare). You'll get a
  401 from the connector; re-authorize once.

See [OAUTH_SETUP.md → Q&A](OAUTH_SETUP.md#qa--when-do-i-need-to-reconnect)
for the full breakdown.

## 7. Troubleshooting

| Symptom | Try |
|---|---|
| "Couldn't reach the MCP server" when adding the connector | Check the URL has `https://` and ends in `/mcp/sse` |
| Login fails with "invalid credentials" | Check email is exact (case-insensitive but no typos); ask the operator to reset your password |
| Claude connector worked yesterday, now says "Authorization required" | Operator may have rotated `OAUTH_JWT_SECRET` — re-authorize the connector in claude.ai Settings |
| Dashboard logs you out unexpectedly | Token expired (1h). The dashboard will auto-refresh; if it doesn't, sign in again |
| "I think I saved something but can't find it" | Ask Claude "what did I save in the last hour?" — calls `pa_list` sorted by created_at |
