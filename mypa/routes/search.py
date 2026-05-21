"""REST endpoint for /search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import service
from ..db import get_session
from ..routes.items import _to_out, _uid
from ..schemas import ItemOut

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[ItemOut])
def search(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = 20,
    db: Session = Depends(get_session),
) -> list[ItemOut]:
    return [_to_out(i) for i in service.search_items(db, q, limit=limit, user_id=_uid(request))]


@router.get("/describe", tags=["meta"])
def describe() -> dict:
    return service.describe_schema()
