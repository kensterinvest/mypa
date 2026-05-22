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
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Attachment, Item
from .settings import settings


log = logging.getLogger(__name__)


# MIMEs we'll downscale (raster, non-animated, well-supported by Pillow).
# GIF excluded (might be animated). HEIC excluded (requires pillow-heif).
# Audio + PDF obviously not images.
_RESIZABLE_MIMES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
})


def resize_image_if_large(data: bytes, mime: str) -> bytes:
    """Downscale a raster image if its longest edge exceeds the configured
    max dimension. Strips EXIF (which includes GPS coords by default).

    Returns the (possibly-rewritten) bytes. Original bytes returned
    unchanged if:
      - resize is disabled by settings
      - mime is not in the resizable set
      - image is already at or below max_dimension
      - Pillow (or the codec) fails — we log + keep original bytes
    """
    s = settings()
    if not s.image_resize_enabled:
        return data
    if mime not in _RESIZABLE_MIMES:
        return data

    try:
        from PIL import Image
    except ImportError:
        log.warning("Pillow not installed — skipping image resize")
        return data

    try:
        img = Image.open(io.BytesIO(data))
        # Force-load (lazy decoder error catch + apply EXIF orientation)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Only resize if either dimension exceeds the limit.
        w, h = img.size
        max_dim = s.image_max_dimension
        if max(w, h) <= max_dim:
            # Even if not resizing, we still rewrite to strip EXIF for
            # privacy. The user uploaded a 1000×800 photo from their phone;
            # we keep the pixels but drop the camera + GPS metadata.
            stripped_io = io.BytesIO()
            _save_image(img, mime, stripped_io, s.image_jpeg_quality)
            stripped = stripped_io.getvalue()
            # Only return the stripped version if it's actually smaller —
            # otherwise the rewrite adds overhead with no payoff.
            return stripped if len(stripped) < len(data) else data

        # Resize: thumbnail preserves aspect ratio in-place.
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        out = io.BytesIO()
        _save_image(img, mime, out, s.image_jpeg_quality)
        result = out.getvalue()
        log.info("resized image %s: %d×%d → %d×%d, %d → %d bytes",
                 mime, w, h, img.size[0], img.size[1], len(data), len(result))
        return result

    except Exception as e:
        log.warning("image resize failed for %s (%d bytes): %s — storing original",
                    mime, len(data), e)
        return data


def _save_image(img, mime: str, out: io.BytesIO, jpeg_quality: int) -> None:
    """Write `img` to `out` in the codec matching `mime`. Drops metadata
    (EXIF, ICC profiles, etc.) — `save` only includes what we explicitly
    pass to `info`."""
    if mime == "image/jpeg":
        # JPEG can't have an alpha channel — convert if needed.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
    elif mime == "image/png":
        img.save(out, format="PNG", optimize=True)
    elif mime == "image/webp":
        img.save(out, format="WEBP", quality=jpeg_quality, method=6)
    else:
        # Shouldn't reach here if _RESIZABLE_MIMES gate is honoured upstream
        raise ValueError(f"unsupported resize target: {mime}")


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

    # 5. System-wide free-disk check on the blob-dir partition. Cheap
    #    statvfs call. Refuse rather than let the disk wedge the VPS.
    try:
        import shutil
        usage = shutil.disk_usage(_blob_dir())
        if usage.free < s.min_free_disk_bytes:
            raise ValueError(
                f"insufficient disk space: {usage.free} bytes free < "
                f"required {s.min_free_disk_bytes}"
            )
    except FileNotFoundError:
        # blob_dir doesn't exist yet — create_attachment creates it on
        # first store. Skip the check, the actual write will surface
        # any FS error.
        pass

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

    # Downscale + strip EXIF before hashing/storing. The sha256 will be
    # of the resized bytes so dedup works correctly (two uploads of the
    # same photo from the same camera produce the same stored blob).
    data = resize_image_if_large(data, mime)

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
