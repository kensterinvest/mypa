"""APScheduler-driven notification dispatcher.

Four jobs run continuously inside mypa-api:

1. dispatch_reminders — scans the `reminders` table every 60s for rows
   where fire_at <= now AND fired_at IS NULL, dispatches a push for
   each (respecting the user's `realtime` pref), marks fired_at.
   Rows that can't be delivered are closed out too (fired_at +
   last_error) so they never clog the queue.

Timestamps are compared with SQLite's julianday(), which normalizes
every stored format (naive UTC, "T" separator, "+01:00" offsets) to UTC.
Comparing raw strings is wrong: ' ' sorts before 'T'.

2. dispatch_digests — every 60s checks each user: is "now in their TZ"
   == digest_hour:XX, AND have we not already fired their digest today?
   If both true, build a digest summary and push it.

3. dispatch_overdue_weekly — same pattern, once a week on the user's
   overdue_day/overdue_hour: lists open items that are past due.

4. dispatch_expiry_alerts — at the user's digest hour, warns 30 / 7 / 1
   days before a contract, warranty, passport… ends (any item whose
   data{} has an end/expiry date — see EXPIRY_KEYS).

Repeating reminders aren't closed out after sending: fire_at moves to
the next occurrence (recurrence.py).

Both jobs are user-scoped: they pull each row's user_id, then resolve
that user's topic and prefs. No cross-tenant leak possible.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from . import notifier, recurrence
from .db import session_factory
from .settings import settings
from .timeutil import as_utc, db_ts, safe_zone


log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _user_tz(tz_name: str) -> ZoneInfo:
    return safe_zone(tz_name)


# Failed publishes are retried once per tick, then given up on.
MAX_REMINDER_ATTEMPTS = 5


def _load_prefs(prefs_raw: str | None) -> dict:
    defaults = {
        "realtime": True, "digest_enabled": True, "digest_hour": 7,
        "overdue_weekly_enabled": False, "overdue_day": 0, "overdue_hour": 9,
        "expiry_alerts": True,
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
            "SELECT r.id, r.item_id, r.user_id, r.fire_at, r.message, i.title, i.kind, "
            "r.attempts, r.repeat, r.repeat_anchor "
            "FROM reminders r LEFT JOIN items i ON r.item_id = i.id "
            "WHERE r.fired_at IS NULL AND julianday(r.fire_at) <= julianday(:now) "
            "ORDER BY julianday(r.fire_at) ASC LIMIT 100"
        ), {"now": db_ts(_now_utc())}).fetchall()
        if not rows:
            return 0

        # Cache user settings within one tick
        user_settings: dict[int, dict] = {}

        def close_out(rid: int, reason: str | None, repeat=None, anchor=None,
                      fire_at=None, user_id=None) -> None:
            """Done with this occurrence. One-off: mark fired. Repeating:
            move fire_at to the next occurrence after now."""
            if repeat:
                tz = _user_tz((user_settings.get(user_id) or {}).get("tz") or "Etc/UTC")
                try:
                    start = as_utc(datetime.fromisoformat(str(anchor or fire_at)))
                    nxt = recurrence.next_occurrence(repeat, start, _now_utc(), tz)
                except ValueError:
                    nxt = None
                if nxt is not None:
                    db.execute(text(
                        "UPDATE reminders SET fire_at = :f, attempts = 0, last_error = :e "
                        "WHERE id = :i"
                    ), {"f": db_ts(nxt), "e": reason, "i": rid})
                    return
            db.execute(text(
                "UPDATE reminders SET fired_at = :now, last_error = :e WHERE id = :i"
            ), {"now": db_ts(_now_utc()), "e": reason, "i": rid})

        for r in rows:
            rid, item_id, user_id, fire_at, msg, title, kind, attempts, repeat, anchor = r
            occurrence = dict(repeat=repeat, anchor=anchor, fire_at=fire_at, user_id=user_id)
            if user_id is None:
                close_out(rid, "skipped: no user")
                continue
            if user_id not in user_settings:
                urow = db.execute(text(
                    "SELECT tz, notify_topic, notify_prefs FROM users WHERE id = :i"
                ), {"i": user_id}).fetchone()
                user_settings[user_id] = {} if urow is None else {
                    "tz": urow[0], "topic": urow[1], "prefs": _load_prefs(urow[2]),
                }
            us = user_settings[user_id]
            if not us:
                close_out(rid, "skipped: user not found")
                continue
            if not us.get("topic"):
                close_out(rid, "skipped: no notify topic", **occurrence)
                continue
            if not us["prefs"].get("realtime", True):
                close_out(rid, "skipped: realtime notifications off", **occurrence)
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
                close_out(rid, None, **occurrence)
                fired += 1
            elif (attempts or 0) + 1 >= MAX_REMINDER_ATTEMPTS:
                close_out(rid, f"failed: publish failed {MAX_REMINDER_ATTEMPTS} times",
                          **occurrence)
                log.warning("dispatch_reminders: giving up on reminder %s", rid)
            else:
                db.execute(text(
                    "UPDATE reminders SET attempts = attempts + 1, "
                    "last_error = 'publish failed' WHERE id = :i"
                ), {"i": rid})
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
            day_start_utc = db_ts(local_day_start)
            day_end_utc = db_ts(local_day_end)

            due_today = db.execute(text(
                "SELECT count(*) FROM items WHERE user_id = :u AND status = 'open' "
                "AND due_at IS NOT NULL "
                "AND julianday(due_at) BETWEEN julianday(:a) AND julianday(:b)"
            ), {"u": uid, "a": day_start_utc, "b": day_end_utc}).scalar() or 0
            overdue = db.execute(text(
                "SELECT count(*) FROM items WHERE user_id = :u AND status = 'open' "
                "AND due_at IS NOT NULL AND julianday(due_at) < julianday(:a)"
            ), {"u": uid, "a": day_start_utc}).scalar() or 0
            events_today = db.execute(text(
                "SELECT title FROM items WHERE user_id = :u AND kind = 'event' "
                "AND due_at IS NOT NULL "
                "AND julianday(due_at) BETWEEN julianday(:a) AND julianday(:b) "
                "ORDER BY julianday(due_at) ASC LIMIT 5"
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


def _sent_today(last_sent: str | None, tz: ZoneInfo, local_day_start: datetime) -> bool:
    if not last_sent:
        return False
    try:
        dt = datetime.fromisoformat(last_sent)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz) >= local_day_start


def dispatch_overdue_weekly() -> int:
    """Weekly catch-up: on the user's overdue_day (0=Sunday..6=Saturday)
    at overdue_hour local time, push the open items that are past due.
    Nothing is sent when nothing is overdue.
    """
    sent = 0
    now_utc = _now_utc()
    SessionLocal = session_factory()
    with SessionLocal() as db:
        users = db.execute(text(
            "SELECT id, tz, notify_topic, notify_prefs, last_overdue_at "
            "FROM users WHERE disabled_at IS NULL AND notify_topic IS NOT NULL"
        )).fetchall()

        for uid, tz_name, topic, prefs_raw, last_sent in users:
            prefs = _load_prefs(prefs_raw)
            if not prefs.get("overdue_weekly_enabled"):
                continue
            tz = _user_tz(tz_name or "Etc/UTC")
            local = now_utc.astimezone(tz)
            sunday_based_weekday = (local.weekday() + 1) % 7  # Mon=0 → Sun=0
            if sunday_based_weekday != int(prefs.get("overdue_day", 0)):
                continue
            if local.hour != int(prefs.get("overdue_hour", 9)):
                continue
            local_day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            if _sent_today(last_sent, tz, local_day_start):
                continue

            rows = db.execute(text(
                "SELECT title FROM items WHERE user_id = :u AND status = 'open' "
                "AND due_at IS NOT NULL AND julianday(due_at) < julianday(:now) "
                "ORDER BY julianday(due_at) ASC"
            ), {"u": uid, "now": db_ts(now_utc)}).fetchall()
            if rows:
                titles = [r[0] for r in rows]
                shown = ", ".join(titles[:8]) + (f" +{len(titles) - 8} more" if len(titles) > 8 else "")
                ok = notifier.publish(
                    topic,
                    title=f"MyPA — {len(titles)} overdue",
                    message=shown,
                    priority=3,
                    tags=["hourglass"],
                )
                if not ok:
                    continue  # retry next tick within the hour
                sent += 1
            db.execute(text(
                "UPDATE users SET last_overdue_at = :now WHERE id = :i"
            ), {"now": now_utc.isoformat(), "i": uid})
        db.commit()
    if sent:
        log.info("dispatch_overdue_weekly: sent %d", sent)
    return sent


# data{} keys that hold an end / expiry / renewal date.
EXPIRY_KEYS = ("end", "end_date", "ends", "expires", "expires_at", "expiry",
               "expiry_date", "renew_at", "renewal_date", "valid_until")
EXPIRY_THRESHOLDS = (30, 7, 1)  # days before


def _parse_end_date(value) -> date | None:
    """'2027-05-01', '2027-05-01T…' or '2027-05' (→ 1st of month, the
    conservative reading of "ends May 2027")."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    try:
        return date.fromisoformat(v[:7] + "-01") if len(v) == 7 else None
    except ValueError:
        return None


