"""Parse WhatsApp "Export chat" text files.

WhatsApp has no API for personal accounts; its own Export chat feature
(chat → ⋮ / contact name → Export chat → Without media) is the supported
way to get history out. Two line formats exist:

  Android: 03/10/2026, 14:05 - Alice: See you at 7
  iOS:     [03/10/2026, 14:05:33] Alice: See you at 7

Lines that don't start with a timestamp continue the previous message.
Dates are day-first or month-first depending on the phone's locale;
we detect which from the data (a field > 12), defaulting to day-first.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

_LINE = re.compile(
    r"^‎?\[?(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4}),?\s+"
    r"(\d{1,2}:\d{2})(?::\d{2})?\s*([APap]\.?[Mm]\.?)?\]?\s*(?:-\s*)?"
    r"(.*)$"
)
_SKIP = ("Messages and calls are end-to-end encrypted", "<Media omitted>",
         "This message was deleted", "image omitted", "video omitted",
         "sticker omitted", "audio omitted", "GIF omitted", "document omitted")


@dataclass
class Message:
    day: date
    time: str
    sender: str
    text: str


def _year(y: str) -> int:
    return int(y) + 2000 if len(y) == 2 else int(y)


def parse(export: str, day_first: bool | None = None) -> list[Message]:
    raw: list[tuple[int, int, int, str, str]] = []
    for line in export.splitlines():
        m = _LINE.match(line)
        if m:
            a, b, y, hm, ampm, rest = m.groups()
            if ampm:
                h, mi = map(int, hm.split(":"))
                pm = ampm.lower().startswith("p")
                h = (h % 12) + (12 if pm else 0)
                hm = f"{h:02d}:{mi:02d}"
            raw.append((int(a), int(b), _year(y), hm.zfill(5), rest))
        elif raw:
            a, b, y, hm, rest = raw[-1]
            raw[-1] = (a, b, y, hm, rest + "\n" + line)

    if day_first is None:
        day_first = not any(b > 12 for _, b, _, _, _ in raw) or any(a > 12 for a, _, _, _, _ in raw)

    out: list[Message] = []
    for a, b, y, hm, rest in raw:
        d, mo = (a, b) if day_first else (b, a)
        try:
            day = date(y, mo, d)
        except ValueError:
            continue
        sender, sep, text = rest.partition(": ")
        if not sep:  # system line ("Alice added Bob")
            continue
        text = text.strip()
        if not text or any(s in text for s in _SKIP):
            continue
        out.append(Message(day, hm, sender.strip().lstrip("‎"), text))
    return out


def group_by_day(messages: list[Message]) -> "OrderedDict[date, list[Message]]":
    days: OrderedDict[date, list[Message]] = OrderedDict()
    for msg in messages:
        days.setdefault(msg.day, []).append(msg)
    return days


def render_day(msgs: list[Message]) -> str:
    return "\n".join(f"{m.time} **{m.sender}**: {m.text}" for m in msgs)
