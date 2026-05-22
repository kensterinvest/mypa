"""Phase 4 — notification dispatcher tests.

Covers the scheduler jobs (dispatch_reminders, dispatch_digests),
per-user scoping, and the prefs endpoint.
"""
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("OAUTH_JWT_SECRET", "test-jwt-notify")
os.environ.setdefault("NTFY_BASE_URL", "https://ntfy.example.invalid")

import pytest
from sqlalchemy import text
from unittest.mock import patch as mock_patch

from mypa import users as users_lib
from mypa import scheduler as sched_mod
from mypa.db import Base, engine, session_factory
from mypa.schemas import ItemCreate
from mypa import service
from tests.conftest import _apply_oauth_schema


def _setup():
    Base.metadata.create_all(engine())
    _apply_oauth_schema()
    from pathlib import Path as P
    for migration in ("003_users.sql", "005_notifications.sql"):
        sql = (P(__file__).parent.parent / "migrations" / migration).read_text(encoding="utf-8")
        sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
        with engine().begin() as conn:
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    Session = session_factory()
    with Session() as db:
        alice = users_lib.create_user(db, "a@e.com", "alice-pw-1234567", name="A", is_admin=True, tz="Europe/London")
        bob = users_lib.create_user(db, "b@e.com", "bob-pw-1234567", name="B", tz="Europe/London")
    return alice.id, bob.id


def test_user_gets_notify_topic_on_create():
    aid, _ = _setup()
    Session = session_factory()
    with Session() as db:
        s = users_lib.get_notify_settings(db, aid)
    assert s["topic"] is not None
    assert s["topic"].startswith("u-")
    assert len(s["topic"]) >= 16


def test_prefs_round_trip():
    aid, _ = _setup()
    Session = session_factory()
    with Session() as db:
        result = users_lib.set_notify_prefs(db, aid, {"digest_hour": 9, "realtime": False})
    assert result["prefs"]["digest_hour"] == 9
    assert result["prefs"]["realtime"] is False
    # Defaults stay for unspecified fields
    assert result["prefs"]["digest_enabled"] is True


def test_dispatch_reminders_fires_due_and_marks_fired_at():
    aid, bid = _setup()
    Session = session_factory()
    with Session() as db:
        a_item = service.create_item(db, ItemCreate(kind="todo", title="A's task"), user_id=aid)
        # Reminder due 1 min ago for Alice
        db.execute(text(
            "INSERT INTO reminders (item_id, user_id, fire_at, message, channel) "
            "VALUES (:i, :u, :t, :m, 'ntfy')"
        ), {"i": a_item.id, "u": aid,
            "t": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "m": "test reminder"})
        db.commit()

    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        fired = sched_mod.dispatch_reminders()

    assert fired == 1
    assert pub.call_count == 1
    # Confirm it was sent to ALICE's topic, not Bob's
    sent_topic = pub.call_args[0][0]
    with session_factory()() as db:
        alice_topic = users_lib.get_notify_settings(db, aid)["topic"]
        bob_topic = users_lib.get_notify_settings(db, bid)["topic"]
    assert sent_topic == alice_topic
    assert sent_topic != bob_topic

    # Second dispatch fires nothing (fired_at now set)
    with mock_patch("mypa.notifier.publish", return_value=True) as pub2:
        fired2 = sched_mod.dispatch_reminders()
    assert fired2 == 0
    assert pub2.call_count == 0


def test_dispatch_reminders_respects_realtime_pref_off():
    aid, _ = _setup()
    Session = session_factory()
    with Session() as db:
        users_lib.set_notify_prefs(db, aid, {"realtime": False})
        a_item = service.create_item(db, ItemCreate(kind="todo", title="A's task"), user_id=aid)
        db.execute(text(
            "INSERT INTO reminders (item_id, user_id, fire_at, message, channel) "
            "VALUES (:i, :u, :t, :m, 'ntfy')"
        ), {"i": a_item.id, "u": aid,
            "t": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "m": "off"})
        db.commit()
    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_reminders()
    assert pub.call_count == 0


def test_dispatch_digest_fires_once_per_day():
    aid, _ = _setup()
    Session = session_factory()
    with Session() as db:
        # Set digest_hour to whatever London local hour we currently have,
        # so the digest condition triggers regardless of when the test runs.
        from zoneinfo import ZoneInfo
        london_now = datetime.now(ZoneInfo("Europe/London"))
        users_lib.set_notify_prefs(db, aid, {"digest_hour": london_now.hour})
        # Give Alice an item due today so the digest has content
        service.create_item(db, ItemCreate(
            kind="todo", title="due today",
            due_at=datetime.now(timezone.utc) + timedelta(hours=2),
        ), user_id=aid)

    with mock_patch("mypa.notifier.publish", return_value=True) as pub:
        sched_mod.dispatch_digests()
    assert pub.call_count >= 1

    # Second invocation in the same hour should NOT send another digest
    with mock_patch("mypa.notifier.publish", return_value=True) as pub2:
        sched_mod.dispatch_digests()
    assert pub2.call_count == 0


def test_notifier_publish_no_base_url_returns_false(monkeypatch):
    from mypa import notifier, settings as settings_mod
    settings_mod._settings = None
    monkeypatch.setenv("NTFY_BASE_URL", "")
    assert notifier.publish("u-anything", message="x") is False


def test_ntfy_account_lifecycle_with_user_mgmt(monkeypatch):
    """When NTFY_USER_MGMT_ENABLED=true, create_user / rotate_notify_topic /
    disable_user must call ntfy_admin. Mock out the CLI."""
    from mypa import users as users_lib
    from mypa import ntfy_admin
    from mypa import settings as settings_mod

    _setup()
    # Flip user-mgmt on for this test only
    monkeypatch.setenv("NTFY_USER_MGMT_ENABLED", "true")
    settings_mod._settings = None

    created: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(ntfy_admin, "create_user_for_topic",
                        lambda topic: (created.append(topic), "test-pw-" + topic)[1])
    monkeypatch.setattr(ntfy_admin, "delete_user_for_topic",
                        lambda topic: deleted.append(topic))

    Session = session_factory()
    with Session() as db:
        user = users_lib.create_user(db, "c@e.com", "c-pw-1234567", name="C", tz="Europe/London")
    assert len(created) == 1
    first_topic = created[0]
    assert first_topic.startswith("u-")

    # Stored ntfy password should be the one ntfy_admin returned
    with Session() as db:
        s = users_lib.get_notify_settings(db, user.id)
    assert s["ntfy_password"] == "test-pw-" + first_topic
    assert s["ntfy_username"] == first_topic

    # rotate — should provision new + delete old
    with Session() as db:
        new_topic, new_pw = users_lib.rotate_notify_topic(db, user.id)
    assert new_topic != first_topic
    assert first_topic in deleted   # old topic revoked
    assert new_topic in created     # new topic provisioned
    assert new_pw == "test-pw-" + new_topic

    # disable — should delete the (current) ntfy account
    deleted.clear()
    with Session() as db:
        ok = users_lib.disable_user(db, user.id)
    assert ok is True
    assert new_topic in deleted
