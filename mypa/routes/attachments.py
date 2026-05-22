"""Attachment REST endpoints — upload, retrieve, link, delete.

All routes require an authenticated user; cross-user access returns 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from .. import attachments as att_lib
from ..db import get_session
from ..settings import settings


router = APIRouter(tags=["attachments"])

# Per-(user|IP) rate limiter on uploads. Tighter than the global 60/min
# because each upload can be 10MB; we don't want a single user to be
# able to churn 600 MB/min through the API.
def _rate_key(request: Request) -> str:
    """Key by user_id when authenticated, fall back to IP."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return f"user:{uid}"
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or get_remote_address(request)


_upload_limiter = Limiter(key_func=_rate_key)


def _uid(request: Request) -> int:
    """Resolve the current user_id from middleware-set state."""
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return uid


def _check_content_length(request: Request) -> None:
    """Pre-flight check: reject obvious oversize uploads before we even
    read the body. Caddy's `request_body max_size` is the canonical
    line of defense; this is belt-and-braces for direct API calls."""
    cl = request.headers.get("content-length")
    if cl is None:
        return  # streaming/chunked — let downstream code catch it
    try:
        n = int(cl)
    except ValueError:
        return
    limit = settings().max_upload_bytes
    if n > limit:
        raise HTTPException(
            status_code=413,
            detail=f"upload too large: {n} bytes (max {limit})",
        )


@router.post("/attachments")
@_upload_limiter.limit(lambda: settings().attachment_rate_limit)
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    item_id: int | None = Form(default=None),
    alt_text: str | None = Form(default=None),
    db: Session = Depends(get_session),
):
    """Upload a file. Multipart form-data with field `file`. Optionally
    link to an item via `item_id`. Returns the attachment row.

    Protection layers (defense in depth):
      1. Caddy `request_body max_size 10MB` — proxy-level cap
      2. `_check_content_length` — rejects oversize Content-Length here
      3. Per-user/IP rate limit (default 20/hour)
      4. `validate_upload` inside `create_attachment` — magic-byte check
         + final size cap + per-user quota
    """
    _check_content_length(request)
    uid = _uid(request)
    data = await file.read()
    mime = file.content_type or "application/octet-stream"

    try:
        att = att_lib.create_attachment(
            db,
            user_id=uid,
            data=data,
            mime=mime,
            item_id=item_id,
            alt_text=alt_text,
        )
    except ValueError as e:
        # validate_upload raises ValueError for size, magic-mismatch,
        # quota. 413 for size-related, 415 for magic, 400 for the rest.
        msg = str(e)
        if "too large" in msg or "quota exceeded" in msg:
            raise HTTPException(status_code=413, detail=msg)
        if "mismatch" in msg or "not allowed" in msg or "unrecognised" in msg:
            raise HTTPException(status_code=415, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {
        "id": att.id,
        "item_id": att.item_id,
        "sha256": att.sha256,
        "mime": att.mime,
        "bytes": att.bytes,
        "alt_text": att.alt_text,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


@router.get("/attachments/{attachment_id}")
def get_attachment_file(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    """Return the raw bytes with the stored Content-Type."""
    uid = _uid(request)
    att = att_lib.get_attachment(db, attachment_id, user_id=uid)
    if att is None:
        raise HTTPException(status_code=404, detail="not found")
    data = att_lib.read_attachment_bytes(att)
    # Use Content-Disposition: attachment (NOT inline) — user-uploaded
    # bytes served inline are an XSS class if a browser ever MIME-sniffs,
    # or if ALLOWED_MIMES is later widened to include SVG/HTML. Forcing
    # download eliminates the class. The dashboard fetches as a blob and
    # renders client-side via createObjectURL, so this doesn't break it.
    return Response(
        content=data,
        media_type=att.mime,
        headers={
            "Content-Disposition": f'attachment; filename="{att.sha256[:12]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/attachments/{attachment_id}/meta")
def get_attachment_meta(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    """Metadata only — same response shape as POST /attachments."""
    uid = _uid(request)
    att = att_lib.get_attachment(db, attachment_id, user_id=uid)
    if att is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": att.id,
        "item_id": att.item_id,
        "sha256": att.sha256,
        "mime": att.mime,
        "bytes": att.bytes,
        "alt_text": att.alt_text,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


@router.post("/items/{item_id}/attachments/{attachment_id}")
def link_attachment(
    item_id: int,
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    """Link an already-uploaded attachment to an item. Both must belong to user."""
    uid = _uid(request)
    att = att_lib.link_to_item(db, attachment_id=attachment_id, item_id=item_id, user_id=uid)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment or item not found")
    return {"id": att.id, "item_id": att.item_id}


@router.get("/items/{item_id}/attachments")
def list_item_attachments(
    item_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    """List attachments linked to an item."""
    uid = _uid(request)
    rows = att_lib.list_attachments_for_item(db, item_id, user_id=uid)
    return [
        {
            "id": a.id,
            "sha256": a.sha256,
            "mime": a.mime,
            "bytes": a.bytes,
            "alt_text": a.alt_text,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    """Delete attachment row + GC blob if no other refs."""
    uid = _uid(request)
    ok = att_lib.delete_attachment(db, attachment_id, user_id=uid)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}
