"""REST endpoints for reminders."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import service
from ..db import get_session
from ..schemas import ReminderCreate, ReminderOut

router = APIRouter(tags=["reminders"])


@router.post("/items/{item_id}/reminders", response_model=ReminderOut)
def add_reminder(
    item_id: int, payload: ReminderCreate, db: Session = Depends(get_session)
) -> ReminderOut:
    r = service.add_reminder(
        db, item_id=item_id, fire_at=payload.fire_at,
        message=payload.message, channel=payload.channel,
    )
    if r is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ReminderOut.model_validate(r, from_attributes=True)


@router.get("/reminders/upcoming", response_model=list[ReminderOut])
def upcoming(limit: int = 20, db: Session = Depends(get_session)) -> list[ReminderOut]:
    return [
        ReminderOut.model_validate(r, from_attributes=True)
        for r in service.upcoming_reminders(db, limit=limit)
    ]
