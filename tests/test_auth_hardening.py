"""v1.0 hardening — login throttle + disable_user revokes refresh tokens."""
import os
os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-hardening")
os.environ.setdefault("NTFY_USER_MGMT_ENABLED", "false")

from sqlalchemy import text
from fastapi.testclient import TestClient

from mypa import users as users_lib
from mypa.db import Base, engine, session_factory
from mypa.main import app
from tests.conftest import _apply_oauth_schema


def _setup_one_user(email: str = "alice@example.com", pw: str = "alice-pw-1234567"):
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    S = session_factory()
    with S() as db:
        # /auth/login issues refresh tokens for client_id='dashboard';
        # the synthetic row is normally added by main.py's lifespan, but
        # we don't always trigger it in tests — insert manually.
        db.execute(text(
            "INSERT OR IGNORE INTO oauth_clients "
            "(client_id, client_secret_hash, name, redirect_uris, scopes) "
            "VALUES ('dashboard', 'n/a', 'MyPA Dashboard (internal)', '', 'mypa:read mypa:write')"
        ))
        db.commit()
        return users_lib.create_user(db, email, pw, name="A", is_admin=True)


def test_login_throttle_blocks_after_5_failures():
    _setup_one_user()
    client = TestClient(app)
    # 5 wrong-password attempts → 401 each
    for i in range(5):
        r = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})
        assert r.status_code == 401, f"attempt {i+1}: got {r.status_code}"
    # 6th attempt — even with CORRECT password — should be throttled
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "alice-pw-1234567"})
    assert r.status_code == 429
    assert "too many" in r.json().get("error", "").lower()


def test_login_throttle_clears_on_success(monkeypatch):
    # Reset the in-process throttle counter so this test isn't biased by
    # the previous test's failures (the dict is module-level).
    from mypa.routes import auth_routes
    auth_routes._login_fail_log.clear()
    _setup_one_user()
    client = TestClient(app)
    # 4 fails (under threshold)
    for _ in range(4):
        client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    # Successful login clears the counter
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "alice-pw-1234567"})
    assert r.status_code == 200
    # New batch of fails should NOT have inherited the previous 4
    for i in range(4):
        r = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})
        assert r.status_code == 401, f"attempt {i+1}: got {r.status_code} (expected 401, not 429)"


def test_disable_user_revokes_refresh_tokens():
    """disable_user() must delete that user's refresh tokens so existing
    sessions can't continue past the next access-token refresh."""
    from mypa.routes import auth_routes
    auth_routes._login_fail_log.clear()
    alice = _setup_one_user()
    client = TestClient(app)
    # Log in to get a refresh token
    r = client.post("/auth/login", json={"email": "alice@example.com", "password": "alice-pw-1234567"})
    assert r.status_code == 200
    rt = r.json()["refresh_token"]
    assert rt
    # Confirm the refresh token works
    r2 = client.post("/auth/refresh", json={"refresh_token": rt})
    assert r2.status_code == 200

    # Disable Alice
    S = session_factory()
    with S() as db:
        ok = users_lib.disable_user(db, alice.id)
    assert ok is True

    # Refresh token should now be rejected
    r3 = client.post("/auth/refresh", json={"refresh_token": rt})
    assert r3.status_code == 401, f"refresh after disable: {r3.status_code} {r3.text}"


def test_disable_user_does_not_revoke_other_users_tokens():
    """Isolation check — disabling Alice must not affect Bob's session."""
    from mypa.routes import auth_routes
    auth_routes._login_fail_log.clear()
    alice = _setup_one_user("alice@example.com")
    Base.metadata.create_all(engine())
    S = session_factory()
    with S() as db:
        bob = users_lib.create_user(db, "bob@example.com", "bob-pw-1234567", name="B")

    client = TestClient(app)
    rb = client.post("/auth/login", json={"email": "bob@example.com", "password": "bob-pw-1234567"})
    bob_rt = rb.json()["refresh_token"]

    # Disable Alice
    with S() as db:
        users_lib.disable_user(db, alice.id)

    # Bob's refresh still works
    r = client.post("/auth/refresh", json={"refresh_token": bob_rt})
    assert r.status_code == 200
