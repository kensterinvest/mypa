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
    """Return RW / RO scope of the bearer in the Authorization header, or None."""
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[7:].strip()
    s = settings()
    if s.bearer_token_rw and token == s.bearer_token_rw:
        return TokenScope.RW
    if s.bearer_token_ro and token == s.bearer_token_ro:
        return TokenScope.RO
    return None


WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
UNAUTHENTICATED_PATHS = {"/health"}


async def bearer_auth_middleware(request: Request, call_next):
    """Allow /health unauthenticated; everything else needs a valid bearer.

    Writes (POST/PATCH/PUT/DELETE) require RW. Reads accept either.
    """
    if request.url.path in UNAUTHENTICATED_PATHS:
        return await call_next(request)

    scope = classify_token(request.headers.get("authorization", ""))
    if scope is None:
        return JSONResponse({"error": "unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)

    if request.method in WRITE_METHODS and scope != TokenScope.RW:
        return JSONResponse(
            {"error": "forbidden", "detail": "RO token cannot perform writes"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Stash scope on request state for handlers that care
    request.state.token_scope = scope
    return await call_next(request)
