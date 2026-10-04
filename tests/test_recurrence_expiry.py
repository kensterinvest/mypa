"""Repeating reminders, recurring todos, expiry alerts (roadmap item 5)."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch as mock_patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from mypa import mcp_server as mcp_mod
from mypa import recurrence
from mypa import scheduler as sched_mod
from mypa import users as users_lib
from mypa.audit import set_request_context
from mypa.db import session_factory
from tests.conftest import make_admin

UTC = timezone.utc
LON = ZoneInfo("Europe/London")


# ---- pure rule maths -------------------------------------------------------

def test_weekly_keeps_local_time_across_dst():
    anchor = datetime(2026, 10, 19, 9, 0, tzinfo=LON)        # BST
    nxt = recurrence.next_occurrence("weekly", anchor, anchor + timedelta(days=7), LON)
    assert nxt == datetime(2026, 11, 2, 9, 0, tzinfo=LON)    # GMT, still 9am
    assert nxt.utcoffset() == timedelta(0)


def test_monthly_on_31st_does_not_drift():
    anchor = datetime(2027, 1, 31, 9, 0, tzinfo=UTC)
    feb = recurrence.next_occurrence("monthly", anchor, anchor, UTC)
    mar = recurrence.next_occurrence("monthly", anchor, feb, UTC)
    assert (feb.month, feb.day, mar.month, mar.day) == (2, 28, 3, 31)


def test_every_n_and_yearly_and_weekdays():
    anchor = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)          # a Friday
    assert recurrence.next_occurrence("every 2 weeks", anchor, anchor, UTC).day == 16
    assert recurrence.next_occurrence("yearly", anchor, anchor, UTC).year == 2027
    mon = recurrence.next_occurrence("weekdays", anchor, anchor, UTC)
    assert mon.weekday() == 0 and mon.day == 5                # skips the weekend


def test_skips_missed_occurrences():
    anchor = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    after = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    assert recurrence.next_occurrence("daily", anchor, after, UTC) == datetime(2026, 3, 16, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["sometimes", "every 0 days", "every week", ""])
def test_bad_rules_rejected(bad):
    with pytest.raises(ValueError):
        recurrence.parse_rule(bad)


# ---- through the tools -----------------------------------------------------

@pytest.fixture
def uid():
    u = make_admin()
    set_request_context("ip", "rw", user_id=u)
    return u


def test_repeating_reminder_advances_instead_of_closing(uid):
    item = mcp_mod.pa_add(kind="todo", title="pay cleaner")
    first = datetime.now(UTC) - timedelta(minutes=1)
    r = mcp_mod.pa_add_reminder(item["id"], first.isoformat(), repeat="every 2 weeks")
    assert r["repeat"] == "every 2 weeks"
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        assert sched_mod.dispatch_reminders() == 1
        assert sched_mod.dispatch_reminders() == 0
    assert pub.call_count == 1
    pending = mcp_mod.pa_list_reminders()["reminders"]
    assert len(pending) == 1
    nxt = datetime.fromisoformat(pending[0]["fire_at"])
    assert abs(nxt - (first + timedelta(weeks=2))) < timedelta(seconds=1)


def test_bad_repeat_rule_is_an_error(uid):
    item = mcp_mod.pa_add(kind="todo", title="x")
    assert "repeat rule" in mcp_mod.pa_add_reminder(item["id"], "2030-01-01T09:00:00+00:00",
                                                    repeat="now and then")["error"]


def test_completing_recurring_todo_creates_next(uid):
    due = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    item = mcp_mod.pa_add(kind="todo", title="bins out", due_at=due.isoformat(),
                          data={"repeat": "weekly"})
    done = mcp_mod.pa_complete(item["id"])
    assert done["status"] == "done"
    nxt = done["next_occurrence"]
    assert nxt["status"] == "open" and nxt["title"] == "bins out"
    assert datetime.fromisoformat(nxt["due_at"]) == due + timedelta(weeks=1)
    assert "next_occurrence" not in mcp_mod.pa_complete(item["id"])  # no duplicate
    # One-off todos don't spawn anything
    plain = mcp_mod.pa_add(kind="todo", title="one-off", due_at=due.isoformat())
    assert "next_occurrence" not in mcp_mod.pa_complete(plain["id"])


def test_completing_late_does_not_create_overdue_copy(uid):
    due = datetime.now(UTC) - timedelta(days=10)
    item = mcp_mod.pa_add(kind="todo", title="water plants", due_at=due.isoformat(),
                          data={"repeat": "weekly"})
    nxt = mcp_mod.pa_complete(item["id"])["next_occurrence"]
    assert datetime.fromisoformat(nxt["due_at"]) > datetime.now(UTC)


# ---- expiry alerts -----------------------------------------------------------

def _at_digest_hour(uid):
    now = datetime.now(LON)
    with session_factory()() as db:
        users_lib.set_notify_prefs(db, uid, {"tz": "Europe/London", "digest_hour": now.hour})
    return now.date()


def test_expiry_alert_thresholds_fire_once(uid):
    today = _at_digest_hour(uid)
    mcp_mod.pa_add(kind="contract", title="IONOS hosting", body="## Why\nprice was the issue",
                   data={"end": (today + timedelta(days=30)).isoformat()})
    mcp_mod.pa_add(kind="note", title="no dates", data={"x": 1})
    mcp_mod.pa_add(kind="contract", title="far away",
                   data={"end": (today + timedelta(days=200)).isoformat()})
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        assert sched_mod.dispatch_expiry_alerts() == 1
        assert sched_mod.dispatch_expiry_alerts() == 0   # same threshold: once
    kw = pub.call_args.kwargs
    assert kw["title"] == "MyPA — contract ends in 30 days"
    assert "IONOS hosting" in kw["message"] and "price was the issue" in kw["message"]


def test_item_first_seen_inside_window_gets_one_push(uid):
    today = _at_digest_hour(uid)
    mcp_mod.pa_add(kind="reference", title="Passport",
                   data={"expires": (today + timedelta(days=5)).isoformat()})
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_expiry_alerts()
        sched_mod.dispatch_expiry_alerts()
    assert pub.call_count == 1   # not 30-day AND 7-day pushes
    with session_factory()() as db:
        days = {r[0] for r in db.execute(text("SELECT days FROM expiry_alerts"))}
    assert days == {7, 30}


def test_renewed_contract_alerts_again(uid):
    today = _at_digest_hour(uid)
    item = mcp_mod.pa_add(kind="contract", title="Gym",
                          data={"end": (today + timedelta(days=1)).isoformat()})
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_expiry_alerts()
        mcp_mod.pa_update(item["id"], data={"end": (today + timedelta(days=7)).isoformat()})
        sched_mod.dispatch_expiry_alerts()
    assert pub.call_count == 2


def test_expiry_alerts_can_be_turned_off(uid):
    today = _at_digest_hour(uid)
    mcp_mod.pa_set_notify_prefs(expiry_alerts=False)
    mcp_mod.pa_add(kind="contract", title="x", data={"end": today.isoformat()})
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_expiry_alerts()
    assert pub.call_count == 0


def test_end_date_formats():
    assert sched_mod._parse_end_date("2027-05") == date(2027, 5, 1)
    assert sched_mod._parse_end_date("2027-05-20T10:00:00+01:00") == date(2027, 5, 20)
    assert sched_mod._parse_end_date("May 2027") is None
    assert sched_mod._parse_end_date(20270501) is None
