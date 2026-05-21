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
}


async def bearer_auth_middleware(request: Request, call_next):
    """Allow /health unauthenticated; everything else needs a valid bearer.

    Writes (POST/PATCH/PUT/DELETE) require RW. Reads accept either.
    401 responses include WWW-Authenticate so well-behaved clients know
    to prompt for / send a bearer.
    """
    if request.url.path in UNAUTHENTICATED_PATHS:
        return await call_next(request)

    scope = classify_token(request.headers.get("authorization", ""))
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

    # Stash scope on request state for handlers that care
    request.state.token_scope = scope
    return await call_next(request)
