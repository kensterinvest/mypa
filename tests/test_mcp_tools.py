"""Tests for the expanded MCP tool surface (pa_delete, pa_update, pa_complete, pa_add_reminder)."""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt")

from mypa.db import Base, engine
from mypa import mcp_server as mcp_mod
from mypa import service
from mypa.schemas import ItemCreate
from mypa.db import session_factory


def _setup():
    Base.metadata.create_all(engine())
    Session = session_factory()
    with Session() as db:
        item = service.create_item(
            db,
            ItemCreate(kind="todo", title="Test task", data={}),
        )
        return item.id


def test_pa_delete_requires_confirm():
    iid = _setup()
    r = mcp_mod.pa_delete(iid, confirm=False)
    assert "error" in r
    assert "confirm" in r["error"]
    # Still there
    assert mcp_mod.pa_get(iid)["id"] == iid


def test_pa_delete_with_confirm():
    iid = _setup()
    r = mcp_mod.pa_delete(iid, confirm=True)
    assert r["deleted_id"] == iid
    # Gone
    g = mcp_mod.pa_get(iid)
    assert "error" in g


def test_pa_delete_missing_item():
    Base.metadata.create_all(engine())
    r = mcp_mod.pa_delete(99999, confirm=True)
    assert "error" in r


def test_pa_update_title_and_body():
    iid = _setup()
    r = mcp_mod.pa_update(iid, title="Updated", body="New body content")
    assert r["title"] == "Updated"
    assert r["body"] == "New body content"


def test_pa_update_decision_append_only():
    Base.metadata.create_all(engine())
    Session = session_factory()
    with Session() as db:
        item = service.create_item(
            db,
            ItemCreate(
                kind="decision",
                title="Buy ABC",
                body="## Thesis\nUndervalued because X.",
                data={"amount": 100},
            ),
        )
        iid = item.id
    # Append to body — substring still present → OK
    r = mcp_mod.pa_update(
        iid, body="## Thesis\nUndervalued because X.\n\n## Update 2026-06-01\nStill holding."
    )
    assert "error" not in r
    # Shrink body without override — rejected
    r2 = mcp_mod.pa_update(iid, body="Completely different.")
    assert "error" in r2
    assert "append-only" in r2["error"]
    # Shrink with override — allowed
    r3 = mcp_mod.pa_update(iid, body="Completely different.", allow_history_rewrite=True)
    assert "error" not in r3


def test_pa_complete():
    iid = _setup()
    r = mcp_mod.pa_complete(iid)
    assert r["status"] == "done"
    assert r["completed_at"] is not None


def test_pa_add_reminder():
    iid = _setup()
    fire = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = mcp_mod.pa_add_reminder(iid, fire_at=fire, message="Test!")
    assert r["item_id"] == iid
    assert r["channel"] == "telegram"
    assert "Telegram delivery worker not yet active" in r["note"]


def test_pa_add_reminder_missing_item():
    Base.metadata.create_all(engine())
    fire = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = mcp_mod.pa_add_reminder(99999, fire_at=fire)
    assert "error" in r
