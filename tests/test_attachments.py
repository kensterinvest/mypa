"""Phase 3 — attachments storage + isolation tests.

Covers the service layer, REST endpoints, and MCP user_id propagation.
"""
import base64
import os
import tempfile
from pathlib import Path

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-att")

import pytest
from fastapi.testclient import TestClient

from mypa import attachments as att_lib
from mypa import users as users_lib
from mypa.audit import set_request_context
from mypa.db import Base, engine, session_factory
from mypa.main import app
from mypa.schemas import ItemCreate
from mypa import service
from tests.conftest import _apply_oauth_schema


@pytest.fixture
def tmp_blob_dir(monkeypatch):
    """Redirect BLOB_DIR to a tempdir so tests don't touch /var/lib."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("BLOB_DIR", td)
        # Force settings re-read
        from mypa import settings as settings_mod
        settings_mod._settings = None
        yield Path(td)


def _setup(tmp_blob_dir):
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    # Apply 003_users.sql for the FK table (Attachment FKs users.id)
    from sqlalchemy import text
    from pathlib import Path as P
    sql = (P(__file__).parent.parent / "migrations" / "003_users.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    with engine().begin() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
    Session = session_factory()
    with Session() as db:
        # Make alice the admin so the static BEARER_TOKEN_RW maps to her in
        # the REST test below (resolve_admin_user_id() returns the first admin).
        alice = users_lib.create_user(db, "a@example.com", "a-pw-1234567", name="A", is_admin=True)
        bob = users_lib.create_user(db, "b@example.com", "b-pw-1234567", name="B")
        a_item = service.create_item(db, ItemCreate(kind="note", title="A's note"), user_id=alice.id)
        b_item = service.create_item(db, ItemCreate(kind="note", title="B's note"), user_id=bob.id)
    return alice.id, bob.id, a_item.id, b_item.id


# Tiny valid PNG (1x1 transparent pixel)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def test_create_and_retrieve_attachment(tmp_blob_dir):
    alice_id, _, a_item_id, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        att = att_lib.create_attachment(
            db, user_id=alice_id, data=PNG_BYTES, mime="image/png",
            item_id=a_item_id, alt_text="test pixel",
        )
        assert att.id > 0
        assert att.bytes == len(PNG_BYTES)
        assert att.mime == "image/png"
        # On-disk path should exist
        full = tmp_blob_dir / att.path
        assert full.is_file()
        # Read-back via service
        retrieved = att_lib.get_attachment(db, att.id, user_id=alice_id)
        assert retrieved is not None
        assert att_lib.read_attachment_bytes(retrieved) == PNG_BYTES


def test_dedup_within_user(tmp_blob_dir):
    alice_id, _, a_item_id, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        a1 = att_lib.create_attachment(db, user_id=alice_id, data=PNG_BYTES, mime="image/png", item_id=a_item_id)
        a2 = att_lib.create_attachment(db, user_id=alice_id, data=PNG_BYTES, mime="image/png", item_id=a_item_id)
        assert a1.id == a2.id  # same row, dedup'd


def test_cross_user_isolation(tmp_blob_dir):
    alice_id, bob_id, a_item_id, b_item_id = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        a_att = att_lib.create_attachment(db, user_id=alice_id, data=PNG_BYTES, mime="image/png", item_id=a_item_id)
        # Bob cannot fetch Alice's attachment
        assert att_lib.get_attachment(db, a_att.id, user_id=bob_id) is None
        # Bob cannot delete Alice's attachment
        assert att_lib.delete_attachment(db, a_att.id, user_id=bob_id) is False
        # Alice still has it
        assert att_lib.get_attachment(db, a_att.id, user_id=alice_id) is not None


def test_cannot_link_to_other_users_item(tmp_blob_dir):
    alice_id, bob_id, a_item_id, b_item_id = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        with pytest.raises(PermissionError):
            att_lib.create_attachment(
                db, user_id=alice_id, data=PNG_BYTES, mime="image/png",
                item_id=b_item_id,  # Bob's item — must fail
            )


def test_delete_gcs_blob_when_last_ref_removed(tmp_blob_dir):
    alice_id, _, a_item_id, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        att = att_lib.create_attachment(db, user_id=alice_id, data=PNG_BYTES, mime="image/png", item_id=a_item_id)
        full = tmp_blob_dir / att.path
        assert full.is_file()
        att_lib.delete_attachment(db, att.id, user_id=alice_id)
        assert not full.exists()


def test_rest_upload_and_retrieve(tmp_blob_dir):
    alice_id, _, a_item_id, _ = _setup(tmp_blob_dir)
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-rw-token"}
    # Static RW token currently maps to admin (alice in this setup is id=1 if first user)
    r = client.post(
        "/attachments",
        headers=headers,
        files={"file": ("p.png", PNG_BYTES, "image/png")},
        data={"item_id": str(a_item_id), "alt_text": "via REST"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mime"] == "image/png"
    assert body["bytes"] == len(PNG_BYTES)
    aid = body["id"]
    # Retrieve the file
    r2 = client.get(f"/attachments/{aid}", headers=headers)
    assert r2.status_code == 200
    assert r2.content == PNG_BYTES
    assert r2.headers["content-type"].startswith("image/png")


def test_mcp_user_id_propagation_isolates_pa_get(tmp_blob_dir):
    """Confirm the contextvar fix: setting user_id via set_request_context
    causes MCP tools to scope by user. Previously pa_get returned any
    item across all users."""
    alice_id, bob_id, a_item_id, b_item_id = _setup(tmp_blob_dir)
    from mypa.mcp_server import pa_get

    # Simulate Alice's request context
    set_request_context("test-ip", "rw", user_id=alice_id)
    # Alice can see her own item
    own = pa_get.fn(a_item_id) if hasattr(pa_get, "fn") else pa_get(a_item_id)
    assert "error" not in own
    assert own["id"] == a_item_id
    # Alice cannot see Bob's item — must return error not the actual item
    others = pa_get.fn(b_item_id) if hasattr(pa_get, "fn") else pa_get(b_item_id)
    assert "error" in others, f"cross-tenant access: {others}"
