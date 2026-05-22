"""RFC 6749 §10.4 — refresh token rotation + reuse detection."""
import os
os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-rotation")
os.environ.setdefault("NTFY_USER_MGMT_ENABLED", "false")

from sqlalchemy import text
from fastapi.testclient import TestClient

from mypa import users as users_lib
from mypa.db import Base, engine, session_factory
from mypa.main import app
from tests.conftest import _apply_oauth_schema


def _setup():
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    S = session_factory()
    with S() as db:
        db.execute(text(
            "INSERT OR IGNORE INTO oauth_clients "
            "(client_id, client_secret_hash, name, redirect_uris, scopes) "
            "VALUES ('dashboard', 'n/a', 'MyPA Dashboard (internal)', '', 'mypa:read mypa:write')"
        ))
        db.commit()
        users_lib.create_user(db, "u@e.com", "u-pw-1234567", name="U", is_admin=True)


def _login_and_get_tokens(client: TestClient) -> tuple[str, str]:
    r = client.post("/auth/login", json={"email": "u@e.com", "password": "u-pw-1234567"})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["refresh_token"]


def _refresh(client: TestClient, refresh_token: str):
    return client.post("/auth/refresh", json={"refresh_token": refresh_token})


def test_refresh_rotates_token():
    """Each /auth/refresh call returns a NEW refresh token; the old one
    is single-use."""
    _setup()
    client = TestClient(app)
    _, rt1 = _login_and_get_tokens(client)

    r2 = _refresh(client, rt1)
    assert r2.status_code == 200
    rt2 = r2.json()["refresh_token"]
    assert rt2 and rt2 != rt1, "refresh did not rotate"

    # New refresh works
    r3 = _refresh(client, rt2)
    assert r3.status_code == 200
    rt3 = r3.json()["refresh_token"]
    assert rt3 and rt3 != rt2


def test_refresh_reuse_revokes_family():
    """Presenting an already-used refresh token must:
       (1) reject the replay
       (2) revoke the legit successor (the family is compromised)."""
    _setup()
    client = TestClient(app)
    _, rt1 = _login_and_get_tokens(client)

    # Legit user rotates: rt1 -> rt2
    r2 = _refresh(client, rt1)
    rt2 = r2.json()["refresh_token"]

    # Attacker (or confused legit) replays rt1 — REUSE
    r_replay = _refresh(client, rt1)
    assert r_replay.status_code == 401, f"expected 401 on reuse, got {r_replay.status_code}"

    # Family should now be fully revoked — even the legitimate rt2 dies
    r_legit_after = _refresh(client, rt2)
    assert r_legit_after.status_code == 401, \
        f"legit successor should be revoked after family compromise, got {r_legit_after.status_code}"


def test_refresh_invalid_token_does_not_affect_anything():
    """A bogus token returns 401 without side-effects (doesn't reveal
    whether the token format is valid or not)."""
    _setup()
    client = TestClient(app)
    _, rt = _login_and_get_tokens(client)
    # Random garbage
    r = _refresh(client, "not-a-real-token")
    assert r.status_code == 401
    # Legit token still works
    r2 = _refresh(client, rt)
    assert r2.status_code == 200


def test_refresh_after_disable_user_is_rejected():
    """Belt-and-braces: disable_user already DELETEs refresh tokens, but
    confirm the end-to-end behaviour."""
    _setup()
    client = TestClient(app)
    _, rt = _login_and_get_tokens(client)
    S = session_factory()
    with S() as db:
        # Resolve user_id of u@e.com
        row = db.execute(text("SELECT id FROM users WHERE email='u@e.com'")).fetchone()
        users_lib.disable_user(db, row[0])
    r = _refresh(client, rt)
    assert r.status_code == 401
