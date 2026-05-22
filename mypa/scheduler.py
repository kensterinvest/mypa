"""APScheduler-driven notification dispatcher.

Two jobs run continuously inside mypa-api:

1. dispatch_reminders — scans the `reminders` table every 60s for rows
   where fire_at <= now AND fired_at IS NULL, dispatches a push for
   each (respecting the user's `realtime` pref), marks fired_at.

2. dispatch_digests — every 60s checks each user: is "now in their TZ"
   == digest_hour:XX, AND have we not already fired their digest today?
   If both true, build a digest summary and push it.

Both jobs are user-scoped: they pull each row's user_id, then resolve
that user's topic and prefs. No cross-tenant leak possible.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from . import notifier
from .db import session_factory
from .settings import settings


log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _user_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Etc/UTC")


def _load_prefs(prefs_raw: str | None) -> dict:
    defaults = {
        "realtime": True, "digest_enabled": True, "digest_hour": 7,
        "overdue_weekly_enabled": False, "overdue_day": 0, "overdue_hour": 9,
    }
    try:
        defaults.update(json.loads(prefs_raw) if prefs_raw else {})
    except json.JSONDecodeError:
        pass
    return defaults


def dispatch_reminders() -> int:
    """Fire pushes for any reminders due (fire_at <= now, not yet fired).
    Returns count fired. Skips users with realtime: false in prefs.
    """
    fired = 0
    SessionLocal = session_factory()
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT r.id, r.item_id, r.user_id, r.fire_at, r.message, i.title, i.kind "
            "FROM reminders r LEFT JOIN items i ON r.item_id = i.id "
            "WHERE r.fired_at IS NULL AND r.fire_at <= :now "
            "ORDER BY r.fire_at ASC LIMIT 100"
        ), {"now": _now_utc().isoformat()}).fetchall()
        if not rows:
            return 0

        # Cache user settings within one tick
        user_settings: dict[int, dict] = {}
        for r in rows:
            rid, item_id, user_id, fire_at, msg, title, kind = r
            if user_id is None:
                continue
            if user_id not in user_settings:
                urow = db.execute(text(
                    "SELECT tz, notify_topic, notify_prefs FROM users WHERE id = :i"
                ), {"i": user_id}).fetchone()
                if urow is None:
                    user_settings[user_id] = {}
                    continue
                user_settings[user_id] = {
                    "tz": urow[0], "topic": urow[1], "prefs": _load_prefs(urow[2]),
                }
            us = user_settings[user_id]
            if not us.get("topic"):
                continue
            if not us["prefs"].get("realtime", True):
                continue

            body = msg or f"Reminder: {title or '(no title)'}"
            ok = notifier.publish(
                us["topic"],
                title=f"MyPA — {kind or 'reminder'}",
                message=body,
                priority=4,  # high (above default 3)
                tags=["bell"],
            )
            if ok:
                db.execute(text("UPDATE reminders SET fired_at = :now WHERE id = :i"),
                           {"now": _now_utc().isoformat(), "i": rid})
                fired += 1
        db.commit()
    if fired:
        log.info("dispatch_reminders: fired %d", fired)
    return fired


def dispatch_digests() -> int:
    """For each user: if it's their digest_hour in their TZ AND they
    haven't received a digest yet today (their local day), send one.
    """
    sent = 0
    now_utc = _now_utc()
    SessionLocal = session_factory()
    with SessionLocal() as db:
        users = db.execute(text(
            "SELECT id, tz, notify_topic, notify_prefs, last_digest_at "
            "FROM users WHERE disabled_at IS NULL AND notify_topic IS NOT NULL"
        )).fetchall()

        for uid, tz_name, topic, prefs_raw, last_digest in users:
            prefs = _load_prefs(prefs_raw)
            if not prefs.get("digest_enabled", True):
                continue
            tz = _user_tz(tz_name or "Etc/UTC")
            local = now_utc.astimezone(tz)
            if local.hour != int(prefs.get("digest_hour", 7)):
                continue

            # Have we already sent a digest in this user-local day?
            local_day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            if last_digest:
                try:
                    last_dt = datetime.fromisoformat(last_digest)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt.astimezone(tz) >= local_day_start:
                        continue  # already sent today
                except ValueError:
                    pass

            # Assemble the digest
            local_day_end = local_day_start.replace(hour=23, minute=59, second=59)
            day_start_utc = local_day_start.astimezone(timezone.utc).isoformat()
            day_end_utc = local_day_end.astimezone(timezone.utc).isoformat()

            due_today = db.execute(text(
                "SELECT count(*) FROM items WHERE user_id = :u AND status = 'open' "
                "AND due_at IS NOT NULL AND due_at >= :a AND due_at <= :b"
            ), {"u": uid, "a": day_start_utc, "b": day_end_utc}).scalar() or 0
            overdue = db.execute(text(
                "SELECT count(*) FROM items WHERE user_id = :u AND status = 'open' "
                "AND due_at IS NOT NULL AND due_at < :a"
            ), {"u": uid, "a": day_start_utc}).scalar() or 0
            events_today = db.execute(text(
                "SELECT title FROM items WHERE user_id = :u AND kind = 'event' "
                "AND due_at IS NOT NULL AND due_at >= :a AND due_at <= :b "
                "ORDER BY due_at ASC LIMIT 5"
            ), {"u": uid, "a": day_start_utc, "b": day_end_utc}).fetchall()

            parts = []
            if due_today:
                parts.append(f"{due_today} due today")
            if events_today:
                names = ", ".join(t[0] for t in events_today)
                parts.append(f"events: {names}")
            if overdue:
                parts.append(f"{overdue} overdue")
            if not parts:
                parts = ["nothing scheduled — enjoy your day"]

            body = " · ".join(parts)
            title = f"MyPA — {local.strftime('%A %d %b')}"
            ok = notifier.publish(
                topic,
                title=title,
                message=body,
                priority=3,
                tags=["sunrise"],
            )
            if ok:
                db.execute(text(
                    "UPDATE users SET last_digest_at = :now WHERE id = :i"
                ), {"now": now_utc.isoformat(), "i": uid})
                sent += 1
        db.commit()
    if sent:
        log.info("dispatch_digests: sent %d", sent)
    return sent


def start_scheduler() -> BackgroundScheduler | None:
    """Boot the APScheduler with both jobs. Called from main.py lifespan.
    Idempotent — returns existing scheduler if already started.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not settings().notify_scheduler_enabled:
        log.info("notify scheduler disabled by env")
        return None

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(dispatch_reminders, IntervalTrigger(seconds=60),
                  id="dispatch_reminders", max_instances=1, coalesce=True)
    sched.add_job(dispatch_digests, IntervalTrigger(seconds=60),
                  id="dispatch_digests", max_instances=1, coalesce=True)
    sched.start()
    _scheduler = sched
    log.info("notification scheduler started")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
