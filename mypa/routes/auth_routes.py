"""Direct email + password login for the dashboard.

Returns the same shape JWT that OAuth issues — so the bearer
middleware already validates it without changes.

This is a simpler alternative to the full OAuth 2.1 + PKCE flow,
appropriate for the in-house dashboard (same origin, no third-party
client). Claude.ai still uses /oauth/* for its full OAuth dance.
"""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import oauth as oauth_lib
from .. import users as users_lib
from ..db import get_session
from ..settings import settings


router = APIRouter(tags=["auth"])

# Per-IP + per-email login-attempt tracking. The global SlowAPI limit
# (60/min/IP) is not enough for credential stuffing: an attacker with one
# IP can try 60 distinct emails or 60 passwords on one email per minute.
# This adds: max 5 failed attempts per (ip, email) per 5-min window, then
# 401 (with a friendly message) until window expires.
_FAIL_WINDOW_SEC = 300         # 5 minutes
_FAIL_THRESHOLD = 5            # 5 fails per window = block
_login_fail_log: dict[tuple[str, str], list[float]] = defaultdict(list)
_login_fail_lock = Lock()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if fwd:
        return fwd
    return request.client.host if request.client else "?"


def _check_login_throttle(ip: str, email: str) -> bool:
    """Return True if (ip, email) is allowed to attempt login now.
    Returns False if currently throttled (too many recent failures).
    Side-effect: drops stale entries from the log."""
    now = time.time()
    cutoff = now - _FAIL_WINDOW_SEC
    key = (ip, email.lower())
    with _login_fail_lock:
        fails = _login_fail_log[key]
        fails[:] = [t for t in fails if t > cutoff]
        return len(fails) < _FAIL_THRESHOLD


def _record_login_failure(ip: str, email: str) -> None:
    key = (ip, email.lower())
    with _login_fail_lock:
        _login_fail_log[key].append(time.time())


def _clear_login_failures(ip: str, email: str) -> None:
    """On successful login, clear the counter so future failures aren't
    biased by ancient ones."""
    key = (ip, email.lower())
    with _login_fail_lock:
        _login_fail_log.pop(key, None)


@router.post("/auth/login")
def login(payload: dict, request: Request, db: Session = Depends(get_session)):
    """Body: {email, password}. Returns: {access_token, refresh_token, expires_in, user}.
    The access_token is a JWT identical to what /oauth/token issues — works
    everywhere a regular JWT works.
    """
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        return JSONResponse({"error": "email and password required"}, status_code=400)

    ip = _client_ip(request)
    if not _check_login_throttle(ip, email):
        # 429 makes it explicit to clients that this is rate-limit, not
        # credential failure. Don't leak which (ip, email) is throttled vs
        # which combinations exist — same response shape regardless.
        return JSONResponse(
            {"error": "too many failed attempts; try again in a few minutes"},
            status_code=429,
        )

    user = users_lib.authenticate(db, email, password)
    if user is None:
        _record_login_failure(ip, email)
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    _clear_login_failures(ip, email)

    issuer = f"https://{settings().public_host}" if settings().public_host else "mypa"
    # Issue a JWT with full mypa:read mypa:write scope (or :read only if you
    # later want a read-only dashboard mode — pass scope='mypa:read' here).
    access = oauth_lib.issue_jwt(
        client_id="dashboard",
        user_subject=str(user.id),
        scope="mypa:read mypa:write",
        issuer=issuer,
    )
    refresh = oauth_lib.issue_refresh_token(
        db, client_id="dashboard", user_subject=str(user.id), scope="mypa:read mypa:write",
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": settings().oauth_access_token_ttl_sec,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_admin": user.is_admin,
        },
    }


@router.post("/auth/refresh")
def refresh(payload: dict, request: Request, db: Session = Depends(get_session)):
    """Body: {refresh_token}. Returns: {access_token, expires_in}.
    Used by the dashboard to get a new access token without re-prompting.
    """
    rt = payload.get("refresh_token") or ""
    if not rt:
        return JSONResponse({"error": "refresh_token required"}, status_code=400)

    # The "dashboard" pseudo-client doesn't actually need DCR — refresh tokens
    # are issued for client_id="dashboard"; consume_refresh_token will validate.
    consumed = oauth_lib.consume_refresh_token(db, rt, client_id="dashboard")
    if consumed is None:
        return JSONResponse({"error": "invalid refresh_token"}, status_code=401)

    issuer = f"https://{settings().public_host}" if settings().public_host else "mypa"
    access = oauth_lib.issue_jwt(
        client_id="dashboard",
        user_subject=consumed["user_subject"],
        scope=consumed["scope"],
        issuer=issuer,
    )
    # Rotation: consume_refresh_token issued a fresh refresh token for us;
    # the old one is now marked used and cannot be replayed (replay
    # revokes the whole family).
    return {
        "access_token": access,
        "refresh_token": consumed["new_refresh_token"],
        "token_type": "Bearer",
        "expires_in": settings().oauth_access_token_ttl_sec,
    }


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_session)):
    """Return the current user — derived from the JWT (or static bearer)."""
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        return JSONResponse({"error": "no user context"}, status_code=401)
    u = users_lib.get_user(db, uid)
    if u is None:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return {"id": u.id, "email": u.email, "name": u.name, "is_admin": u.is_admin}
