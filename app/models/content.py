"""[EXTENDED] Reels and app banners — media the apps show that is not a menu."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Reel(Base, UUIDPrimaryKey, TimestampMixin):
    """A short video a restaurant posts; the customer Reels feed."""

    __tablename__ = "reels"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE", name="fk_reels_restaurant"),
        nullable=False,
    )
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(String(300))
    # Reported by the uploading client, which has the file; the server never
    # sees the bytes (uploads go straight to R2).
    duration_seconds: Mapped[int | None] = mapped_column(SmallInteger)
    # Optional: the dish the video shows, so the app can open it directly.
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="SET NULL", name="fk_reels_menu_item"),
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_reels_uploaded_by"),
    )
    # Moderation: hidden reels leave the feed but stay for the vendor to see.
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hidden_reason: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0", name="ck_reels_duration"
        ),
        Index("ix_reels_feed", text("created_at DESC"), postgresql_where=text("NOT is_hidden")),
        Index("ix_reels_restaurant", "restaurant_id", text("created_at DESC")),
    )


class AppBanner(Base, UUIDPrimaryKey, TimestampMixin):
    """A banner the apps show at a `placement` (HOME by default), in
    `sort_order`, while active and inside its optional time window."""

    __tablename__ = "app_banners"

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    # IMAGE (png/jpg/webp), GIF, or LOTTIE (a Lottie JSON animation).
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)
    placement: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'HOME'")
    )
    # What a tap opens: nothing, a restaurant (id), a category (slug) or a URL.
    action_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'NONE'")
    )
    action_value: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_app_banners_created_by"),
    )

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('IMAGE', 'GIF', 'LOTTIE')", name="ck_app_banners_media_type"
        ),
        CheckConstraint(
            "action_type IN ('NONE', 'RESTAURANT', 'CATEGORY', 'URL') "
            "AND (action_type = 'NONE' OR action_value IS NOT NULL)",
            name="ck_app_banners_action",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="ck_app_banners_window",
        ),
        Index(
            "ix_app_banners_placement",
            "placement",
            "sort_order",
            postgresql_where=text("is_active"),
        ),
    )
