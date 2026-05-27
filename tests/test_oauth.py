"""OAuth 2.1 server tests — discovery, auth-code+PKCE flow, JWT validation."""
import os

# Ensure jwt secret is set before importing the app (settings is memoized)
os.environ["OAUTH_JWT_SECRET"] = "test-only-jwt-secret-for-unit-tests"

import base64
import hashlib
import secrets

from fastapi.testclient import TestClient

from mypa import oauth as oauth_lib
from mypa.db import Base, engine, session_factory
from mypa.main import app


def _client(with_admin: bool = True):
    Base.metadata.create_all(engine())
    from tests.conftest import _apply_oauth_schema
    _apply_oauth_schema()
    # Apply migration 003 (users + user_id FK) so legacy admin OAuth login works
    from sqlalchemy import text
    from pathlib import Path
    sql = (Path(__file__).parent.parent / "migrations" / "003_users.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    with engine().begin() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
    if with_admin:
        from mypa import users as users_lib
        Session = session_factory()
        with Session() as db:
            if users_lib.get_admin_user(db) is None:
                users_lib.create_user(db, "admin@example.com", "test-rw-token", is_admin=True)
    return TestClient(app)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _register_test_client(redirect_uri="https://client.example.com/cb"):
    Session = session_factory()
    with Session() as db:
        return oauth_lib.register_client(
            db, name="Test", redirect_uris=[redirect_uri]
        )


def test_discovery_returns_required_metadata():
    c = _client()
    r = c.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"]
    assert body["authorization_endpoint"].endswith("/oauth/authorize")
    assert body["token_endpoint"].endswith("/oauth/token")
    assert "S256" in body["code_challenge_methods_supported"]
    assert "authorization_code" in body["grant_types_supported"]
    assert "refresh_token" in body["grant_types_supported"]


def test_full_authorization_code_flow():
    c = _client()
    creds = _register_test_client()

    # PKCE pair
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

    # 1. GET /oauth/authorize — should render the login form
    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": creds["client_id"],
            "redirect_uri": "https://client.example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mypa:read mypa:write",
            "state": "xyz",
        },
    )
    assert r.status_code == 200
    assert "MyPA" in r.text
    assert creds["client_id"] in r.text

    # 2. POST /oauth/authorize with the password (= BEARER_TOKEN_RW)
    r = c.post(
        "/oauth/authorize",
        data={
            "client_id": creds["client_id"],
            "redirect_uri": "https://client.example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mypa:read mypa:write",
            "state": "xyz",
            "password": "test-rw-token",  # from tests/conftest.py
        },
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith("https://client.example.com/cb?")
    # Extract code from redirect query
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(loc).query)
    code = qs["code"][0]
    assert qs["state"][0] == "xyz"

    # 3. POST /oauth/token — exchange code for JWT
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://client.example.com/cb",
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"].count(".") == 2  # JWT
    assert body["refresh_token"]
    assert body["expires_in"] > 0
    access = body["access_token"]
    refresh = body["refresh_token"]

    # 4. JWT works as auth on protected endpoints
    r = c.get("/items", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200

    # 5. Code can't be reused
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://client.example.com/cb",
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert r.status_code == 400

    # 6. Refresh token works
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert new_access != access


def test_wrong_password_re_renders_form():
    c = _client()
    creds = _register_test_client()
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

    r = c.post(
        "/oauth/authorize",
        data={
            "client_id": creds["client_id"],
            "redirect_uri": "https://client.example.com/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mypa:read mypa:write",
            "state": "abc",
            "password": "wrong",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "Wrong email or password" in r.text


def test_authorize_form_escapes_injected_values():
    """Regression: the consent/login form must HTML-escape attacker-controllable
    values (stored client_name, reflected state) so no <script> executes on
    MyPA's origin. Guards against the credential-phishing XSS (P0-1)."""
    c = _client()
    Session = session_factory()
    with Session() as db:
        creds = oauth_lib.register_client(
            db,
            name="<script>alert('xss')</script>",
            redirect_uris=["https://claude.ai/cb"],
        )

    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    evil_state = '"><script>steal()</script>'

    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": creds["client_id"],
            "redirect_uri": "https://claude.ai/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mypa:read mypa:write",
            "state": evil_state,
        },
    )
    assert r.status_code == 200
    # Raw payloads must NOT appear unescaped...
    assert "<script>alert('xss')</script>" not in r.text
    assert "<script>steal()</script>" not in r.text
    # ...and their escaped forms MUST be present (proves they were rendered, escaped).
    assert "&lt;script&gt;alert(" in r.text
    assert "&lt;script&gt;steal()" in r.text


def test_register_caps_client_name_length():
    """Defense-in-depth: an over-long client_name is truncated, not stored whole."""
    c = _client()
    r = c.post(
        "/oauth/register",
        json={
            "client_name": "A" * 5000,
            "redirect_uris": ["https://claude.ai/cb"],
        },
    )
    assert r.status_code == 201
    assert len(r.json()["client_name"]) <= 200


def test_dynamic_client_registration():
    c = _client()
    r = c.post(
        "/oauth/register",
        json={
            "client_name": "ClaudeAI",
            "redirect_uris": ["https://claude.ai/cb"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"].startswith("mypa-")
    assert body["client_secret"]
    assert body["redirect_uris"] == ["https://claude.ai/cb"]
