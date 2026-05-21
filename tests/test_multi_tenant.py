"""Per-user isolation tests.

Confirm that user A can never see / modify user B's items, even via
direct API calls."""
import os

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-mt")

from fastapi.testclient import TestClient

from mypa import users as users_lib
from mypa.db import Base, engine, session_factory
from mypa.main import app
from tests.conftest import _apply_oauth_schema


def _setup_multi_tenant():
    """Init schema + OAuth tables + create two users (alice, bob), return their IDs."""
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    # Apply migration 003 (users + user_id FK)
    from sqlalchemy import text
    from pathlib import Path
    eng = engine()
    sql = (Path(__file__).parent.parent / "migrations" / "003_users.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    with eng.begin() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                conn.execute(text(stmt))
            except Exception:
                # ALTER may have already been applied by Base.metadata.create_all
                # (since the ORM now defines user_id columns). Ignore.
                pass
    Session = session_factory()
    with Session() as db:
        alice = users_lib.create_user(db, "alice@example.com", "alice-password-123", name="Alice")
        bob = users_lib.create_user(db, "bob@example.com", "bob-password-123", name="Bob")
    return alice.id, bob.id


def test_password_hashing_roundtrip():
    h = users_lib.hash_password("hello12345")
    assert h.startswith("scrypt:")
    assert users_lib.verify_password("hello12345", h)
    assert not users_lib.verify_password("HELLO12345", h)
    assert not users_lib.verify_password("hello12346", h)


def test_users_authenticate():
    _setup_multi_tenant()
    Session = session_factory()
    with Session() as db:
        u = users_lib.authenticate(db, "alice@example.com", "alice-password-123")
        assert u is not None
        assert u.email == "alice@example.com"
        u2 = users_lib.authenticate(db, "alice@example.com", "wrong")
        assert u2 is None
        u3 = users_lib.authenticate(db, "missing@example.com", "x")
        assert u3 is None


def test_items_isolated_by_user_id_at_service_layer():
    """Service-layer scoping: alice creates items, bob can't see them."""
    from mypa import service
    from mypa.schemas import ItemCreate

    alice_id, bob_id = _setup_multi_tenant()

    Session = session_factory()
    with Session() as db:
        # Alice creates 2 items
        a1 = service.create_item(db, ItemCreate(kind="todo", title="Alice's task"), user_id=alice_id)
        a2 = service.create_item(db, ItemCreate(kind="note", title="Alice's note"), user_id=alice_id)
        # Bob creates 1 item
        b1 = service.create_item(db, ItemCreate(kind="todo", title="Bob's task"), user_id=bob_id)

        # Alice's list — only sees her own
        alice_items = service.list_items(db, user_id=alice_id)
        alice_ids = {i.id for i in alice_items}
        assert a1.id in alice_ids and a2.id in alice_ids
        assert b1.id not in alice_ids

        # Bob's list — only sees his own
        bob_items = service.list_items(db, user_id=bob_id)
        bob_ids = {i.id for i in bob_items}
        assert b1.id in bob_ids
        assert a1.id not in bob_ids and a2.id not in bob_ids

        # Alice cannot get Bob's item
        assert service.get_item(db, b1.id, user_id=alice_id) is None
        # Bob cannot delete Alice's item
        assert service.delete_item(db, a1.id, user_id=bob_id) is False
        # Alice can delete her own
        assert service.delete_item(db, a1.id, user_id=alice_id) is True


def test_search_scoped_by_user_id():
    from mypa import service
    from mypa.schemas import ItemCreate

    alice_id, bob_id = _setup_multi_tenant()
    Session = session_factory()
    with Session() as db:
        service.create_item(db, ItemCreate(kind="preference", title="Pizza",
                                            body="Alice loves pizza"), user_id=alice_id)
        service.create_item(db, ItemCreate(kind="preference", title="Pizza",
                                            body="Bob hates pizza"), user_id=bob_id)
        alice_hits = service.search_items(db, "pizza", user_id=alice_id)
        bob_hits = service.search_items(db, "pizza", user_id=bob_id)
        assert len(alice_hits) == 1 and "loves" in alice_hits[0].body
        assert len(bob_hits) == 1 and "hates" in bob_hits[0].body


def test_undo_last_scoped_by_user_id():
    from mypa import service
    from mypa.schemas import ItemCreate

    alice_id, bob_id = _setup_multi_tenant()
    Session = session_factory()
    with Session() as db:
        a1 = service.create_item(db, ItemCreate(kind="note", title="A"), user_id=alice_id)
        b1 = service.create_item(db, ItemCreate(kind="note", title="B"), user_id=bob_id)
        # Bob undoes — should remove his own (B), not Alice's (A)
        undone = service.undo_last(db, user_id=bob_id)
        assert undone is not None
        assert undone.id == b1.id
        # Alice's item still there
        assert service.get_item(db, a1.id, user_id=alice_id) is not None
