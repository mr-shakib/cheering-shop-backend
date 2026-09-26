"""[EXTENDED] Support tickets and their message thread — Support Ticket and
Live Chat.

Any signed-in user (customer, vendor or rider) can open a ticket. EVENT rows in
`support_messages` are the ticket's history ("Assigned to …", "Closed"), kept
in the same table as the conversation so one ordered read renders both.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKey
from app.models.enums import UserRoleType

TICKET_TYPES = (
    "ORDER_ISSUE",
    "RIDER_COMPLAINT",
    "VENDOR_COMPLAINT",
    "PAYMENT",
    "REFUND",
    "ACCOUNT",
    "OTHER",
)
TICKET_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")
TICKET_STATUSES = ("OPEN", "PENDING", "RESOLVED", "CLOSED")


class SupportTicket(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "support_tickets"

    # Human-quotable: "TCK-8800".
    ticket_number: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_support_tickets_user"),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'MEDIUM'")
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'OPEN'"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL", name="fk_support_tickets_order"),
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_support_tickets_assigned_to"),
    )
    # The red dots: set when the other side writes, cleared when this side reads.
    unread_by_staff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    unread_by_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("ticket_number", name="uq_support_tickets_number"),
        CheckConstraint(
            "type IN ('ORDER_ISSUE', 'RIDER_COMPLAINT', 'VENDOR_COMPLAINT', 'PAYMENT', "
            "'REFUND', 'ACCOUNT', 'OTHER')",
            name="ck_support_tickets_type",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')", name="ck_support_tickets_priority"
        ),
        CheckConstraint(
            "status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')", name="ck_support_tickets_status"
        ),
        Index("ix_support_tickets_queue", "status", text("last_message_at DESC")),
        Index("ix_support_tickets_user", "user_id", text("created_at DESC")),
    )


class SupportMessage(Base, UUIDPrimaryKey, CreatedAtMixin):
    __tablename__ = "support_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE", name="fk_support_messages_ticket"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'MESSAGE'"))
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_support_messages_sender"),
    )
    sender_role: Mapped[str | None] = mapped_column(UserRoleType)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"url": "...", "name": "receipt.pdf"}] — uploaded first via /uploads.
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))

    __table_args__ = (
        CheckConstraint("kind IN ('MESSAGE', 'EVENT')", name="ck_support_messages_kind"),
        Index("ix_support_messages_ticket", "ticket_id", "created_at"),
    )
