"""Pydantic request/response shapes for the REST + MCP layers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ItemCreate(BaseModel):
    """Create payload for POST /items and pa_add()."""

    kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    status: str = "open"
    source: str = "manual"
    source_ref: str | None = None
    context: str | None = Field(
        default=None,
        description="Optional surrounding conversation; appended to body under ## Context",
    )


class ItemPatch(BaseModel):
    """Partial update payload."""

    title: str | None = None
    body: str | None = None
    data: dict[str, Any] | None = None
    tags: list[str] | None = None
    due_at: datetime | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    allow_history_rewrite: bool = Field(
        default=False,
        description="For decision-kind items: must be true to allow body shrinkage",
    )


class ItemOut(BaseModel):
    """Response shape — flat for REST and MCP both."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body: str
    status: str
    priority: int
    due_at: datetime | None
    tags: list[str]
    data: dict[str, Any]
    source: str
    source_ref: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ReminderCreate(BaseModel):
    fire_at: datetime
    message: str | None = None
    channel: str = "telegram"


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    fire_at: datetime
    fired_at: datetime | None
    channel: str
    message: str | None
