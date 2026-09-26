"""[EXTENDED] Notification campaigns and each user's inbox.

A campaign is fanned out into one `user_notifications` row per recipient when
it is sent, in one INSERT … SELECT. The inbox is what the apps read; push is a
best-effort nudge on top, sent only where a device token and push credentials
exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKey

NOTIFICATION_TYPES = ("PROMOTION", "ALERT", "UPDATE")
AUDIENCES = ("CUSTOMER", "VENDOR", "RIDER", "ALL")


class NotificationCampaign(Base, UUIDPrimaryKey, CreatedAtMixin):
    __tablename__ = "notification_campaigns"

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'SCHEDULED'")
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    push_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_notification_campaigns_created_by"),
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('PROMOTION', 'ALERT', 'UPDATE')", name="ck_notification_campaigns_type"
        ),
        CheckConstraint(
            "audience IN ('CUSTOMER', 'VENDOR', 'RIDER', 'ALL')",
            name="ck_notification_campaigns_audience",
        ),
        CheckConstraint(
            "status IN ('SCHEDULED', 'SENT', 'FAILED', 'CANCELLED')",
            name="ck_notification_campaigns_status",
        ),
        Index(
            "ix_notification_campaigns_due",
            "scheduled_for",
            postgresql_where=text("status = 'SCHEDULED'"),
        ),
    )


class UserNotification(Base, UUIDPrimaryKey, CreatedAtMixin):
    __tablename__ = "user_notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_notifications_user"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "notification_campaigns.id", ondelete="CASCADE", name="fk_user_notifications_campaign"
        ),
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_user_notifications_user", "user_id", text("created_at DESC")),)
