"""Bearer-token middleware with RW + RO token separation.

The dashboard uses the RO token (read-only); Claude / agents use RW.
Stolen device with RO token → cannot mutate data.
"""
from __future__ import annotations

from enum import Enum

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from .settings import settings


class TokenScope(str, Enum):
    RW = "rw"
    RO = "ro"


def resolve_admin_user_id() -> int | None:
    """Look up the admin user_id once, lazily. Returns None on bootstrap when no
    admin exists yet (e.g., during install or before backfill).
    """
    from .db import session_factory
    from .users import get_admin_user
    try:
        Session = session_factory()
        with Session() as db:
            admin = get_admin_user(db)
            return admin.id if admin else None
    except Exception:
        return None


def classify_token(header_value: str) -> TokenScope | None:
    """Return RW / RO scope of the bearer in the Authorization header, or None.

    Accepts three token forms:
      1. Static BEARER_TOKEN_RW (Claude Code, scripts, dashboard)
      2. Static BEARER_TOKEN_RO (read-only dashboard / scripts)
      3. OAuth JWT issued via /oauth/token (Claude.ai mobile / custom MCP clients).
         Scope decoded from the JWT's `scope` claim.
    """
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[7:].strip()
    s = settings()
    if s.bearer_token_rw and token == s.bearer_token_rw:
        return TokenScope.RW
    if s.bearer_token_ro and token == s.bearer_token_ro:
        return TokenScope.RO
    # OAuth JWT path — only if OAUTH_JWT_SECRET is set
    if s.oauth_jwt_secret and token.count(".") == 2:
        try:
            from . import oauth as oauth_lib
            claims = oauth_lib.verify_jwt(token)
            if claims is None:
                return None
            scope = claims.get("scope", "")
            if "mypa:write" in scope:
                return TokenScope.RW
            if "mypa:read" in scope:
                return TokenScope.RO
        except Exception:
            return None
    return None


WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
# OAuth endpoints are intentionally unauthenticated — they ARE the auth.
UNAUTHENTICATED_PATHS = {
    "/health",
    "/health/ready",
    "/.well-known/oauth-authorization-server",
    "/oauth/authorize",
    "/oauth/token",
    "/oauth/register",
    "/auth/login",
    "/auth/refresh",
}


def _user_id_from_token(header_value: str) -> int | None:
    """Extract user_id from a bearer.

    - Static BEARER_TOKEN_RW/RO → admin user_id (lookup)
    - OAuth JWT with numeric `sub` → that user_id
    - OAuth JWT with `sub="user"` (legacy single-tenant token) → admin user_id
    - Anything else → None
    """
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[7:].strip()
    s = settings()
    if s.bearer_token_rw and token == s.bearer_token_rw:
        return resolve_admin_user_id()
    if s.bearer_token_ro and token == s.bearer_token_ro:
        return resolve_admin_user_id()
    if s.oauth_jwt_secret and token.count(".") == 2:
        try:
            from . import oauth as oauth_lib
            claims = oauth_lib.verify_jwt(token)
            if claims is None:
                return None
            sub = claims.get("sub")
            if isinstance(sub, int):
                return sub
            if isinstance(sub, str) and sub.isdigit():
                return int(sub)
            # Legacy "user" sub → admin
            if sub == "user":
                return resolve_admin_user_id()
        except Exception:
            return None
    return None


async def bearer_auth_middleware(request: Request, call_next):
    """Allow /health (and OAuth endpoints) unauthenticated; everything else
    needs a valid bearer.

    Sets `request.state.token_scope` and `request.state.user_id` for handlers.
    """
    if request.url.path in UNAUTHENTICATED_PATHS:
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    scope = classify_token(auth_header)
    if scope is None:
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={'WWW-Authenticate': 'Bearer realm="mypa"'},
        )

    if request.method in WRITE_METHODS and scope != TokenScope.RW:
        return JSONResponse(
            {"error": "forbidden", "detail": "RO token cannot perform writes"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    request.state.token_scope = scope
    user_id = _user_id_from_token(auth_header)
    request.state.user_id = user_id

    # Also publish the request context to audit.py's ContextVars so the
    # REST surface can call audit() with the same user_id/scope tracking
    # the MCP middleware already provides.
    try:
        from .audit import set_request_context
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?")
        )
        set_request_context(client_ip, scope.value if scope else "?", user_id=user_id)
    except Exception:
        pass

    return await call_next(request)
