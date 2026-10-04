"""Repeat rules for reminders and recurring todos.

Rules are short strings so Claude can pass them straight through:
  daily, weekdays, weekly, fortnightly, monthly, quarterly, yearly,
  every N days / weeks / months / years

Occurrences are computed in the user's local time from a fixed anchor
(the first occurrence), so "9am" stays 9am across DST changes and
"monthly on the 31st" lands on the 31st whenever the month has one
(the 30th/28th otherwise) instead of drifting.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, tzinfo

_NAMED = {
    "daily": ("day", 1),
    "weekly": ("week", 1),
    "fortnightly": ("week", 2),
    "biweekly": ("week", 2),
    "monthly": ("month", 1),
    "quarterly": ("month", 3),
    "yearly": ("month", 12),
    "annually": ("month", 12),
    "weekdays": ("weekday", 1),
}
_EVERY = re.compile(r"^every\s+(\d{1,3})\s+(day|week|month|year)s?$")

RULE_HELP = ("use daily, weekdays, weekly, fortnightly, monthly, quarterly, "
             "yearly, or 'every N days/weeks/months/years'")


def parse_rule(rule: str) -> tuple[str, int]:
    """Return (unit, n) with unit in day/week/month/weekday. Raises ValueError."""
    r = (rule or "").strip().lower()
    if r in _NAMED:
        return _NAMED[r]
    m = _EVERY.match(r)
    if m and int(m.group(1)) > 0:
        n, unit = int(m.group(1)), m.group(2)
        return ("month", n * 12) if unit == "year" else (unit, n)
    raise ValueError(f"unknown repeat rule {rule!r}: {RULE_HELP}")


def normalize_rule(rule: str) -> str:
    parse_rule(rule)
    return " ".join(rule.strip().lower().split())


def _add_months(dt: datetime, months: int) -> datetime:
    total = dt.month - 1 + months
    year, month = dt.year + total // 12, total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def next_occurrence(rule: str, anchor: datetime, after: datetime, tz: tzinfo) -> datetime:
    """First occurrence of `rule` (starting at `anchor`) strictly after
    `after`. Both inputs are aware; the result is aware in `tz`."""
    unit, n = parse_rule(rule)
    base = anchor.astimezone(tz).replace(tzinfo=None)  # local wall time
    after_local = after.astimezone(tz)

    def at(naive: datetime) -> datetime:
        return naive.replace(tzinfo=tz)

    if unit == "weekday":
        day = after_local.replace(tzinfo=None).date()
        while True:
            cand = at(datetime.combine(day, base.time()))
            if day.weekday() < 5 and cand > after and cand >= at(base):
                return cand
            day += timedelta(days=1)

    if unit in ("day", "week"):
        step = timedelta(days=n * (7 if unit == "week" else 1))
        elapsed = after_local.replace(tzinfo=None) - base
        k = max(0, elapsed // step)
        while at(base + k * step) <= after:
            k += 1
        return at(base + k * step)

    # months
    al = after_local.replace(tzinfo=None)
    elapsed_months = (al.year - base.year) * 12 + (al.month - base.month)
    k = max(0, elapsed_months // n)
    while at(_add_months(base, k * n)) <= after:
        k += 1
    return at(_add_months(base, k * n))
