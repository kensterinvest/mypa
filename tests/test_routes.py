"""Day 2 — REST routes."""
from fastapi.testclient import TestClient

from mypa.db import Base, engine
from mypa.main import app


def _client():
    Base.metadata.create_all(engine())
    return TestClient(app)


RW = {"Authorization": "Bearer test-rw-token"}
RO = {"Authorization": "Bearer test-ro-token"}


def test_create_list_get_complete_delete_flow():
    c = _client()

    # Create
    r = c.post(
        "/items",
        headers=RW,
        json={
            "kind": "preference",
            "title": "Pizza",
            "body": "Pizza is so good.",
            "data": {"category": "food", "sentiment": "love"},
            "tags": ["food"],
            "context": "User said this at lunch.",
        },
    )
    assert r.status_code == 201, r.text
    item = r.json()
    item_id = item["id"]
    assert item["kind"] == "preference"
    assert "Context" in item["body"]  # context appended under heading
    assert item["data"]["sentiment"] == "love"
    assert "food" in item["tags"]

    # Get
    r = c.get(f"/items/{item_id}", headers=RW)
    assert r.status_code == 200
    assert r.json()["id"] == item_id

    # List + filter
    r = c.get("/items?kind=preference", headers=RW)
    assert r.status_code == 200
    assert any(i["id"] == item_id for i in r.json())

    # Patch (non-decision, body may shrink freely)
    r = c.patch(f"/items/{item_id}", headers=RW, json={"body": "Shorter."})
    assert r.status_code == 200
    assert r.json()["body"] == "Shorter."

    # Complete
    r = c.post(f"/items/{item_id}/complete", headers=RW)
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None

    # Delete
    r = c.delete(f"/items/{item_id}", headers=RW)
    assert r.status_code == 204

    # Confirm gone
    r = c.get(f"/items/{item_id}", headers=RW)
    assert r.status_code == 404


def test_decision_append_only_enforced():
    c = _client()

    r = c.post(
        "/items",
        headers=RW,
        json={
            "kind": "decision",
            "title": "Bought ABC at $2",
            "body": "## Thesis\nUndervalued because X, Y, Z.\n",
            "data": {"category": "investment", "amount": 200},
        },
    )
    assert r.status_code == 201
    item_id = r.json()["id"]

    # Try to shrink body → must reject without allow_history_rewrite
    r = c.patch(f"/items/{item_id}", headers=RW, json={"body": "different"})
    assert r.status_code == 400
    assert "append-only" in r.json()["detail"]

    # Appending is fine
    new_body = r.json()  # rejected body
    original = (
        "## Thesis\nUndervalued because X, Y, Z.\n"
    )
    r = c.patch(
        f"/items/{item_id}",
        headers=RW,
        json={"body": original + "\n## Update 2026-06-01\nStill holding."},
    )
    assert r.status_code == 200
    assert "Update 2026-06-01" in r.json()["body"]

    # Override is allowed but explicit
    r = c.patch(
        f"/items/{item_id}",
        headers=RW,
        json={"body": "fully different", "allow_history_rewrite": True},
    )
    assert r.status_code == 200


def test_ro_token_can_read_but_not_write():
    c = _client()

    # Create via RW
    r = c.post(
        "/items",
        headers=RW,
        json={"kind": "note", "title": "test", "data": {}},
    )
    assert r.status_code == 201
    item_id = r.json()["id"]

    # RO can read
    r = c.get("/items", headers=RO)
    assert r.status_code == 200

    # RO can NOT write
    r = c.post("/items", headers=RO, json={"kind": "note", "title": "blocked"})
    assert r.status_code == 403


def test_search_finds_body_match():
    c = _client()
    c.post(
        "/items",
        headers=RW,
        json={
            "kind": "decision",
            "title": "Bought ABC at $2",
            "body": "Undervalued because of upcoming product launch.",
            "data": {},
        },
    )
    r = c.get("/search?q=undervalued", headers=RW)
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) >= 1


def test_describe_schema_returns_kinds():
    c = _client()
    r = c.get("/describe", headers=RW)
    assert r.status_code == 200
    kinds = r.json()["kinds"]
    assert "decision" in kinds
    assert "preference" in kinds
    assert "place" in kinds


def test_reminder_creation():
    c = _client()
    item = c.post(
        "/items",
        headers=RW,
        json={"kind": "todo", "title": "Test reminder"},
    ).json()
    r = c.post(
        f"/items/{item['id']}/reminders",
        headers=RW,
        json={"fire_at": "2026-06-01T09:00:00+00:00", "message": "Wake up"},
    )
    assert r.status_code == 200
    upc = c.get("/reminders/upcoming", headers=RW).json()
    assert any(x["item_id"] == item["id"] for x in upc)
