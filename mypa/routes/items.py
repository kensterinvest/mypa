"""REST endpoints for /items."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import service
from ..db import get_session
from ..schemas import ItemCreate, ItemOut, ItemPatch


def _uid(request: Request) -> int | None:
    return getattr(request.state, "user_id", None)

router = APIRouter(prefix="/items", tags=["items"])


def _to_out(item) -> ItemOut:
    return ItemOut.model_validate(
        {
            "id": item.id,
            "kind": item.kind,
            "title": item.title,
            "body": item.body,
            "status": item.status,
            "priority": item.priority,
            "due_at": item.due_at,
            "tags": service._str_to_tags(item.tags),
            "data": item.data or {},
            "source": item.source,
            "source_ref": item.source_ref,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "completed_at": item.completed_at,
        }
    )


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def post_item(payload: ItemCreate, request: Request, db: Session = Depends(get_session)) -> ItemOut:
    try:
        item = service.create_item(db, payload, user_id=_uid(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_out(item)


@router.get("", response_model=list[ItemOut])
def list_items(
    request: Request,
    kind: str | None = None,
    status_filter: str | None = None,
    due_before: datetime | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_session),
) -> list[ItemOut]:
    items = service.list_items(
        db, kind=kind, status=status_filter, due_before=due_before, tag=tag,
        limit=limit, offset=offset, user_id=_uid(request),
    )
    return [_to_out(i) for i in items]


@router.get("/{item_id}", response_model=ItemOut)
def get_item_by_id(item_id: int, request: Request, db: Session = Depends(get_session)) -> ItemOut:
    item = service.get_item(db, item_id, user_id=_uid(request))
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return _to_out(item)


@router.patch("/{item_id}", response_model=ItemOut)
def patch_item(item_id: int, patch: ItemPatch, request: Request,
               db: Session = Depends(get_session)) -> ItemOut:
    try:
        item = service.update_item(db, item_id, patch, user_id=_uid(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return _to_out(item)


@router.post("/{item_id}/complete", response_model=ItemOut)
def complete(item_id: int, request: Request, db: Session = Depends(get_session)) -> ItemOut:
    item = service.complete_item(db, item_id, user_id=_uid(request))
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return _to_out(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item_by_id(item_id: int, request: Request, db: Session = Depends(get_session)) -> None:
    deleted = service.delete_item(db, item_id, user_id=_uid(request))
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")
