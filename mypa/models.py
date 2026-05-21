"""SQLAlchemy 2.0 mapped classes for MyPA.

MVP subset: `items` + `reminders` only. attachments / oauth_tokens /
body_indexed FTS5 column come in later phases when they're actually used.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Item(Base):
    """A single saved record. The `kind` column + JSON `data` column carry all
    kind-specific shape — see master plan §Kinds for the open set.
    `user_id` scopes the row to a single user in the multi-tenant model.
    """

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source", "source_ref", name="uq_items_source_ref"),
        Index("idx_items_kind_status", "kind", "status"),
        Index("idx_items_due", "due_at"),
        Index("idx_items_user", "user_id"),
    )


class Reminder(Base):
    """A scheduled message tied to an item."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(32), default="telegram", nullable=False)
    message: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship(back_populates="reminders")

    __table_args__ = (
        Index("idx_reminders_due", "fire_at"),
        Index("idx_reminders_user", "user_id"),
    )