def _snippet(body: str | None, limit: int = 140) -> str:
    """First line of prose from a markdown body (skips headings)."""
    for line in (body or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def dispatch_expiry_alerts() -> int:
    """At each user's digest hour, push "ends in N days" for open items
    whose data{} has an end date (EXPIRY_KEYS) within 30 / 7 / 1 days.
    Each threshold fires once per (item, end date); an item first seen
    inside a window gets one push, not one per threshold.
    """
    sent = 0
    now_utc = _now_utc()
    SessionLocal = session_factory()
    with SessionLocal() as db:
        users = db.execute(text(
            "SELECT id, tz, notify_topic, notify_prefs "
            "FROM users WHERE disabled_at IS NULL AND notify_topic IS NOT NULL"
        )).fetchall()
        for uid, tz_name, topic, prefs_raw in users:
            prefs = _load_prefs(prefs_raw)
            if not prefs.get("expiry_alerts", True):
                continue
            local = now_utc.astimezone(_user_tz(tz_name or "Etc/UTC"))
            if local.hour != int(prefs.get("digest_hour", 7)):
                continue
            today = local.date()
            items = db.execute(text(
                "SELECT id, kind, title, body, data FROM items "
                "WHERE user_id = :u AND status = 'open' AND data IS NOT NULL AND data != '{}'"
            ), {"u": uid}).fetchall()
            for item_id, kind, title, body, data_raw in items:
                try:
                    data = json.loads(data_raw) if isinstance(data_raw, str) else (data_raw or {})
                except json.JSONDecodeError:
                    continue
                end = next((d for d in (_parse_end_date(data.get(k)) for k in EXPIRY_KEYS) if d), None)
                if end is None:
                    continue
                days_left = (end - today).days
                due = [t for t in EXPIRY_THRESHOLDS if 0 <= days_left <= t]
                if not due:
                    continue
                already = {row[0] for row in db.execute(text(
                    "SELECT days FROM expiry_alerts WHERE item_id = :i AND end_date = :e"
                ), {"i": item_id, "e": end.isoformat()})}
                if all(t in already for t in due):
                    continue
                when = {0: "today", 1: "tomorrow"}.get(days_left, f"in {days_left} days")
                note = _snippet(body)
                ok = notifier.publish(
                    topic,
                    title=f"MyPA — {kind} ends {when}",
                    message=f"{title} (ends {end.isoformat()})" + (f"\n{note}" if note else ""),
                    priority=4 if days_left <= 7 else 3,
                    tags=["calendar"],
                )
                if not ok:
                    continue
                for t in due:
                    db.execute(text(
                        "INSERT OR IGNORE INTO expiry_alerts (item_id, end_date, days, sent_at) "
                        "VALUES (:i, :e, :d, :s)"
                    ), {"i": item_id, "e": end.isoformat(), "d": t, "s": now_utc.isoformat()})
                sent += 1
        db.commit()
    if sent:
        log.info("dispatch_expiry_alerts: sent %d", sent)
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
    sched.add_job(dispatch_overdue_weekly, IntervalTrigger(seconds=60),
                  id="dispatch_overdue_weekly", max_instances=1, coalesce=True)
    sched.add_job(dispatch_expiry_alerts, IntervalTrigger(seconds=60),
                  id="dispatch_expiry_alerts", max_instances=1, coalesce=True)
    sched.start()
    _scheduler = sched
    log.info("notification scheduler started")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
