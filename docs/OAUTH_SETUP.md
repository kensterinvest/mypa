# OAuth setup for MyPA — connecting Claude.ai

This guide walks you through connecting your MyPA instance to
**Claude.ai (mobile + desktop)** as a custom MCP connector.

MyPA implements OAuth 2.1 with PKCE and Dynamic Client Registration
(RFC 7591), so Claude.ai sets itself up — you only paste the URL and
your password.

## Before you start

You should already have:

- MyPA running on your domain (see [README.md](../README.md) "Quick start")
- Your `BEARER_TOKEN_RW` saved in your password manager
- Access to claude.ai on a desktop browser (mobile inherits — see below)

## Step 1 — Add the connector on claude.ai desktop

1. Open **claude.ai** in a browser (desktop or laptop)
2. **Settings → Connectors**
3. **+ Add custom connector** (or "Add MCP server")
4. Fill in:
   - **Name:** `MyPA` (or anything)
   - **URL:** `https://mypa.example.com/mcp/sse` ← your actual domain
   - **OAuth Client ID:** leave blank
   - **OAuth Client Secret:** leave blank
5. Click **Connect** / **Save**.

Claude.ai will:
- Probe your server, discover OAuth via `/.well-known/oauth-authorization-server`
- Auto-register itself as a client via `POST /oauth/register` (DCR)
- Open a new browser tab to your `/oauth/authorize` endpoint

## Step 2 — Authorize on the MyPA login form

The form shows:

```
MyPA — Authorize a connection

Claude is requesting access.
Scopes: mypa:read mypa:write
Will redirect to: https://claude.ai/api/mcp/auth_callback

⚠️ Check the redirect URL above. It should point to a service you trust
(e.g. claude.ai). If it points anywhere unexpected — close this tab and
do NOT enter your password.

[Your MyPA access password (paste your BEARER_TOKEN_RW): ____________]
[Authorize]
```

1. **Verify the redirect URL** is a `https://claude.ai/...` address. If
   it's NOT, close the tab — something fishy is going on (someone is
   trying to phish you, or you have the wrong server URL).
2. Paste your `BEARER_TOKEN_RW` (from your password manager) into the
   password field.
3. Click **Authorize**.

## Step 3 — Verify connection

After clicking Authorize, you'll be redirected back to Claude.ai. The
connector status should show **Connected**.

Then in any Claude.ai chat (mobile or desktop):

> *"Use MyPA — what tools are available?"*

Claude should list your tools (`pa_add`, `pa_get`, `pa_list`,
`pa_search`, `pa_describe_schema`, `pa_undo_last`, `pa_delete`,
`pa_update`, `pa_complete`, `pa_add_reminder`).

A first capture to test:

> *"Save: pizza is so good, remember it."*

Should produce a `preference` item with sentiment `love`. Verify on
your server:

```bash
curl -sS -H "Authorization: Bearer $BEARER_TOKEN_RW" \
  https://mypa.example.com/api/items
```

## Mobile

The mobile Claude.ai app **inherits all connectors** added on desktop
(there's no "+ Add connector" UI on mobile by design). After Step 3
above, your phone's Claude app will see MyPA automatically.

## Troubleshooting

### "Couldn't reach the MCP server"

Either:
- Your URL is wrong (check the `https://` and the `/mcp/sse` path)
- DNS hasn't propagated (test with `curl https://your-domain/.well-known/oauth-authorization-server`)
- Your firewall blocks port 443 (open it at the OS firewall AND any
  cloud-provider firewall — both layers must allow)
- The MCP server crashed (`systemctl status mypa-mcp`)

### "POST /sse returned 405"

You're running the older SSE transport. Switch to Streamable HTTP — see
`mypa/mcp_server.py`:

```python
mcp = FastMCP(name="mypa", streamable_http_path="/sse", ...)
# ...
app.mount("/", mcp.streamable_http_app())  # NOT mcp.sse_app()
```

And wire the lifespan:

```python
@asynccontextmanager
async def lifespan(app):
    async with _mcp_app.router.lifespan_context(_mcp_app):
        yield
```

### "Invalid Host header"

DNS-rebinding protection is rejecting the request. Add your domain to
`allowed_hosts` in `FastMCP(transport_security=TransportSecuritySettings(...))`.

### "redirect_uri rejected"

Your client's redirect URI host isn't on the allow-list. Edit
`mypa/routes/oauth.py` `_ALLOWED_REDIRECT_HOSTS` to include the new
host. Default: only `claude.ai`.

### Token rotation

```bash
NEW=$(openssl rand -base64 36 | tr -d "\n=+/" | head -c 40)
sudo sed -i "s|^BEARER_TOKEN_RW=.*|BEARER_TOKEN_RW=$NEW|" /etc/mypa/env
sudo systemctl restart mypa-api mypa-mcp
echo "New token: $NEW"  # save to password manager
```

Existing Claude.ai connectors **continue to work** — they hold JWTs
signed with `OAUTH_JWT_SECRET`, not the bearer. The bearer is only
checked at `/oauth/authorize` (next re-connect).

### JWT secret rotation (nuclear option)

```bash
NEW=$(openssl rand -base64 48 | tr -d "\n=+/" | head -c 64)
sudo sed -i "s|^OAUTH_JWT_SECRET=.*|OAUTH_JWT_SECRET=$NEW|" /etc/mypa/env
sudo systemctl restart mypa-api mypa-mcp
```

⚠️ This **invalidates every existing JWT** — every connected
Claude.ai must re-authorize.

## Pre-provisioned clients

If you ever need to skip DCR and pre-issue a client:

```bash
cd /opt/mypa && sudo -u mypa bash -c \
  "set -a; source /etc/mypa/env; set +a; cd /opt/mypa; \
   PYTHONPATH=/opt/mypa /opt/mypa/.venv/bin/python scripts/oauth_register_client.py \
   'Some App' 'https://someapp.example.com/oauth/callback'"
```

Prints `client_id` + `client_secret` once. Paste both into the
client's OAuth settings.
