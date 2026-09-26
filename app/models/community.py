"""[EXTENDED] Community posts and the reports that flag them for moderation."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKey


class CommunityPost(Base, UUIDPrimaryKey, CreatedAtMixin):
    __tablename__ = "community_posts"

    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_community_posts_author"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    image_urls: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # Optional: the restaurant the post is about ("Loved the biryani from …").
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="SET NULL", name="fk_community_posts_restaurant"),
    )
    # Denormalised count of community_reports rows, so moderation sorts cheaply.
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Removal is soft: the author's post and its reports stay for the record.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_community_posts_removed_by"),
    )
    removal_reason: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        CheckConstraint("report_count >= 0", name="ck_community_posts_reports"),
        Index(
            "ix_community_posts_feed",
            text("created_at DESC"),
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_community_posts_author", "author_id", text("created_at DESC")),
    )


class CommunityReport(Base, CreatedAtMixin):
    """One report per user per post — reporting twice changes nothing."""

    __tablename__ = "community_reports"

    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community_posts.id", ondelete="CASCADE", name="fk_community_reports_post"),
        nullable=False,
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_community_reports_reporter"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (PrimaryKeyConstraint("post_id", "reporter_id", name="pk_community_reports"),)
