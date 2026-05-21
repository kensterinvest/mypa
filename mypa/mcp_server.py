"""MyPA MCP server (HTTP/SSE transport).

Wires the same service layer the REST API uses, so Claude / agents and
the dashboard see identical data with identical semantics.

Run via systemd:
  uvicorn mypa.mcp_server:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__
from .audit import audit, set_request_context
from .auth import classify_token, TokenScope
from .db import session_factory
from .schemas import ItemCreate, ItemPatch
from . import service
from .settings import settings


# -----------------------------------------------------------------------------
# Build the MCP server with hardened transport security
# -----------------------------------------------------------------------------
s = settings()
mcp = FastMCP(
    name="mypa",
    # Override default streamable HTTP path ("/mcp") to "/sse" so the
    # public URL https://mypa.z-tidus.com/mcp/sse continues to work
    # (Caddy strips the /mcp/ prefix; backend sees /sse). Claude.ai's
    # Custom MCP uses Streamable HTTP transport, NOT classic SSE.
    streamable_http_path="/sse",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[s.public_host, "127.0.0.1", "localhost"],
        allowed_origins=[
            f"https://{s.public_host}",
            "https://claude.ai",
            "https://*.claude.ai",
        ],
    ),
)


def _serialize(item) -> dict:
    """Flatten an Item ORM into the JSON shape returned by tool calls."""
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "body": item.body,
        "status": item.status,
        "priority": item.priority,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "tags": service._str_to_tags(item.tags),
        "data": item.data or {},
        "source": item.source,
        "source_ref": item.source_ref,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _with_session(fn):
    """Decorator that opens a session, calls fn(session), audits, closes."""
    def wrapped(*args, **kwargs):
        Session = session_factory()
        with Session() as db:
            return fn(db, *args, **kwargs)
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


# -----------------------------------------------------------------------------
# Tools — exposed to Claude / agents
# -----------------------------------------------------------------------------

@mcp.tool()
def pa_add(
    kind: str,
    title: str,
    body: str = "",
    data: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    due_at: str | None = None,
    context: str | None = None,
) -> dict:
    """Save a new item to the user's MyPA.

    Use when the user says "remember this", "save", "help me remember",
    "add to my PA", or volunteers a durable fact that fits one of the
    known kinds.

    Pick the kind based on the user's intent:
    - 'preference' for likes/dislikes: "pizza is so good" / "I hate cilantro"
    - 'place' for visited locations with rating: "Pizza Express was amazing"
    - 'decision' for choices with reasoning: "bought 100 ABC at $2 because..."
    - 'person' for people they mention
    - 'event' for dated calendar-style entries (date implied → event)
    - 'reference' / 'contract' / 'account' for durable facts to remember
    - 'todo' / 'reminder' for actions to take
    Call pa_describe_schema() to see all kinds and example data fields.

    `body` is rich markdown — capture the WHY in the user's own words,
    use ## headings (Thesis, Risks, Context), and (later) link to
    other items with [[person:Name]] / [[place:Name]] / [[item:N]].

    `context` is optional — pass the surrounding 1-3 user messages so
    the saved item has conversational context preserved under a
    `## Context` heading.

    Returns the parsed item so the caller can show read-back to the
    user. Save with confidence then surface the result ("Saved as
    `preference` — Pizza"). User can undo via pa_undo_last() within
    30s of the save.
    """
    Session = session_factory()
    payload = ItemCreate(
        kind=kind,
        title=title,
        body=body,
        data=data or {},
        tags=tags or [],
        due_at=datetime.fromisoformat(due_at) if due_at else None,
        context=context,
    )
    with Session() as db:
        item = service.create_item(db, payload)
        result = _serialize(item)
    audit("pa_add", {"kind": kind, "title": title}, f"id={result['id']}")
    return result


@mcp.tool()
def pa_get(item_id: int) -> dict:
    """Fetch a single item by id. Returns full record including body and data{}."""
    Session = session_factory()
    with Session() as db:
        item = service.get_item(db, item_id)
        if item is None:
            audit("pa_get", {"item_id": item_id}, "not found", 1)
            return {"error": "not found", "item_id": item_id}
        result = _serialize(item)
    audit("pa_get", {"item_id": item_id}, "ok")
    return result


@mcp.tool()
def pa_list(
    kind: str | None = None,
    status: str | None = None,
    due_before: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> dict:
    """List items, filtered. Returns items in most-recently-updated order.

    Filters are AND-combined. Use this for "what todos do I have?" /
    "show me my places" / "anything due before Friday?".
    """
    Session = session_factory()
    with Session() as db:
        items = service.list_items(
            db,
            kind=kind,
            status=status,
            due_before=datetime.fromisoformat(due_before) if due_before else None,
            tag=tag,
            limit=limit,
        )
        result = [_serialize(i) for i in items]
    audit(
        "pa_list",
        {"kind": kind, "status": status, "tag": tag, "limit": limit},
        f"{len(result)} items",
    )
    return {"count": len(result), "items": result}


@mcp.tool()
def pa_search(q: str, limit: int = 10) -> dict:
    """Search items by free-text query across title + body + tags.

    Use for "find...", "did I save something about...", "what did
    I record about X". For decision-related questions ("why did I
    buy ABC?") this works too — the reasoning is in the body and
    will match.
    """
    Session = session_factory()
    with Session() as db:
        items = service.search_items(db, q, limit=limit)
        result = [_serialize(i) for i in items]
    audit("pa_search", {"q": q, "limit": limit}, f"{len(result)} hits")
    return {"query": q, "count": len(result), "items": result}


@mcp.tool()
def pa_describe_schema() -> dict:
    """Return the catalog of available kinds with example data{} fields
    plus the casual-capture mapping hints.

    Call this at the start of any session before deciding how to
    interpret the user's phrasing — it ensures you map "pizza is so
    good" to `preference` and "bought ABC at $2" to `decision` correctly.
    """
    result = service.describe_schema()
    audit("pa_describe_schema", {}, f"{len(result['kinds'])} kinds")
    return result


@mcp.tool()
def pa_undo_last(source: str | None = None) -> dict:
    """Soft-undo: delete the most recently created item (optionally
    filtered by source like 'telegram' or 'manual').

    Used after a pa_add when the user says "actually no", "undo that",
    "wrong save", or taps the inline Undo button in Telegram (30-second
    window).
    """
    Session = session_factory()
    with Session() as db:
        item = service.undo_last(db, source=source)
    if item is None:
        audit("pa_undo_last", {"source": source}, "nothing to undo", 1)
        return {"error": "nothing to undo"}
    audit("pa_undo_last", {"source": source}, f"removed id={item.id}")
    return {"removed_id": item.id, "title": item.title, "kind": item.kind}


@mcp.tool()
def pa_delete(item_id: int, confirm: bool = False) -> dict:
    """Delete an item by id. **Destructive — requires confirm=True.**

    Use when the user explicitly says "delete", "remove", "forget", "scrap"
    a specific item they identified. Always show the user what you'll
    delete and require their go-ahead before calling with confirm=True.

    For "undo the last save" use pa_undo_last instead.
    """
    if not confirm:
        audit("pa_delete", {"item_id": item_id, "confirm": confirm}, "blocked: confirm=False", 1)
        return {
            "error": "confirm=True required",
            "detail": "Show the user the item first (call pa_get) and ask them to confirm.",
        }
    Session = session_factory()
    with Session() as db:
        item = service.get_item(db, item_id)
        if item is None:
            audit("pa_delete", {"item_id": item_id}, "not found", 1)
            return {"error": "not found", "item_id": item_id}
        title = item.title
        kind = item.kind
        service.delete_item(db, item_id)
    audit("pa_delete", {"item_id": item_id, "confirm": True}, f"deleted {kind!r} {title!r}")
    return {"deleted_id": item_id, "title": title, "kind": kind}


@mcp.tool()
def pa_update(
    item_id: int,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    due_at: str | None = None,
    tags: list[str] | None = None,
    data: dict[str, Any] | None = None,
    allow_history_rewrite: bool = False,
) -> dict:
    """Partial update on an item. Only the fields you pass get changed.

    Special rule for `kind='decision'` items: `body` is APPEND-ONLY by
    convention. The new body must contain the existing body verbatim
    (substring). Set `allow_history_rewrite=True` to override (audit-logged).

    Use when the user says "change", "update", "edit", "rename", "mark
    as done", "snooze", "reschedule", or wants to add an `## Update
    YYYY-MM-DD` section to a decision.
    """
    from .schemas import ItemPatch
    from datetime import datetime

    patch_kwargs: dict[str, Any] = {"allow_history_rewrite": allow_history_rewrite}
    if title is not None: patch_kwargs["title"] = title
    if body is not None: patch_kwargs["body"] = body
    if status is not None: patch_kwargs["status"] = status
    if priority is not None: patch_kwargs["priority"] = priority
    if due_at is not None: patch_kwargs["due_at"] = datetime.fromisoformat(due_at)
    if tags is not None: patch_kwargs["tags"] = tags
    if data is not None: patch_kwargs["data"] = data

    patch = ItemPatch(**patch_kwargs)
    Session = session_factory()
    try:
        with Session() as db:
            item = service.update_item(db, item_id, patch)
    except ValueError as e:
        audit("pa_update", {"item_id": item_id}, f"rejected: {e}", 1)
        return {"error": str(e)}
    if item is None:
        audit("pa_update", {"item_id": item_id}, "not found", 1)
        return {"error": "not found", "item_id": item_id}
    audit("pa_update", {"item_id": item_id, "fields": list(patch_kwargs.keys())}, "updated")
    return _serialize(item)


@mcp.tool()
def pa_complete(item_id: int) -> dict:
    """Mark an item as done. Sets status='done' and completed_at=now.

    Use when the user says "I did X", "X is done", "completed X", "finished X",
    "mark X as done", or anything that signals an open todo / task is now complete.
    """
    Session = session_factory()
    with Session() as db:
        item = service.complete_item(db, item_id)
    if item is None:
        audit("pa_complete", {"item_id": item_id}, "not found", 1)
        return {"error": "not found", "item_id": item_id}
    audit("pa_complete", {"item_id": item_id}, "completed")
    return _serialize(item)


@mcp.tool()
def pa_add_reminder(item_id: int, fire_at: str, message: str | None = None) -> dict:
    """Schedule a reminder for an item. The reminder fires via Telegram
    once the Phase 2 worker is live (not yet). Stored regardless so it'll
    fire as soon as the worker comes online.

    `fire_at` is ISO 8601 (e.g. "2026-05-22T15:30:00+01:00").
    Use when the user says "remind me", "alert me", "tell me at", "ping me".
    """
    from datetime import datetime
    Session = session_factory()
    with Session() as db:
        r = service.add_reminder(
            db, item_id=item_id,
            fire_at=datetime.fromisoformat(fire_at),
            message=message,
            channel="telegram",
        )
    if r is None:
        audit("pa_add_reminder", {"item_id": item_id, "fire_at": fire_at}, "item not found", 1)
        return {"error": "item not found", "item_id": item_id}
    audit("pa_add_reminder", {"item_id": item_id, "fire_at": fire_at}, f"reminder id={r.id}")
    return {
        "reminder_id": r.id,
        "item_id": r.item_id,
        "fire_at": r.fire_at.isoformat(),
        "message": r.message,
        "channel": r.channel,
        "note": "Reminder stored. Telegram delivery worker not yet active — will fire once Phase 2 ships.",
    }


# -----------------------------------------------------------------------------
# Outer FastAPI app with bearer auth — same shape as admin-mcp
# -----------------------------------------------------------------------------

# Build the Streamable HTTP MCP app once at import; reuse its lifespan.
_mcp_app = mcp.streamable_http_app()


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    """Delegate startup/shutdown to the inner MCP app — needed for Streamable
    HTTP's session manager task group to be initialized.
    """
    async with _mcp_app.router.lifespan_context(_mcp_app):
        yield


app = FastAPI(title="MyPA-MCP", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    scope = classify_token(request.headers.get("authorization", ""))
    if scope is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    # MCP supports both RW and RO scopes; service-level checks restrict writes
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "?")
    )
    set_request_context(client_ip, scope.value)
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mypa-mcp", "version": __version__}


# Mount the Streamable HTTP transport (what Claude.ai uses).
app.mount("/", _mcp_app)
