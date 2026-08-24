"""Order chat — the Message screen.

Not in the original spec. Scoped deliberately narrowly: one thread per order,
between the customer and whoever is currently serving it, and it closes with
the order. A permanent channel to a stranger's device is a safety problem
rather than a feature, which is why there is no thread table — the order *is*
the thread, and its lifecycle is the channel's lifecycle.

`sender_role` is stored alongside `sender_id` for the same reason the orders
table pairs ids with roles: it lets a composite check assert the sender is
actually a party to this order, rather than trusting the application layer.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey
from app.models.enums import ActorTypeType


class OrderMessage(Base, UUIDPrimaryKey):
    __tablename__ = "order_messages"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    sender_role: Mapped[str] = mapped_column(ActorTypeType, nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    # NULL until the counterparty opens the thread. Per-message rather than a
    # per-thread high-water mark so the ticks on each bubble are exact.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("length(btrim(body)) > 0", name="ck_order_messages_body"),
        # Only the three parties to a delivery can be in the thread. ADMIN is
        # included for support stepping in; SYSTEM for automated notices.
        CheckConstraint(
            "sender_role IN ('CUSTOMER', 'VENDOR', 'RIDER', 'ADMIN', 'SYSTEM')",
            name="ck_order_messages_role",
        ),
        # The thread read: this order's messages, oldest first.
        Index("ix_order_messages_thread", "order_id", "created_at"),
        # The unread badge, which is a count over a tiny partial index rather
        # than a scan of the whole thread.
        Index(
            "ix_order_messages_unread",
            "order_id",
            "sender_role",
            postgresql_where=text("read_at IS NULL"),
        ),
    )


__all__ = ["OrderMessage"]
