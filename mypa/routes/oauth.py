"""OAuth 2.1 endpoints — discovery, authorize, token, register.

URL paths (mounted at the FastAPI app root):
  GET  /.well-known/oauth-authorization-server  — metadata (RFC 8414)
  GET  /oauth/authorize  — login form
  POST /oauth/authorize  — submit credentials, issue auth code
  POST /oauth/token      — exchange code/refresh_token for access token
  POST /oauth/register   — Dynamic Client Registration (RFC 7591)
"""
from __future__ import annotations

import base64
import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import oauth as oauth_lib
from ..db import get_session
from ..settings import settings


router = APIRouter(tags=["oauth"])


def _issuer(request: Request) -> str:
    """Derive issuer from the request URL — respects forwarded headers."""
    public_host = settings().public_host
    return f"https://{public_host}"


# ---------- Discovery -----------------------------------------------------

@router.get("/.well-known/oauth-authorization-server")
async def discovery(request: Request) -> dict:
    """RFC 8414 + MCP authorization spec metadata."""
    issuer = _issuer(request)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "scopes_supported": ["mypa:read", "mypa:write"],
        "service_documentation": f"{issuer}/",
    }


# ---------- Authorize -----------------------------------------------------

_LOGIN_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><title>MyPA — Authorize</title>
<style>
  body {{ font-family: system-ui; max-width: 480px; margin: 4rem auto; padding: 1rem; }}
  h1 {{ font-size: 1.2rem; }}
  .client {{ background: #f0f0f0; padding: 0.6rem 0.8rem; border-radius: 4px; margin-bottom: 1rem; }}
  label {{ display: block; margin-bottom: 1rem; }}
  input {{ width: 100%; padding: 0.5rem; font: inherit; border: 1px solid #999; border-radius: 4px; }}
  button {{ padding: 0.5rem 1.2rem; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }}
  .err {{ color: #842029; background: #f8d7da; padding: 0.5rem; border-radius: 4px; margin-bottom: 1rem; }}
</style></head>
<body>
<h1>MyPA — Authorize a connection</h1>
<div class="client"><strong>{client_name}</strong> is requesting access. <br>
  Scopes: <code>{scope}</code>
</div>
{error_block}
<form method="POST" action="/oauth/authorize">
  <input type="hidden" name="client_id" value="{client_id}">
  <input type="hidden" name="redirect_uri" value="{redirect_uri}">
  <input type="hidden" name="state" value="{state}">
  <input type="hidden" name="code_challenge" value="{code_challenge}">
  <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
  <input type="hidden" name="scope" value="{scope}">
  <label>
    Your MyPA access password (paste your <code>BEARER_TOKEN_RW</code> from the password manager):
    <input type="password" name="password" autofocus required autocomplete="off">
  </label>
  <button type="submit">Authorize</button>
</form>
</body></html>
"""


def _render_form(**kw) -> HTMLResponse:
    return HTMLResponse(content=_LOGIN_FORM.format(**kw))


@router.get("/oauth/authorize")
async def authorize_get(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "mypa:read mypa:write",
    db: Session = Depends(get_session),
):
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="only S256 PKCE supported")
    client = oauth_lib.get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=400, detail="unknown client_id")
    if redirect_uri not in client["redirect_uris"]:
        raise HTTPException(status_code=400, detail="redirect_uri not registered for this client")

    return _render_form(
        client_name=client["name"],
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        error_block="",
    )


@router.post("/oauth/authorize")
async def authorize_post(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    scope: str = Form("mypa:read mypa:write"),
    state: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    # Validate password = BEARER_TOKEN_RW (single-user MyPA).
    s = settings()
    if not hmac.compare_digest(password.encode(), s.bearer_token_rw.encode()):
        return _render_form(
            client_name="<unknown — invalid login>",
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            error_block='<div class="err">Wrong password. Try again.</div>',
        )

    client = oauth_lib.get_client(db, client_id)
    if client is None or redirect_uri not in client["redirect_uris"]:
        raise HTTPException(status_code=400, detail="invalid client or redirect_uri")

    code = oauth_lib.issue_code(
        db,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        user_subject="user",  # single-user
    )
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


# ---------- Token -----------------------------------------------------

def _basic_auth(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(header[6:]).decode()
        cid, _, secret = raw.partition(":")
        return cid, secret
    except Exception:
        return None


@router.post("/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: Session = Depends(get_session),
):
    # Allow client credentials via either Basic auth or POST body.
    if not client_id or not client_secret:
        basic = _basic_auth(request)
        if basic:
            client_id, client_secret = basic
    if not client_id or not client_secret:
        return JSONResponse({"error": "invalid_client"}, status_code=401)

    if oauth_lib.authenticate_client(db, client_id, client_secret) is None:
        return JSONResponse({"error": "invalid_client"}, status_code=401)

    issuer = _issuer(request)

    if grant_type == "authorization_code":
        if not code or not redirect_uri or not code_verifier:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        consumed = oauth_lib.consume_code(db, code, client_id, redirect_uri, code_verifier)
        if consumed is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access = oauth_lib.issue_jwt(client_id, consumed["user_subject"], consumed["scope"], issuer)
        refresh = oauth_lib.issue_refresh_token(db, client_id, consumed["user_subject"], consumed["scope"])
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": settings().oauth_access_token_ttl_sec,
            "refresh_token": refresh,
            "scope": consumed["scope"],
        })

    elif grant_type == "refresh_token":
        if not refresh_token:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        consumed = oauth_lib.consume_refresh_token(db, refresh_token, client_id)
        if consumed is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access = oauth_lib.issue_jwt(client_id, consumed["user_subject"], consumed["scope"], issuer)
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": settings().oauth_access_token_ttl_sec,
            "scope": consumed["scope"],
        })

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


# ---------- Register (Dynamic Client Registration RFC 7591) -------------

@router.post("/oauth/register")
async def register_endpoint(
    request: Request,
    db: Session = Depends(get_session),
):
    """Public DCR — anyone can register a client and gets credentials back.
    For a single-user system this is acceptable since the credentials are
    useless without also passing the /oauth/authorize password step.
    """
    body = await request.json()
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
    name = body.get("client_name") or "Unnamed client"
    scopes = body.get("scope") or "mypa:read mypa:write"

    client = oauth_lib.register_client(
        db, name=name, redirect_uris=redirect_uris, scopes=scopes
    )
    return JSONResponse(
        {
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "client_name": client["name"],
            "redirect_uris": client["redirect_uris"],
            "scope": client["scopes"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
        status_code=201,
    )
