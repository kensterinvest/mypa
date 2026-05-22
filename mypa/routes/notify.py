"""Per-user notification preferences + test-send endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import notifier
from .. import users as users_lib
from ..db import get_session
from ..settings import settings


router = APIRouter(tags=["notify"])


def _uid(request: Request) -> int:
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return uid


@router.get("/me/notify-prefs")
def get_prefs(request: Request, db: Session = Depends(get_session)):
    """Return the calling user's notification settings (tz, topic, prefs).
    `topic` is returned as the full subscribe URL — paste this into the
    ntfy mobile app to start receiving."""
    uid = _uid(request)
    s = users_lib.get_notify_settings(db, uid)
    if not s:
        raise HTTPException(status_code=404, detail="user not found")
    base = (settings().ntfy_base_url or "").rstrip("/")
    return {
        "tz": s["tz"],
        "topic": s["topic"],
        "subscribe_url": f"{base}/{s['topic']}" if base and s["topic"] else None,
        "prefs": s["prefs"],
    }


@router.patch("/me/notify-prefs")
def update_prefs(payload: dict, request: Request, db: Session = Depends(get_session)):
    """Partial update of notification prefs. Body fields (all optional):
       tz, realtime, digest_enabled, digest_hour, overdue_weekly_enabled,
       overdue_day, overdue_hour.
    Returns the new full settings."""
    uid = _uid(request)
    # Whitelist the keys we accept
    allowed = {"tz", "realtime", "digest_enabled", "digest_hour",
               "overdue_weekly_enabled", "overdue_day", "overdue_hour"}
    patch = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not patch:
        raise HTTPException(status_code=400, detail="no recognised fields in payload")
    # Validate digest_hour 0-23 and overdue_hour 0-23, overdue_day 0-6
    if "digest_hour" in patch and not (0 <= int(patch["digest_hour"]) <= 23):
        raise HTTPException(status_code=400, detail="digest_hour must be 0-23")
    if "overdue_hour" in patch and not (0 <= int(patch["overdue_hour"]) <= 23):
        raise HTTPException(status_code=400, detail="overdue_hour must be 0-23")
    if "overdue_day" in patch and not (0 <= int(patch["overdue_day"]) <= 6):
        raise HTTPException(status_code=400, detail="overdue_day must be 0-6 (0=Sunday)")
    try:
        result = users_lib.set_notify_prefs(db, uid, patch)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.post("/me/notify-test")
def test_notify(request: Request, db: Session = Depends(get_session)):
    """Send a test notification to the calling user's topic. Use after
    configuring the mobile app to confirm push works end-to-end."""
    uid = _uid(request)
    s = users_lib.get_notify_settings(db, uid)
    if not s or not s["topic"]:
        raise HTTPException(status_code=400, detail="no notify_topic set for user")
    ok = notifier.publish(
        s["topic"],
        title="MyPA test",
        message="If you see this, your notifications are working.",
        priority=3,
        tags=["white_check_mark"],
    )
    return {"sent": ok, "topic": s["topic"]}


@router.post("/me/notify-topic/rotate")
def rotate_topic(request: Request, db: Session = Depends(get_session)):
    """Generate a fresh random topic. Existing mobile subscribers to the
    old topic will stop receiving messages — they must re-subscribe to
    the new URL returned here."""
    uid = _uid(request)
    new_topic = users_lib.rotate_notify_topic(db, uid)
    base = (settings().ntfy_base_url or "").rstrip("/")
    return {
        "topic": new_topic,
        "subscribe_url": f"{base}/{new_topic}" if base else None,
    }
