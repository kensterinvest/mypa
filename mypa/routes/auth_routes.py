"""Direct email + password login for the dashboard.

Returns the same shape JWT that OAuth issues — so the bearer
middleware already validates it without changes.

This is a simpler alternative to the full OAuth 2.1 + PKCE flow,
appropriate for the in-house dashboard (same origin, no third-party
client). Claude.ai still uses /oauth/* for its full OAuth dance.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import oauth as oauth_lib
from .. import users as users_lib
from ..db import get_session
from ..settings import settings


router = APIRouter(tags=["auth"])


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

    user = users_lib.authenticate(db, email, password)
    if user is None:
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

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
    return {
        "access_token": access,
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
