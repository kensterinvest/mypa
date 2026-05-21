"""Business logic — shared by REST routes and MCP tools.

Keeping CRUD here (rather than in routes/) means the MCP tool layer can
call the same functions without going through HTTP. One implementation,
two surfaces.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Item, Reminder
from .schemas import ItemCreate, ItemPatch


def _tags_to_str(tags: list[str] | None) -> str:
    if not tags:
        return ""
    cleaned = [t.strip().lower() for t in tags if t and t.strip()]
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


def create_item(db: Session, payload: ItemCreate) -> Item:
    item = Item(
        kind=payload.kind.strip().lower(),
        title=payload.title.strip(),
        body=_append_context(payload.body or "", payload.context),
        status=payload.status,
        priority=payload.priority,
        due_at=payload.due_at,
        tags=_tags_to_str(payload.tags),
        data=payload.data or {},
        source=payload.source,
        source_ref=payload.source_ref,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_item(db: Session, item_id: int) -> Item | None:
    return db.get(Item, item_id)


def list_items(
    db: Session,
    kind: str | None = None,
    status: str | None = None,
    due_before: datetime | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Item]:
    stmt = select(Item)
    if kind:
        stmt = stmt.where(Item.kind == kind.lower())
    if status:
        stmt = stmt.where(Item.status == status)
    if due_before:
        stmt = stmt.where(Item.due_at != None, Item.due_at <= due_before)  # noqa: E711
    if tag:
        stmt = stmt.where(Item.tags.like(f"%{tag.lower()}%"))
    stmt = stmt.order_by(Item.updated_at.desc()).limit(min(limit, 500)).offset(offset)
    return list(db.execute(stmt).scalars())


def search_items(db: Session, q: str, limit: int = 20) -> list[Item]:
    """Simple LIKE-based search across title + body + tags.

    The master plan calls for FTS5; for MVP we use LIKE so we don't need a
    custom tokenizer for wiki-link syntax. Performance is fine up to
    ~100K items. Replace with FTS5 + denormalized body_indexed column
    once that becomes the bottleneck.
    """
    q = q.strip()
    if not q:
        return []
    needle = f"%{q.lower()}%"
    stmt = (
        select(Item)
        .where(
            or_(
                Item.title.ilike(needle),
                Item.body.ilike(needle),
                Item.tags.ilike(needle),
            )
        )
        .order_by(Item.updated_at.desc())
        .limit(min(limit, 200))
    )
    return list(db.execute(stmt).scalars())


def update_item(db: Session, item_id: int, patch: ItemPatch) -> Item | None:
    item = db.get(Item, item_id)
    if item is None:
        return None

    fields = patch.model_dump(exclude_unset=True, exclude={"allow_history_rewrite"})
    if "tags" in fields:
        fields["tags"] = _tags_to_str(fields["tags"])

    # Decision append-only convention — see master plan §Decision affordances
    if (
        item.kind == "decision"
        and "body" in fields
        and not patch.allow_history_rewrite
    ):
        new_body = fields["body"] or ""
        existing = item.body or ""
        # Body must STRICTLY grow (existing content preserved as a prefix)
        if not new_body.startswith(existing):
            raise ValueError(
                "decision body is append-only — set allow_history_rewrite=true to override"
            )

    for k, v in fields.items():
        setattr(item, k, v)
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def complete_item(db: Session, item_id: int) -> Item | None:
    item = db.get(Item, item_id)
    if item is None:
        return None
    item.status = "done"
    item.completed_at = datetime.now(timezone.utc)
    item.updated_at = item.completed_at
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> bool:
    item = db.get(Item, item_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def add_reminder(
    db: Session, item_id: int, fire_at: datetime, message: str | None = None, channel: str = "telegram"
) -> Reminder | None:
    item = db.get(Item, item_id)
    if item is None:
        return None
    r = Reminder(item_id=item_id, fire_at=fire_at, message=message, channel=channel)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def upcoming_reminders(db: Session, limit: int = 20) -> list[Reminder]:
    stmt = (
        select(Reminder)
        .where(Reminder.fired_at == None)  # noqa: E711
        .order_by(Reminder.fire_at.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def undo_last(db: Session, source: str | None = None) -> Item | None:
    """Soft-undo: delete the most recently created item, optionally filtered by source.

    Used by the 30-second undo window after a save (Telegram inline button)
    and by the `/undo` command. Hard-deletes; we don't track tombstones in MVP.
    """
    stmt = select(Item).order_by(Item.created_at.desc()).limit(1)
    if source:
        stmt = stmt.where(Item.source == source)
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        return None
    db.delete(item)
    db.commit()
    return item


# --- kinds registry for pa_describe_schema() ---

DEFAULT_KINDS: dict[str, dict[str, Any]] = {
    "todo": {
        "description": "Action with optional due date.",
        "example_data": {"project": "string", "blocked_by": "item id"},
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
        "description": "Service contract with renewal date.",
        "example_data": {
            "provider": "string",
            "contract_id": "string",
            "start": "iso",
            "end": "iso",
            "monthly_cost": "number",
        },
    },
    "subscription": {
        "description": "Recurring paid service.",
        "example_data": {"provider": "string", "plan": "string", "monthly_cost": "number"},
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


def describe_schema() -> dict:
    """Return the kinds catalog + casual-capture mapping hints for tool consumers."""
    return {
        "kinds": DEFAULT_KINDS,
        "casual_capture_hints": CASUAL_CAPTURE_HINTS,
        "notes": [
            "kind values are open — supply any string. New kinds need no schema migration.",
            "`body` is rich markdown — capture WHY in user's own words, use ## headings.",
            "Wiki-links like [[person:Kepei]] inside body work in later phases (planned).",
            "For decision items, body is append-only (use ## Update YYYY-MM-DD).",
        ],
    }
