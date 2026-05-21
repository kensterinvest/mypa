"""Day-1 smoke tests — Item insert + read roundtrip, models OK."""
from datetime import datetime, timezone

from mypa.db import Base, engine, session_factory
from mypa.models import Item, Reminder


def test_create_schema_and_roundtrip():
    eng = engine()
    Base.metadata.create_all(eng)

    Session = session_factory()
    with Session() as db:
        item = Item(
            kind="preference",
            title="Pizza",
            body="## Why\nPizza is so good. Recorded 2026-05-21.\n",
            data={"category": "food", "sentiment": "love"},
            tags="food,favorites",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.id is not None
        assert item.kind == "preference"
        assert item.data["sentiment"] == "love"
        assert item.status == "open"
        assert item.created_at is not None

    Session = session_factory()
    with Session() as db:
        fetched = db.get(Item, item.id)
        assert fetched is not None
        assert fetched.title == "Pizza"
        assert "Pizza is so good" in fetched.body


def test_reminder_cascade():
    eng = engine()
    Base.metadata.create_all(eng)

    Session = session_factory()
    with Session() as db:
        item = Item(kind="todo", title="Pick up milk", data={})
        item.reminders.append(
            Reminder(fire_at=datetime.now(timezone.utc), channel="telegram", message="Milk!")
        )
        db.add(item)
        db.commit()
        item_id = item.id

    Session = session_factory()
    with Session() as db:
        db.delete(db.get(Item, item_id))
        db.commit()
        assert db.query(Reminder).filter_by(item_id=item_id).count() == 0


def test_health_endpoint():
    """The FastAPI app should respond to /health without auth."""
    from fastapi.testclient import TestClient
    from mypa.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthenticated_request_returns_401():
    from fastapi.testclient import TestClient
    from mypa.main import app

    client = TestClient(app)
    r = client.get("/items")
    assert r.status_code == 401


def test_wrong_token_returns_401():
    from fastapi.testclient import TestClient
    from mypa.main import app

    client = TestClient(app)
    r = client.get("/items", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
