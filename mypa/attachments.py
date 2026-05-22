"""Attachment storage helper + service layer.

Content-addressed on-disk storage: BLOB_DIR/YYYY/MM/<sha256>.<ext>.
The DB row is just an index pointing at the blob. Identical bytes
uploaded twice by the same user dedup (UNIQUE(user_id, sha256));
different users uploading the same bytes still get distinct rows but
share the same physical file — which is fine because they each have
their own pointer and the GC only removes a blob when no rows point
at it.

This module is the *service layer*. REST and MCP both call into here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attachment, Item
from .settings import settings


# Per RFC 6838, but pragmatic — we only accept what we have a story for.
ALLOWED_MIMES = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "application/pdf",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
})


def _ext_for_mime(mime: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "application/pdf": ".pdf",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/webm": ".webm",
    }.get(mime, ".bin")


def _blob_dir() -> Path:
    return Path(settings().blob_dir)


def _disk_path_for(sha256: str, mime: str, created: datetime | None = None) -> Path:
    """Compute the on-disk path for a blob.

    Layout: BLOB_DIR/YYYY/MM/<sha256><ext>. Partitioning by year-month
    keeps any single directory under a few hundred files even at heavy
    use, which matters for filesystem listing cost.
    """
    when = created or datetime.now(timezone.utc)
    sub = f"{when.year:04d}/{when.month:02d}"
    return _blob_dir() / sub / f"{sha256}{_ext_for_mime(mime)}"


def store_blob(data: bytes, mime: str) -> tuple[str, Path]:
    """Write bytes to disk, returning (sha256, full_path).

    Idempotent: if a blob with the same sha256 already exists at the
    computed path, we don't rewrite — saves IO on dedup.
    """
    sha = hashlib.sha256(data).hexdigest()
    path = _disk_path_for(sha, mime)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return sha, path


def create_attachment(
    db: Session,
    *,
    user_id: int,
    data: bytes,
    mime: str,
    item_id: int | None = None,
    alt_text: str | None = None,
) -> Attachment:
    """Create an attachment row. Dedups within-user on sha256."""
    if mime not in ALLOWED_MIMES:
        raise ValueError(f"mime {mime!r} not allowed (see ALLOWED_MIMES)")
    if len(data) == 0:
        raise ValueError("empty payload")

    sha, full_path = store_blob(data, mime)
    rel_path = str(full_path.relative_to(_blob_dir()))

    # Dedup: if this user already uploaded these exact bytes, return the
    # existing row rather than creating a duplicate.
    existing = db.execute(
        select(Attachment).where(
            Attachment.user_id == user_id,
            Attachment.sha256 == sha,
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Optionally re-link to a different item if one is now specified.
        if item_id is not None and existing.item_id != item_id:
            existing.item_id = item_id
        if alt_text and not existing.alt_text:
            existing.alt_text = alt_text
        db.commit()
        db.refresh(existing)
        return existing

    # If item_id given, validate the user owns it before linking.
    if item_id is not None:
        owner = db.get(Item, item_id)
        if owner is None or owner.user_id != user_id:
            raise PermissionError("item does not belong to user")

    att = Attachment(
        user_id=user_id,
        item_id=item_id,
        sha256=sha,
        mime=mime,
        bytes=len(data),
        path=rel_path,
        alt_text=alt_text,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def get_attachment(db: Session, attachment_id: int, *, user_id: int) -> Attachment | None:
    """Fetch an attachment row scoped to user. Returns None on cross-user."""
    att = db.get(Attachment, attachment_id)
    if att is None or att.user_id != user_id:
        return None
    return att


def read_attachment_bytes(att: Attachment) -> bytes:
    """Read the on-disk bytes for an attachment."""
    full = _blob_dir() / att.path
    return full.read_bytes()


def link_to_item(db: Session, *, attachment_id: int, item_id: int, user_id: int) -> Attachment | None:
    """Link an existing attachment to an item. Both must belong to user."""
    att = get_attachment(db, attachment_id, user_id=user_id)
    if att is None:
        return None
    owner = db.get(Item, item_id)
    if owner is None or owner.user_id != user_id:
        return None
    att.item_id = item_id
    db.commit()
    db.refresh(att)
    return att


def delete_attachment(db: Session, attachment_id: int, *, user_id: int) -> bool:
    """Delete an attachment row. GC the on-disk blob only if no other row
    (across all users) still references the same sha256."""
    att = get_attachment(db, attachment_id, user_id=user_id)
    if att is None:
        return False

    sha = att.sha256
    full_path = _blob_dir() / att.path
    db.delete(att)
    db.commit()

    still_referenced = db.execute(
        select(Attachment.id).where(Attachment.sha256 == sha).limit(1)
    ).first()
    if not still_referenced and full_path.exists():
        full_path.unlink()
    return True


def list_attachments_for_item(db: Session, item_id: int, *, user_id: int) -> list[Attachment]:
    """All attachments linked to an item, scoped to user."""
    item = db.get(Item, item_id)
    if item is None or item.user_id != user_id:
        return []
    return list(db.execute(
        select(Attachment)
        .where(Attachment.item_id == item_id, Attachment.user_id == user_id)
        .order_by(Attachment.created_at)
    ).scalars())
