"""Reviews — POST /orders/{id}/reviews."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKey


class Review(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Endpoint #35 existed; no entity did.

    Also the only honest source for restaurants.rating_avg, which is
    denormalized and recomputed by the worker when a review lands.
    """

    __tablename__ = "reviews"

    # One review per order — the constraint that stops rating inflation.
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    restaurant_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rider_rating: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        CheckConstraint("restaurant_rating BETWEEN 1 AND 5", name="ck_reviews_restaurant_rating"),
        CheckConstraint(
            "rider_rating IS NULL OR rider_rating BETWEEN 1 AND 5", name="ck_reviews_rider_rating"
        ),
        Index("ix_reviews_restaurant", "restaurant_id", text("created_at DESC")),
        Index("ix_reviews_rider", "rider_id", postgresql_where=text("rider_id IS NOT NULL")),
    )
