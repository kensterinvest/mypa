"""MCP tool-surface cleanup (roadmap item 3)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch as mock_patch
from zoneinfo import ZoneInfo

import pytest

from mypa import mcp_server as mcp_mod
from mypa import scheduler as sched_mod
from mypa import users as users_lib
from mypa.audit import set_request_context
from mypa.db import session_factory
from mypa.models import Item
from tests.conftest import make_admin

UTC = timezone.utc


@pytest.fixture
def uid():
    u = make_admin()
    set_request_context("ip", "rw", user_id=u)
    return u


def test_search_matches_words_in_any_order(uid):
    mcp_mod.pa_add(kind="place", title="Pizza Express", body="Best pizza in London")
    mcp_mod.pa_add(kind="place", title="Dishoom", body="London curry")
    hits = mcp_mod.pa_search("london pizza")["items"]
    assert [h["title"] for h in hits] == ["Pizza Express"]


def test_tag_filter_is_exact(uid):
    mcp_mod.pa_add(kind="note", title="gallery", tags=["art"])
    mcp_mod.pa_add(kind="note", title="birthday", tags=["party"])
    titles = [i["title"] for i in mcp_mod.pa_list(tag="art")["items"]]
    assert titles == ["gallery"]


def test_comma_tag_and_bad_date_return_errors_not_exceptions(uid):
    assert "commas" in mcp_mod.pa_add(kind="note", title="x", tags=["a,b"])["error"]
    assert "ISO 8601" in mcp_mod.pa_add(kind="todo", title="x", due_at="next tues")["error"]
    assert "ISO 8601" in mcp_mod.pa_list(due_before="soon")["error"]
    assert "ISO 8601" in mcp_mod.pa_add_reminder(1, "tomorrow")["error"]


def test_due_at_can_be_cleared(uid):
    item = mcp_mod.pa_add(kind="todo", title="x", due_at="2030-01-01T09:00:00+00:00")
    assert item["due_at"] == "2030-01-01T09:00:00+00:00"
    assert mcp_mod.pa_update(item["id"], due_at="")["due_at"] is None


def test_list_order_by_due_and_offset(uid):
    mcp_mod.pa_add(kind="todo", title="later", due_at="2030-03-01T09:00:00+00:00")
    mcp_mod.pa_add(kind="todo", title="undated")
    mcp_mod.pa_add(kind="todo", title="sooner", due_at="2030-02-01T09:00:00+00:00")
    titles = [i["title"] for i in mcp_mod.pa_list(order_by="due")["items"]]
    assert titles == ["sooner", "later", "undated"]
    page2 = mcp_mod.pa_list(order_by="due", limit=1, offset=1)["items"]
    assert [i["title"] for i in page2] == ["later"]


def test_list_and_cancel_reminders(uid):
    item = mcp_mod.pa_add(kind="todo", title="dentist")
    r = mcp_mod.pa_add_reminder(item["id"], "2030-01-01T09:00:00+00:00")
    listed = mcp_mod.pa_list_reminders()["reminders"]
    assert [(x["reminder_id"], x["item_title"]) for x in listed] == [(r["reminder_id"], "dentist")]
    assert mcp_mod.pa_get(item["id"])["reminders"][0]["reminder_id"] == r["reminder_id"]
    assert mcp_mod.pa_cancel_reminder(r["reminder_id"])["item_id"] == item["id"]
    assert mcp_mod.pa_list_reminders()["count"] == 0
    assert "error" in mcp_mod.pa_cancel_reminder(r["reminder_id"])


def test_undo_only_recent_saves(uid):
    old = mcp_mod.pa_add(kind="note", title="old")
    with session_factory()() as db:
        db.get(Item, old["id"]).created_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    assert "10 minutes" in mcp_mod.pa_undo_last()["error"]
    new = mcp_mod.pa_add(kind="note", title="new")
    assert new["source"] == "claude"
    assert mcp_mod.pa_undo_last()["removed_id"] == new["id"]
    assert mcp_mod.pa_get(old["id"])["title"] == "old"


def test_extract_stub_removed():
    assert not hasattr(mcp_mod, "pa_extract_from_image")


@pytest.mark.parametrize("patch,msg", [
    ({"tz": "Mars/Base"}, "unknown timezone"),
    ({"digest_hour": 99}, "digest_hour"),
    ({"overdue_day": 7}, "overdue_day"),
])
def test_notify_prefs_validated(uid, patch, msg):
    r = mcp_mod.pa_set_notify_prefs(**patch)
    assert msg in r["error"]


def test_weekly_overdue_push(uid):
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    with session_factory()() as db:
        users_lib.set_notify_prefs(db, uid, {
            "tz": "Asia/Tokyo",
            "overdue_weekly_enabled": True,
            "overdue_day": (now.weekday() + 1) % 7,
            "overdue_hour": now.hour,
        })
    mcp_mod.pa_add(kind="todo", title="renew passport", due_at="2020-01-01T09:00:00+00:00")
    mcp_mod.pa_add(kind="todo", title="future", due_at="2099-01-01T09:00:00+00:00")
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        assert sched_mod.dispatch_overdue_weekly() == 1
        assert sched_mod.dispatch_overdue_weekly() == 0  # once per day
    assert pub.call_args.kwargs["message"] == "renew passport"
    assert "1 overdue" in pub.call_args.kwargs["title"]


def test_source_ref_makes_sync_idempotent(uid):
    first = mcp_mod.pa_add(kind="purchase", title="Amazon order", source="gmail",
                           source_ref="thread-123")
    again = mcp_mod.pa_add(kind="purchase", title="Amazon order (re-read)", source="gmail",
                           source_ref="thread-123")
    assert again["duplicate"] is True and again["id"] == first["id"]
    assert first["source"] == "gmail" and first["source_ref"] == "thread-123"
    assert "together" in mcp_mod.pa_add(kind="note", title="x", source="gmail")["error"]
    assert "lowercase" in mcp_mod.pa_add(kind="note", title="x", source="Gmail!",
                                         source_ref="1")["error"]


ANDROID_EXPORT = """03/10/2026, 14:05 - Messages and calls are end-to-end encrypted.
03/10/2026, 14:05 - Alice: Dinner at Dishoom Friday 7pm?
03/10/2026, 14:06 - Me: Yes! Booking now
04/10/2026, 09:00 - Alice: <Media omitted>
04/10/2026, 09:01 - Alice: Address is 7 Boundary St"""


def test_whatsapp_import_is_searchable_and_incremental(uid):
    r = mcp_mod.pa_import_whatsapp("Alice", ANDROID_EXPORT)
    assert (r["messages"], r["days"], r["created"]) == (3, 2, 2)
    hits = mcp_mod.pa_search("dishoom")["items"]
    assert [h["title"] for h in hits] == ["WhatsApp: Alice — 2026-10-03"]
    assert hits[0]["source"] == "whatsapp"
    # Re-export later with one more message that day: updates, no duplicates
    more = ANDROID_EXPORT + "\n04/10/2026, 10:00 - Me: Thanks!"
    r2 = mcp_mod.pa_import_whatsapp("Alice", more)
    assert (r2["created"], r2["updated"], r2["unchanged"]) == (0, 1, 1)
    assert mcp_mod.pa_list(kind="chat")["count"] == 2


def test_whatsapp_import_rejects_non_export(uid):
    assert "no messages" in mcp_mod.pa_import_whatsapp("x", "hello world")["error"]
