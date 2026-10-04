"""Business logic — shared by REST routes and MCP tools.

Keeping CRUD here (rather than in routes/) means the MCP tool layer can
call the same functions without going through HTTP. One implementation,
two surfaces.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Float, Integer, and_, func, literal, or_, select, text
from sqlalchemy.orm import Session

from .models import Item, Reminder
from .schemas import ItemCreate, ItemPatch
from . import recurrence
from .timeutil import as_utc, safe_zone, to_utc, user_tz_name


def _tags_to_str(tags: list[str] | None) -> str:
    if not tags:
        return ""
    cleaned: list[str] = []
    for t in tags:
        if not t or not t.strip():
            continue
        if "," in t:
            # Reject comma-containing tags — comma is the storage delimiter.
            # Users (and Claude) should split into multiple tags themselves.
            raise ValueError(
                f"tag {t!r} cannot contain commas; split into multiple tags"
            )
        cleaned.append(t.strip().lower())
    return ",".join(sorted(set(cleaned)))


def _str_to_tags(s: str | None) -> list[str]:
    if not s:
        return []
    return [t for t in s.split(",") if t]


def _append_context(body: str, context: str | None) -> str:
    if not context:
        return body
    block = f"\n\n## Context\n{context.strip()}\n"
    return (body or "").rstrip() + block


def create_item(db: Session, payload: ItemCreate, user_id: int | None = None) -> Item:
    item = Item(
        user_id=user_id,
        kind=payload.kind.strip().lower(),
        title=payload.title.strip(),
        body=_append_context(payload.body or "", payload.context),
        status=payload.status,
        priority=payload.priority,
        due_at=to_utc(payload.due_at, user_tz_name(db, user_id)),
        tags=_tags_to_str(payload.tags),
        data=payload.data or {},
        source=payload.source,
        source_ref=payload.source_ref,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def find_by_source_ref(
    db: Session, source: str, source_ref: str, user_id: int | None = None,
) -> Item | None:
    """The item previously imported from (source, source_ref), e.g. a
    Gmail thread — lets syncs re-run without creating duplicates."""
    stmt = select(Item).where(Item.source == source, Item.source_ref == source_ref)
    if user_id is not None:
        stmt = stmt.where(Item.user_id == user_id)
    return db.execute(stmt.limit(1)).scalar_one_or_none()


def get_item(db: Session, item_id: int, user_id: int | None = None) -> Item | None:
    item = db.get(Item, item_id)
    if item is None:
        return None
    # Scope check: when caller specifies user_id, item must belong to them.
    # Ownerless legacy rows (user_id NULL) are not visible to any user —
    # scripts/backfill_admin_user.py assigns them to the admin.
    if user_id is not None and item.user_id != user_id:
        return None
    return item


def _has_tag(tag: str):
    """Exact tag match. Tags are stored comma-joined ("food,italy"), so
    wrap in commas — a bare LIKE '%art%' would also match 'party'."""
    needle = f"%,{_escape_like(tag.strip().lower())},%"
    return (literal(",") + Item.tags + literal(",")).like(needle, escape="\\")


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_items(
    db: Session,
    kind: str | None = None,
    status: str | None = None,
    due_before: datetime | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: int | None = None,
    order_by: str = "updated",
    where: list[str] | None = None,
) -> list[Item]:
    """order_by: 'updated' (newest first, default), 'due' (soonest due
    first, undated last) or 'created' (newest first).
    where: filters on data{} fields — see _data_filters."""
    stmt = select(Item)
    if user_id is not None:
        stmt = stmt.where(Item.user_id == user_id)
    if kind:
        stmt = stmt.where(Item.kind == kind.lower())
    if status:
        stmt = stmt.where(Item.status == status)
    if due_before:
        due_before = to_utc(due_before, user_tz_name(db, user_id))
        stmt = stmt.where(Item.due_at != None, Item.due_at <= due_before)  # noqa: E711
    if tag:
        stmt = stmt.where(_has_tag(tag))
    if where:
        stmt = stmt.where(*_data_filters(where))
    if order_by == "due":
        stmt = stmt.order_by(Item.due_at.is_(None), Item.due_at.asc())
    elif order_by == "created":
        stmt = stmt.order_by(Item.created_at.desc())
    else:
        stmt = stmt.order_by(Item.updated_at.desc())
    stmt = stmt.limit(min(limit, 500)).offset(offset)
    return list(db.execute(stmt).scalars())


_WHERE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*(>=|<=|!=|=|>|<|~)\s*(.*?)\s*$")


def _data_filters(where: list[str] | None) -> list:
    """Turn ["rating>=4", "category=italian", "notes~fireplace"] into SQL
    conditions on the JSON `data` column.

    Operators: = != > >= < <= and ~ (contains). Numbers compare
    numerically; text compares case-insensitively. Nested keys use dots
    ("address.city=London").
    """
    conds = []
    for expr in where or []:
        m = _WHERE_RE.match(expr or "")
        if not m or m.group(3) == "" or m.group(3)[0] in "<>=!~":
            raise ValueError(
                f"bad filter {expr!r}: use field<op>value, e.g. 'rating>=4', "
                "'category=italian', 'notes~garden' (ops: = != > >= < <= ~)"
            )
        key, op, raw = m.groups()
        raw = raw.strip("'\"")
        field = func.json_extract(Item.data, f"$.{key}")
        if op == "~":
            conds.append(func.lower(field).like(f"%{_escape_like(raw.lower())}%", escape="\\"))
            continue
        try:
            value: Any = float(raw) if "." in raw else int(raw)
            lhs = field
        except ValueError:
            if raw.lower() in ("true", "false"):
                value, lhs = (1 if raw.lower() == "true" else 0), field
            else:
                value, lhs = raw.lower(), func.lower(field)
        conds.append({
            "=": lhs == value, "!=": lhs != value, ">": lhs > value,
            ">=": lhs >= value, "<": lhs < value, "<=": lhs <= value,
        }[op])
    return conds


def _fts_query(q: str) -> str | None:
    """User text -> safe FTS5 MATCH expression: every word must match,
    as a prefix ("pizz" finds "pizza"). FTS operators in the input are
    neutralized by quoting each token."""
    tokens = re.findall(r"\w+", q.lower())[:10]
    return " ".join(f'"{t}"*' for t in tokens) or None


def _has_fts(db: Session) -> bool:
    return db.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'items_fts'"
    )).first() is not None


def search_items(
    db: Session, q: str, limit: int = 20, user_id: int | None = None,
    kind: str | None = None, where: list[str] | None = None,
) -> list[Item]:
    """Full-text search across title + body + tags, best match first.

    Uses the FTS5 index from migration 010 (stemmed, prefix-matching,
    title hits ranked above body hits). Falls back to LIKE — every word
    must appear somewhere — if the index doesn't exist.
    `kind` and `where` (see _data_filters) narrow the results.
    """
    filters = _data_filters(where)
    if kind:
        filters.append(Item.kind == kind.strip().lower())
    if user_id is not None:
        filters.append(Item.user_id == user_id)
    limit = min(limit, 200)

    match = _fts_query(q)
    if match is None:
        if not (where or kind):
            return []
        stmt = select(Item).where(*filters).order_by(Item.updated_at.desc()).limit(limit)
        return list(db.execute(stmt).scalars())

    if _has_fts(db):
        # bm25 weights: title 10, body 1, tags 5. Lower rank = better.
        hits = (
            text("SELECT rowid AS item_id, bm25(items_fts, 10.0, 1.0, 5.0) AS rank "
                 "FROM items_fts WHERE items_fts MATCH :q")
            .bindparams(q=match)
            .columns(item_id=Integer, rank=Float)
            .subquery()
        )
        stmt = (select(Item).join(hits, hits.c.item_id == Item.id)
                .where(*filters).order_by(hits.c.rank).limit(limit))
        return list(db.execute(stmt).scalars())

    conds = []
    for w in re.findall(r"\w+", q.lower())[:10]:
        needle = f"%{_escape_like(w)}%"
        conds.append(or_(
            Item.title.ilike(needle, escape="\\"),
            Item.body.ilike(needle, escape="\\"),
            Item.tags.ilike(needle, escape="\\"),
        ))
    stmt = (select(Item).where(and_(*conds), *filters)
            .order_by(Item.updated_at.desc()).limit(limit))
    return list(db.execute(stmt).scalars())


def update_item(db: Session, item_id: int, patch: ItemPatch, user_id: int | None = None) -> Item | None:
    item = get_item(db, item_id, user_id=user_id)
    if item is None:
        return None

    fields = patch.model_dump(exclude_unset=True, exclude={"allow_history_rewrite"})
    if "tags" in fields:
        fields["tags"] = _tags_to_str(fields["tags"])
    if fields.get("due_at") is not None:
        fields["due_at"] = to_utc(fields["due_at"], user_tz_name(db, user_id))

    # Decision append-only convention — see master plan §Decision affordances.
    # The new body must CONTAIN the existing body verbatim (substring match,
    # not prefix). This lets callers add prefatory headings, footnotes, or
    # `## Update YYYY-MM-DD` sections without violating the rule. Cosmetic
    # whitespace normalization is normalized before comparison.
    if (
        item.kind == "decision"
        and "body" in fields
        and not patch.allow_history_rewrite
    ):
        new_body = (fields["body"] or "").replace("\r\n", "\n").strip()
        existing = (item.body or "").replace("\r\n", "\n").strip()
        if existing and existing not in new_body:
            raise ValueError(
                "decision body is append-only — existing content must remain "
                "verbatim in the update. Set allow_history_rewrite=true to override."
            )

    for k, v in fields.items():
        setattr(item, k, v)
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def complete_item(db: Session, item_id: int, user_id: int | None = None) -> Item | None:
    return complete_item_with_next(db, item_id, user_id=user_id)[0]


def item_repeat_rule(item: Item) -> str | None:
    """Recurring todos carry their rule in data.repeat (data.recurring is
    accepted too — the 'date' kind's example uses it)."""
    data = item.data or {}
    rule = data.get("repeat") or data.get("recurring")
    return rule if isinstance(rule, str) and rule.strip() else None


def complete_item_with_next(
    db: Session, item_id: int, user_id: int | None = None,
) -> tuple[Item | None, Item | None]:
    """Mark an item done. If it's a recurring item with a due date, also
    create the next open occurrence, due at the next date after
    max(old due, now) — finishing "pay cleaner every 2 weeks" late
    doesn't produce an already-overdue copy. Returns (done, next)."""
    item = get_item(db, item_id, user_id=user_id)
    if item is None:
        return None, None
    if item.status == "done":
        return item, None  # already done: don't spawn a second next occurrence
    now = datetime.now(timezone.utc)
    item.status = "done"
    item.completed_at = now
    item.updated_at = now

    nxt = None
    rule = item_repeat_rule(item)
    if rule and item.due_at is not None:
        try:
            recurrence.parse_rule(rule)
        except ValueError:
            rule = None
    if rule and item.due_at is not None:
        tz = safe_zone(user_tz_name(db, user_id if user_id is not None else item.user_id))
        due = as_utc(item.due_at)
        anchor_raw = (item.data or {}).get("repeat_anchor")
        try:
            anchor = as_utc(datetime.fromisoformat(anchor_raw)) if anchor_raw else due
        except ValueError:
            anchor = due
        next_due = recurrence.next_occurrence(rule, anchor, max(due, now), tz)
        nxt = Item(
            user_id=item.user_id, kind=item.kind, title=item.title, body=item.body,
            status="open", priority=item.priority, due_at=next_due.astimezone(timezone.utc),
            tags=item.tags, data={**(item.data or {}), "repeat_anchor": anchor.isoformat()},
            source=item.source,
        )
        db.add(nxt)
    db.commit()
    db.refresh(item)
    if nxt is not None:
        db.refresh(nxt)
    return item, nxt


def delete_item(db: Session, item_id: int, user_id: int | None = None) -> bool:
    item = get_item(db, item_id, user_id=user_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def add_reminder(
    db: Session, item_id: int, fire_at: datetime, message: str | None = None,
    channel: str = "ntfy", user_id: int | None = None, repeat: str | None = None,
) -> Reminder | None:
    """Schedule a reminder. `repeat` (see recurrence.py) makes it recur:
    after each send it moves to the next occurrence. Raises ValueError
    for an unknown rule."""
    if repeat:
        repeat = recurrence.normalize_rule(repeat)
    item = get_item(db, item_id, user_id=user_id)
    if item is None:
        return None
    fire_at = to_utc(fire_at, user_tz_name(db, user_id))
    r = Reminder(item_id=item_id, user_id=user_id, fire_at=fire_at, message=message,
                 channel=channel, repeat=repeat or None,
                 repeat_anchor=fire_at if repeat else None)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def upcoming_reminders(
    db: Session, limit: int = 20, user_id: int | None = None, item_id: int | None = None,
) -> list[Reminder]:
    stmt = select(Reminder).where(Reminder.fired_at == None)  # noqa: E711
    if user_id is not None:
        stmt = stmt.where(Reminder.user_id == user_id)
    if item_id is not None:
        stmt = stmt.where(Reminder.item_id == item_id)
    stmt = stmt.order_by(Reminder.fire_at.asc()).limit(limit)
    return list(db.execute(stmt).scalars())


def cancel_reminder(db: Session, reminder_id: int, user_id: int | None = None) -> Reminder | None:
    """Delete a pending reminder. Returns it, or None if not found / not
    yours / already fired."""
    r = db.get(Reminder, reminder_id)
    if r is None or r.fired_at is not None:
        return None
    if user_id is not None and r.user_id != user_id:
        return None
    db.delete(r)
    db.commit()
    return r


# How long after a save "undo" still applies. Long enough for a
# conversational "actually no, undo that"; short enough that it can't
# silently delete something saved days ago.
UNDO_WINDOW = timedelta(minutes=10)


def undo_last(db: Session, source: str | None = None, user_id: int | None = None) -> Item | None:
    """Undo the most recent save: delete the newest item created within
    UNDO_WINDOW, optionally filtered by source. Hard-deletes.
    """
    cutoff = datetime.now(timezone.utc) - UNDO_WINDOW
    stmt = select(Item).where(Item.created_at >= cutoff)
    if user_id is not None:
        stmt = stmt.where(Item.user_id == user_id)
    if source:
        stmt = stmt.where(Item.source == source)
    stmt = stmt.order_by(Item.created_at.desc()).limit(1)
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        return None
    db.delete(item)
    db.commit()
    return item


# --- kinds registry for pa_describe_schema() ---

DEFAULT_KINDS: dict[str, dict[str, Any]] = {
    "todo": {
        "description": "Action with optional due date. Set data.repeat "
                       "(e.g. 'weekly', 'every 2 weeks') + due_at to make it recurring: "
                       "completing it creates the next one.",
        "example_data": {"project": "string", "blocked_by": "item id", "repeat": "weekly"},
    },
    "reminder": {
        "description": "Simple alert at a specific time.",
        "example_data": {},
    },
    "date": {
        "description": "A date to remember (birthday, anniversary).",
        "example_data": {"recurring": "yearly", "person_id": "int"},
    },
    "purchase": {
        "description": "A thing to buy.",
        "example_data": {"category": "string", "store": "string", "price": "number"},
    },
    "trip": {
        "description": "Travel plan.",
        "example_data": {"destination": "string", "depart_at": "iso", "return_at": "iso"},
    },
    "chat": {
        "description": "Archived conversation (one item per chat per day), e.g. "
                       "imported from a WhatsApp export via pa_import_whatsapp.",
        "example_data": {"chat": "string", "date": "iso date", "participants": ["string"]},
    },
    "note": {
        "description": "Freeform text. Body is the content.",
        "example_data": {},
    },
    "idea": {
        "description": "An idea to develop.",
        "example_data": {"category": "string"},
    },
    "reference": {
        "description": "Durable fact to remember (contract IDs, account numbers, recipes).",
        "example_data": {"category": "string"},
    },
    "contract": {
        "description": "Service contract with renewal date. data.end (ISO date) "
                       "triggers push alerts 30/7/1 days before it ends.",
        "example_data": {
            "provider": "string",
            "contract_id": "string",
            "start": "iso",
            "end": "iso",
            "monthly_cost": "number",
        },
    },
    "subscription": {
        "description": "Recurring paid service. data.renew_at (ISO date) triggers "
                       "renewal alerts.",
        "example_data": {"provider": "string", "plan": "string", "monthly_cost": "number",
                         "renew_at": "iso date"},
    },
    "account": {
        "description": "Online service account info (non-secret; keep passwords in your password manager).",
        "example_data": {"provider": "string", "username": "string", "account_number": "string"},
    },
    "person": {
        "description": "A person (family, friend, contact).",
        "example_data": {"relationship": "string", "phone": "string", "email": "string"},
    },
    "event": {
        "description": "Dated event (will sync to Google Calendar in Phase 5).",
        "example_data": {"start_at": "iso", "end_at": "iso", "location": "string"},
    },
    "wish": {
        "description": "Wishlist item.",
        "example_data": {"category": "string", "est_cost": "number", "url": "string"},
    },
    "location": {
        "description": "A place — home, work, school.",
        "example_data": {"address": "string", "lat": "number", "lon": "number"},
    },
    "learning": {
        "description": "Topic the user is studying.",
        "example_data": {"topic": "string", "source_url": "string", "progress_pct": "number"},
    },
    "place": {
        "description": "A visited place (restaurant, shop, hotel).",
        "example_data": {
            "category": "restaurant|shop|hotel|park",
            "address": "string",
            "rating": "1-5",
            "visited_at": "iso",
        },
    },
    "preference": {
        "description": "Like / dislike for food, brand, music, style.",
        "example_data": {
            "category": "food|brand|music|style",
            "sentiment": "love|like|dislike|avoid",
        },
    },
    "decision": {
        "description": (
            "A choice with reasoning. Body should contain the WHY in user's "
            "own words. Append-only by convention — never overwrite past "
            "reasoning, add ## Update YYYY-MM-DD sections."
        ),
        "example_data": {
            "category": "investment|purchase|career|parenting|health",
            "why": "string",
            "amount": "number",
            "currency": "USD|GBP|HKD",
            "who_for": "string",
            "outcome_at": "iso",
            "outcome_sentiment": "good|bad|neutral|tbd",
        },
    },
}


CASUAL_CAPTURE_HINTS = {
    "pizza is so good": "preference (food, sentiment=love)",
    "X was amazing yesterday": "place (rating=5, visited_at=yesterday)",
    "I hate cilantro": "preference (food, sentiment=avoid)",
    "bought 100 ABC at $2 because…": "decision (investment, with `why` in body)",
    "Kepei loves dinosaurs": "preference linked to person",
    "contract ends May 2027": "contract",
    "pick up Kepei 3:30 tomorrow": "todo with due_at",
    "going to the wedding next month": "event (date implied → event)",
}


_CUSTOM_KINDS_CACHE: dict | None = None


def _load_custom_kinds() -> dict:
    """Read /etc/mypa/kinds.yaml at first call. Merge with DEFAULT_KINDS.

    YAML format (per the master plan):
        recipe:
          description: A cooking recipe with ingredients and steps.
          example_data:
            cuisine: string
            servings: number
            prep_min: number
        workout:
          description: A workout session.
          ...

    Cached after first read — restart the service to pick up changes.
    """
    global _CUSTOM_KINDS_CACHE
    if _CUSTOM_KINDS_CACHE is not None:
        return _CUSTOM_KINDS_CACHE
    from pathlib import Path
    custom_path = Path("/etc/mypa/kinds.yaml")
    if not custom_path.is_file():
        _CUSTOM_KINDS_CACHE = {}
        return _CUSTOM_KINDS_CACHE
    try:
        # Use stdlib yaml if available, else parse a minimal subset.
        try:
            import yaml
            with custom_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except ImportError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        _CUSTOM_KINDS_CACHE = data
    except Exception:
        _CUSTOM_KINDS_CACHE = {}
    return _CUSTOM_KINDS_CACHE


def describe_schema() -> dict:
    """Return the kinds catalog + casual-capture mapping hints for tool consumers."""
    # Merge defaults + custom (custom can override default kinds, or add new ones).
    merged = {**DEFAULT_KINDS, **_load_custom_kinds()}
    return {
        "kinds": merged,
        "casual_capture_hints": CASUAL_CAPTURE_HINTS,
        "notes": [
            "kind values are open — supply any string. New kinds need no schema migration.",
            "`body` is rich markdown — capture WHY in user's own words, use ## headings.",
            "Wiki-links like [[person:Kepei]] inside body work in later phases (planned).",
            "For decision items, body is append-only (use ## Update YYYY-MM-DD).",
            "Custom kinds can be added by editing /etc/mypa/kinds.yaml then restarting mypa-api.",
        ],
    }
