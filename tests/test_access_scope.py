"""Access hardening (roadmap item 2): read-only tokens can't write via MCP,
unresolvable users fail closed, ownerless rows aren't visible."""
from fastapi.testclient import TestClient

from mypa import mcp_server as mcp_mod
from mypa import service
from mypa.audit import set_request_context
from mypa.db import Base, engine, session_factory
from mypa.main import app
from mypa.schemas import ItemCreate
from tests.conftest import make_admin

WRITE_CALLS = {
    "pa_add": lambda: mcp_mod.pa_add(kind="note", title="x"),
    "pa_update": lambda: mcp_mod.pa_update(1, title="y"),
    "pa_complete": lambda: mcp_mod.pa_complete(1),
    "pa_delete": lambda: mcp_mod.pa_delete(1, confirm=True),
    "pa_undo_last": lambda: mcp_mod.pa_undo_last(),
    "pa_add_reminder": lambda: mcp_mod.pa_add_reminder(1, "2030-01-01T09:00:00+00:00"),
    "pa_set_notify_prefs": lambda: mcp_mod.pa_set_notify_prefs(realtime=False),
}


def test_read_only_scope_blocks_every_mcp_write():
    uid = make_admin()
    with session_factory()() as db:
        service.create_item(db, ItemCreate(kind="note", title="keep"), user_id=uid)
    set_request_context("ip", "ro", user_id=uid)
    for name, call in WRITE_CALLS.items():
        r = call()
        assert "read-only" in r.get("error", ""), name
    # Reads still work, and nothing was changed
    items = mcp_mod.pa_list()["items"]
    assert [i["title"] for i in items] == ["keep"]


def test_rest_rejects_token_with_no_user():
    Base.metadata.create_all(engine())  # no admin user exists
    r = TestClient(app).get("/items", headers={"Authorization": "Bearer test-rw-token"})
    assert r.status_code == 403
    assert "no MyPA user" in r.json()["detail"]


def test_mcp_rejects_token_with_no_user():
    Base.metadata.create_all(engine())
    r = TestClient(mcp_mod.app, base_url="http://localhost").post(
        "/mcp", json={}, headers={"Authorization": "Bearer test-rw-token"})
    assert r.status_code == 403


def test_ownerless_rows_hidden_from_users():
    uid = make_admin()
    with session_factory()() as db:
        orphan = service.create_item(db, ItemCreate(kind="note", title="orphan"), user_id=None)
        assert service.get_item(db, orphan.id, user_id=uid) is None
