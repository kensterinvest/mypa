"""OAuth 2.1 server primitives for MyPA — client registry, auth codes,
JWT issuance + verification.

Implements the minimum subset of OAuth 2.1 that Claude.ai's Custom MCP
connector needs:

  - Discovery (RFC 8414 + MCP authorization spec 2025-03-26)
  - Authorization Code flow with PKCE (S256)
  - Optional Dynamic Client Registration (RFC 7591)
  - Bearer JWT access tokens (HS256, signed with OAUTH_JWT_SECRET)
  - Opaque refresh tokens stored in DB

The single human user is identified by a single password (the existing
BEARER_TOKEN_RW). Login = pasting that password into the /oauth/authorize
form. Successful login issues an auth code, then JWT.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta

import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from .settings import settings


# ----- helpers ---------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def gen_secret(nbytes: int = 32) -> str:
    """URL-safe random secret."""
    return _b64url(secrets.token_bytes(nbytes))


def hash_secret(secret: str) -> str:
    """One-way hash for at-rest storage."""
    return hashlib.sha256(secret.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def jwt_secret() -> str:
    """Lazily ensure OAUTH_JWT_SECRET exists; raise if not set."""
    s = settings().oauth_jwt_secret
    if not s:
        raise RuntimeError(
            "OAUTH_JWT_SECRET env var required. Generate one: "
            "openssl rand -base64 48"
        )
    return s


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    """RFC 7636 PKCE verification. Only S256 supported per OAuth 2.1."""
    if method != "S256":
        return False
    expected = _b64url(hashlib.sha256(code_verifier.encode()).digest())
    return hmac.compare_digest(expected, code_challenge)


# ----- client registry -------------------------------------------------------

def register_client(
    db: Session,
    name: str,
    redirect_uris: list[str],
    scopes: str = "mypa:read mypa:write",
) -> dict:
    """Register an OAuth client. Returns dict with client_id + plaintext
    client_secret (only returned ONCE — store immediately).
    """
    client_id = f"mypa-{uuid.uuid4().hex[:16]}"
    client_secret = gen_secret(32)
    db.execute(
        text(
            "INSERT INTO oauth_clients (client_id, client_secret_hash, name, "
            "redirect_uris, scopes) VALUES (:cid, :hash, :name, :uris, :scopes)"
        ),
        {
            "cid": client_id,
            "hash": hash_secret(client_secret),
            "name": name,
            "uris": "\n".join(redirect_uris),
            "scopes": scopes,
        },
    )
    db.commit()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "name": name,
        "redirect_uris": redirect_uris,
        "scopes": scopes,
    }


def get_client(db: Session, client_id: str) -> dict | None:
    row = db.execute(
        text(
            "SELECT client_id, client_secret_hash, name, redirect_uris, scopes "
            "FROM oauth_clients WHERE client_id = :cid"
        ),
        {"cid": client_id},
    ).fetchone()
    if row is None:
        return None
    return {
        "client_id": row[0],
        "client_secret_hash": row[1],
        "name": row[2],
        "redirect_uris": row[3].split("\n"),
        "scopes": row[4],
    }


def authenticate_client(db: Session, client_id: str, client_secret: str) -> dict | None:
    c = get_client(db, client_id)
    if c is None:
        return None
    if not constant_time_eq(c["client_secret_hash"], hash_secret(client_secret)):
        return None
    db.execute(
        text("UPDATE oauth_clients SET last_used_at = datetime('now') WHERE client_id = :cid"),
        {"cid": client_id},
    )
    db.commit()
    return c


# ----- authorization codes ---------------------------------------------------

def issue_code(
    db: Session,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    user_subject: str,
) -> str:
    """Mint a one-time auth code valid for OAUTH_CODE_TTL_SEC seconds."""
    code = gen_secret(32)
    expires_at = _now() + timedelta(seconds=settings().oauth_code_ttl_sec)
    db.execute(
        text(
            "INSERT INTO oauth_codes (code, client_id, redirect_uri, "
            "code_challenge, code_challenge_method, scope, user_subject, expires_at) "
            "VALUES (:c, :cid, :ru, :cc, :ccm, :s, :u, :ex)"
        ),
        {
            "c": code,
            "cid": client_id,
            "ru": redirect_uri,
            "cc": code_challenge,
            "ccm": code_challenge_method,
            "s": scope,
            "u": user_subject,
            "ex": expires_at.isoformat(),
        },
    )
    db.commit()
    return code


def consume_code(
    db: Session,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict | None:
    """Validate the code, verify PKCE, mark as used. Returns the code row's
    {scope, user_subject} on success, None on any failure.
    """
    row = db.execute(
        text(
            "SELECT client_id, redirect_uri, code_challenge, code_challenge_method, "
            "scope, user_subject, expires_at, used_at "
            "FROM oauth_codes WHERE code = :c"
        ),
        {"c": code},
    ).fetchone()
    if row is None:
        return None
    if row[7] is not None:
        return None  # already used
    if row[0] != client_id:
        return None
    if row[1] != redirect_uri:
        return None
    expires_at = datetime.fromisoformat(row[6])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if _now() > expires_at:
        return None
    if not verify_pkce(code_verifier, row[2], row[3]):
        return None

    db.execute(
        text("UPDATE oauth_codes SET used_at = datetime('now') WHERE code = :c"),
        {"c": code},
    )
    db.commit()
    return {"scope": row[4], "user_subject": row[5]}


# ----- tokens ----------------------------------------------------------------

def issue_jwt(client_id: str, user_subject: str, scope: str, issuer: str) -> str:
    """Sign an access-token JWT. HS256 with OAUTH_JWT_SECRET."""
    now = int(time.time())
    payload = {
        "iss": issuer,
        "sub": user_subject,
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "exp": now + settings().oauth_access_token_ttl_sec,
        "jti": secrets.token_hex(16),
        "token_type": "access",
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def verify_jwt(token: str) -> dict | None:
    """Return claims dict if token is valid + not expired, else None."""
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def issue_refresh_token(
    db: Session, client_id: str, user_subject: str, scope: str
) -> str:
    token = gen_secret(48)
    expires_at = _now() + timedelta(seconds=settings().oauth_refresh_token_ttl_sec)
    db.execute(
        text(
            "INSERT INTO oauth_refresh_tokens (token_id, client_id, scope, "
            "user_subject, expires_at) VALUES (:t, :c, :s, :u, :e)"
        ),
        {"t": hash_secret(token), "c": client_id, "s": scope, "u": user_subject, "e": expires_at.isoformat()},
    )
    db.commit()
    return token


def consume_refresh_token(db: Session, token: str, client_id: str) -> dict | None:
    """Validate refresh, return {scope, user_subject} for issuing a new access token."""
    row = db.execute(
        text(
            "SELECT scope, user_subject, expires_at, revoked_at FROM oauth_refresh_tokens "
            "WHERE token_id = :t AND client_id = :c"
        ),
        {"t": hash_secret(token), "c": client_id},
    ).fetchone()
    if row is None or row[3] is not None:
        return None
    expires_at = datetime.fromisoformat(row[2])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if _now() > expires_at:
        return None
    return {"scope": row[0], "user_subject": row[1]}
