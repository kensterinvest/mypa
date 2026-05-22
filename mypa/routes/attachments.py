"""Attachment REST endpoints — upload, retrieve, link, delete.

All routes require an authenticated user; cross-user access returns 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import attachments as att_lib
from ..db import get_session


router = APIRouter(tags=["attachments"])


def _uid(request: Request) -> int:
    """Resolve the current user_id from middleware-set state."""
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return uid


@router.post("/attachments")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    item_id: int | None = Form(default=None),
    alt_text: str | None = Form(default=None),
    db: Session = Depends(get_session),
):
    """Upload a file. Multipart form-data with field `file`. Optionally
    link to an item via `item_id`. Returns the attachment row.
    """
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
        raise HTTPException(status_code=400, detail=str(e))
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
