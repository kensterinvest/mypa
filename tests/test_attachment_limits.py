"""Attachment size + magic-byte + quota validation tests.

Covers the protection layers added to defend against oversized uploads,
spoofed Content-Type, and disk-exhaustion via compromised JWT.
"""
import base64
import os
import tempfile
from pathlib import Path

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-limits")
os.environ.setdefault("NTFY_USER_MGMT_ENABLED", "false")
# Tight quota for the quota test — 5KB total per user
os.environ["MAX_USER_BYTES"] = "5120"
# Tight per-upload cap — 2KB
os.environ["MAX_UPLOAD_BYTES"] = "2048"
# Disable resize for these tests — they assert exact byte counts that
# resize would otherwise rewrite. (Resize is covered by test_image_resize.)
os.environ["IMAGE_RESIZE_ENABLED"] = "false"

import pytest
from sqlalchemy import text

from mypa import attachments as att_lib
from mypa import users as users_lib
from mypa.db import Base, engine, session_factory
from mypa.schemas import ItemCreate
from mypa import service, settings as settings_mod
from tests.conftest import _apply_oauth_schema


@pytest.fixture
def tmp_blob_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("BLOB_DIR", td)
        settings_mod._settings = None
        yield Path(td)


def _setup(tmp_blob_dir):
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    Session = session_factory()
    with Session() as db:
        alice = users_lib.create_user(db, "a@e.com", "alice-pw-1234567", name="A", is_admin=True)
        a_item = service.create_item(db, ItemCreate(kind="note", title="A note"), user_id=alice.id)
    return alice.id, a_item.id


# Tiny valid PNG (1x1 transparent pixel)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
# Tiny valid JPEG (1x1 white pixel — minimum valid JPEG)
JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKpgB//Z"
)


def test_magic_byte_detect_png():
    assert att_lib._detect_mime_from_magic(PNG_BYTES) == "image/png"


def test_magic_byte_detect_jpeg():
    assert att_lib._detect_mime_from_magic(JPEG_BYTES) == "image/jpeg"


def test_magic_byte_detect_unknown_returns_none():
    assert att_lib._detect_mime_from_magic(b"this is just text not an image") is None


def test_validate_rejects_mismatched_magic_bytes(tmp_blob_dir):
    """Caller declares image/png but bytes are JPEG. Must reject."""
    aid, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        with pytest.raises(ValueError, match="mismatch"):
            att_lib.validate_upload(JPEG_BYTES, "image/png", user_id=aid, db=db)


def test_validate_rejects_oversize_upload(tmp_blob_dir):
    """Single upload over MAX_UPLOAD_BYTES (set to 2048 in this test file)."""
    aid, _ = _setup(tmp_blob_dir)
    big_jpeg = JPEG_BYTES + b"\x00" * 3000   # ~3KB > 2048
    Session = session_factory()
    with Session() as db:
        with pytest.raises(ValueError, match="too large"):
            att_lib.validate_upload(big_jpeg, "image/jpeg", user_id=aid, db=db)


def test_validate_rejects_disallowed_mime(tmp_blob_dir):
    """Declared MIME not in the allow-list."""
    aid, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        with pytest.raises(ValueError, match="not allowed"):
            att_lib.validate_upload(PNG_BYTES, "image/svg+xml", user_id=aid, db=db)


def test_validate_rejects_empty(tmp_blob_dir):
    aid, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        with pytest.raises(ValueError, match="empty"):
            att_lib.validate_upload(b"", "image/png", user_id=aid, db=db)


def test_validate_rejects_garbage_with_declared_mime(tmp_blob_dir):
    """Bytes don't match ANY known magic; reject even with declared MIME."""
    aid, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        with pytest.raises(ValueError, match="unrecognised"):
            att_lib.validate_upload(b"hello world hello world", "image/png", user_id=aid, db=db)


def test_validate_accepts_valid_png(tmp_blob_dir):
    aid, _ = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        verified = att_lib.validate_upload(PNG_BYTES, "image/png", user_id=aid, db=db)
    assert verified == "image/png"


def test_per_user_quota_enforced(tmp_blob_dir):
    """MAX_USER_BYTES is 5120 (5KB) in this test. PNG is small (~70 bytes).
    Upload many; eventually quota exceeded."""
    aid, item_id = _setup(tmp_blob_dir)
    Session = session_factory()

    # Fill to just under the quota — create attachments directly with fake
    # large blobs so we don't have to use ~75 real PNGs.
    with Session() as db:
        big = JPEG_BYTES + b"\x00" * (1900 - len(JPEG_BYTES))  # ~1.9KB each
        # 1st upload: 1900 bytes — fine (under 2048 cap, well under 5120 quota)
        att1 = att_lib.create_attachment(db, user_id=aid, data=big, mime="image/jpeg", item_id=item_id)
        # 2nd: 1900 + 1900 = 3800 — still under 5120
        big2 = JPEG_BYTES + b"\x01" * (1900 - len(JPEG_BYTES))
        att2 = att_lib.create_attachment(db, user_id=aid, data=big2, mime="image/jpeg", item_id=item_id)
        # 3rd: 1900 + 1900 + 1900 = 5700 > 5120 — must reject
        big3 = JPEG_BYTES + b"\x02" * (1900 - len(JPEG_BYTES))
        with pytest.raises(ValueError, match="quota exceeded"):
            att_lib.create_attachment(db, user_id=aid, data=big3, mime="image/jpeg", item_id=item_id)


def test_create_attachment_uses_verified_mime(tmp_blob_dir):
    """Even if client declares JPEG, if bytes are PNG, the stored MIME is
    the verified PNG. But our magic-byte check raises on mismatch — so this
    test confirms the SAME magic also passes."""
    aid, item_id = _setup(tmp_blob_dir)
    Session = session_factory()
    with Session() as db:
        att = att_lib.create_attachment(
            db, user_id=aid, data=PNG_BYTES, mime="image/png", item_id=item_id,
        )
    assert att.mime == "image/png"
