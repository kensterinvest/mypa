"""Reminder timing + queue health (roadmap item 1).

Regressions covered:
- UTC offsets were dropped on save (15:30+01:00 stored as 15:30 → 1h late)
- scheduler string-compared ' '-separated DB values against 'T' isoformat
  strings, so a reminder became "due" at 00:00 UTC on its date
- skipped/failed reminders were never closed out and clogged the queue
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch as mock_patch

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-notify")
os.environ.setdefault("NTFY_BASE_URL", "https://ntfy.example.invalid")

from sqlalchemy import text

from mypa import scheduler as sched_mod
from mypa import service
from mypa import users as users_lib
from mypa.db import session_factory
from mypa.schemas import ItemCreate
from mypa.timeutil import as_utc
from tests.test_notifications import _setup

UTC = timezone.utc


def _item(db, uid, **kw):
    return service.create_item(db, ItemCreate(kind="todo", title="t", **kw), user_id=uid)


def _reminder_row(db, rid):
    return db.execute(text(
        "SELECT fired_at, attempts, last_error FROM reminders WHERE id = :i"
    ), {"i": rid}).fetchone()


def test_offset_is_preserved_on_save():
    aid, _ = _setup()
    with session_factory()() as db:
        it = _item(db, aid)
        fire = datetime(2030, 5, 22, 15, 30, tzinfo=timezone(timedelta(hours=1)))
        r = service.add_reminder(db, it.id, fire, user_id=aid)
        db.refresh(r)
        assert as_utc(r.fire_at) == datetime(2030, 5, 22, 14, 30, tzinfo=UTC)

        it2 = _item(db, aid, due_at=fire)
        db.refresh(it2)
        assert as_utc(it2.due_at) == datetime(2030, 5, 22, 14, 30, tzinfo=UTC)


def test_naive_input_is_user_local_time():
    aid, _ = _setup()  # alice is Europe/London (BST = UTC+1 in May)
    with session_factory()() as db:
        it = _item(db, aid, due_at=datetime(2030, 5, 22, 15, 30))
        db.refresh(it)
        assert as_utc(it.due_at) == datetime(2030, 5, 22, 14, 30, tzinfo=UTC)


def test_reminder_later_today_does_not_fire_early():
    aid, _ = _setup()
    with session_factory()() as db:
        it = _item(db, aid)
        r = service.add_reminder(db, it.id, datetime.now(UTC) + timedelta(hours=3), user_id=aid)
        rid = r.id
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        assert sched_mod.dispatch_reminders() == 0
    assert pub.call_count == 0
    with session_factory()() as db:
        assert _reminder_row(db, rid)[0] is None


def test_due_reminder_fires_via_service_path():
    aid, _ = _setup()
    with session_factory()() as db:
        it = _item(db, aid)
        service.add_reminder(db, it.id, datetime.now(UTC) - timedelta(minutes=1), user_id=aid)
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        assert sched_mod.dispatch_reminders() == 1
    assert pub.call_count == 1


def test_skipped_reminder_is_closed_out_not_replayed():
    aid, _ = _setup()
    with session_factory()() as db:
        users_lib.set_notify_prefs(db, aid, {"realtime": False})
        it = _item(db, aid)
        rid = service.add_reminder(db, it.id, datetime.now(UTC) - timedelta(minutes=1),
                                   user_id=aid).id
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_reminders()
    assert pub.call_count == 0
    with session_factory()() as db:
        fired_at, _, err = _reminder_row(db, rid)
        assert fired_at is not None and err.startswith("skipped")
        # Turning realtime back on must not replay the backlog
        users_lib.set_notify_prefs(db, aid, {"realtime": True})
    with mock_patch("mypa.notifier.publish", return_value=True) as pub2:
        sched_mod.dispatch_reminders()
    assert pub2.call_count == 0


def test_failed_publish_retries_then_gives_up():
    aid, _ = _setup()
    with session_factory()() as db:
        it = _item(db, aid)
        rid = service.add_reminder(db, it.id, datetime.now(UTC) - timedelta(minutes=1),
                                   user_id=aid).id
    with mock_patch("mypa.notifier.publish", return_value=False) as pub:
        for _ in range(sched_mod.MAX_REMINDER_ATTEMPTS + 2):
            sched_mod.dispatch_reminders()
    assert pub.call_count == sched_mod.MAX_REMINDER_ATTEMPTS
    with session_factory()() as db:
        fired_at, attempts, err = _reminder_row(db, rid)
        assert fired_at is not None and err.startswith("failed")


def test_stuck_rows_do_not_block_newer_reminders():
    aid, bid = _setup()
    with session_factory()() as db:
        # 120 old reminders for a user with no topic would previously fill
        # the LIMIT 100 window forever.
        db.execute(text("UPDATE users SET notify_topic = NULL WHERE id = :i"), {"i": bid})
        db.commit()
        b_item = _item(db, bid)
        old = datetime.now(UTC) - timedelta(hours=2)
        for _ in range(120):
            service.add_reminder(db, b_item.id, old, user_id=bid)
        a_item = _item(db, aid)
        service.add_reminder(db, a_item.id, datetime.now(UTC) - timedelta(minutes=1), user_id=aid)
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_reminders()  # closes out 100 stuck rows
        sched_mod.dispatch_reminders()  # closes the rest + fires alice's
    assert pub.call_count == 1


def test_digest_counts_later_today_as_due_not_overdue():
    from zoneinfo import ZoneInfo
    aid, _ = _setup()
    london = ZoneInfo("Europe/London")
    now_local = datetime.now(london)
    with session_factory()() as db:
        users_lib.set_notify_prefs(db, aid, {"digest_hour": now_local.hour})
        # Due 1 minute before local midnight — today, never overdue
        end_of_day = now_local.replace(hour=23, minute=58, second=0, microsecond=0)
        _item(db, aid, due_at=end_of_day)
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_digests()
    msg = pub.call_args.kwargs["message"]
    assert "1 due today" in msg
    assert "overdue" not in msg
