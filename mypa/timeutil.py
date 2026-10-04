"""Timestamp normalization.

SQLite has no timezone-aware datetime type: SQLAlchemy's DateTime stores
the *wall time* and silently drops any UTC offset. So every datetime is
converted to UTC before it reaches the DB, and naive datetimes read back
are UTC by convention.

Naive *inputs* (e.g. "2026-05-22T15:30" with no offset) mean the user's
own local time, so they're interpreted in the user's tz.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

UTC = timezone.utc


def safe_zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "Etc/UTC")
    except Exception:
        return ZoneInfo("Etc/UTC")


def user_tz_name(db: Session, user_id: int | None) -> str:
    """The user's IANA tz, or Etc/UTC if unknown (or users table absent)."""
    if user_id is None:
        return "Etc/UTC"
    try:
        row = db.execute(
            text("SELECT tz FROM users WHERE id = :i"), {"i": user_id}
        ).fetchone()
    except Exception:
        return "Etc/UTC"
    return (row[0] if row and row[0] else "Etc/UTC")


def to_utc(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    """Return an aware-UTC datetime. Naive input is read as `tz_name` local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=safe_zone(tz_name))
    return dt.astimezone(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """Mark a datetime read from the DB (naive == UTC) as aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def iso(dt: datetime | None) -> str | None:
    dt = as_utc(dt)
    return dt.isoformat() if dt else None


def parse_iso(value: str, field: str = "datetime") -> datetime:
    """fromisoformat with an error message Claude can act on."""
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError(
            f"invalid {field} {value!r}: use ISO 8601, ideally with an offset, "
            "e.g. 2026-10-05T15:30:00+01:00"
        )


def db_ts(dt: datetime) -> str:
    """Format for raw-SQL writes, matching what SQLAlchemy's SQLite
    DateTime stores (naive UTC, space separator) so ORM reads parse it."""
    return to_utc(dt).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
