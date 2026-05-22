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

from sqlalchemy import func, select
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


def _detect_mime_from_magic(data: bytes) -> str | None:
    """Inspect the first bytes of `data` and return the MIME type implied
    by the file's magic bytes, or None if unrecognised.

    Defense against clients lying about Content-Type. We trust the bytes,
    not the header. Only checks the MIMEs we accept in ALLOWED_MIMES —
    everything else returns None and the caller rejects.

    Signatures from the libmagic database and the various format specs.
    """
    if len(data) < 12:
        return None

    # JPEG: FF D8 FF (E0/E1/E8/etc.)
    if data[:3] == b"\xFF\xD8\xFF":
        return "image/jpeg"

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # GIF: GIF87a or GIF89a
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    # WebP: RIFF....WEBP  (4 bytes RIFF, 4 bytes size, 4 bytes WEBP)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    # WAV: RIFF....WAVE
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"

    # HEIC: bytes 4-8 are 'ftyp', and bytes 8-12 indicate the brand
    # ('heic', 'heix', 'mif1', 'msf1', 'heim', 'heis', 'hevc', 'hevx', 'hevm', 'hevs')
    if data[4:8] == b"ftyp" and data[8:12] in (
        b"heic", b"heix", b"mif1", b"msf1",
        b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs",
    ):
        return "image/heic"

    # PDF: %PDF-
    if data[:5] == b"%PDF-":
        return "application/pdf"

    # OGG: OggS
    if data[:4] == b"OggS":
        return "audio/ogg"

    # MP3: 'ID3' tag at start, OR an MP3 frame sync (0xFF 0xFB/0xF3/0xF2)
    if data[:3] == b"ID3":
        return "audio/mpeg"
    if data[0] == 0xFF and data[1] in (0xFB, 0xF3, 0xF2, 0xE3):
        return "audio/mpeg"

    # WebM / Matroska: 1A 45 DF A3
    if data[:4] == b"\x1A\x45\xDF\xA3":
        return "audio/webm"

    return None


def validate_upload(
    data: bytes,
    declared_mime: str,
    *,
    user_id: int,
    db: Session,
) -> str:
    """Validate an incoming attachment body. Returns the *verified* MIME
    type (which may differ from the declared one if the bytes say so —
    we trust bytes over headers).

    Raises:
        ValueError — size cap exceeded, magic-byte mismatch, declared MIME
                     not in ALLOWED_MIMES, or quota exceeded.

    All checks are intentionally cheap and run BEFORE we touch disk.
    """
    s = settings()

    # 1. Size cap. Caddy enforces this at the proxy too — this is the
    #    application-layer belt-and-braces in case Caddy is misconfigured.
    if len(data) > s.max_upload_bytes:
        raise ValueError(
            f"upload too large: {len(data)} bytes > limit {s.max_upload_bytes}"
        )
    if len(data) == 0:
        raise ValueError("empty payload")

    # 2. Declared MIME must be in the allow-list.
    if declared_mime not in ALLOWED_MIMES:
        raise ValueError(f"mime {declared_mime!r} not allowed")

    # 3. Magic-byte detection: what the bytes actually look like.
    detected = _detect_mime_from_magic(data)
    if detected is None:
        raise ValueError(
            f"unrecognised file format — declared {declared_mime} but the bytes don't match any allowed signature"
        )
    if detected != declared_mime:
        raise ValueError(
            f"content-type mismatch: declared {declared_mime}, bytes look like {detected}"
        )

    # 4. Per-user quota. One additional SELECT — negligible cost. Defends
    #    against a compromised JWT filling the disk.
    used = db.execute(
        select(func.coalesce(func.sum(Attachment.bytes), 0))
        .where(Attachment.user_id == user_id)
    ).scalar() or 0
    if used + len(data) > s.max_user_bytes:
        raise ValueError(
            f"user quota exceeded: {used} bytes used + {len(data)} new > limit {s.max_user_bytes}"
        )

    return detected


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
    """Create an attachment row. Dedups within-user on sha256.

    Runs `validate_upload` first — size cap, magic-byte check, per-user
    quota. The verified MIME (from magic bytes) replaces the declared
    one if they match, so callers can pass the client-declared mime.
    """
    verified_mime = validate_upload(data, mime, user_id=user_id, db=db)
    mime = verified_mime

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
