"""Restaurants and favorites."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.address import GEO_FROM_LATLNG
from app.models.base import Base, CreatedAtMixin, GeoPoint, Money, TimestampMixin, UUIDPrimaryKey
from app.models.enums import RestaurantStatusType, UserRoleType


class Restaurant(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "restaurants"

    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Constant-valued guard column: combined with the composite FK below, the
    # database refuses any owner whose users.role is not VENDOR.
    owner_role: Mapped[str] = mapped_column(
        UserRoleType, nullable=False, server_default=text("'VENDOR'")
    )

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    cuisine_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    logo_url: Mapped[str | None] = mapped_column(Text)
    cover_image_url: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        RestaurantStatusType, nullable=False, server_default=text("'CLOSED'")
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # Denormalized; recomputed by the worker when a review lands (see docs §7).
    rating_avg: Mapped[float] = mapped_column(
        Numeric(2, 1), nullable=False, server_default=text("0.0")
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    address_line: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[object] = mapped_column(
        GeoPoint,
        Computed(GEO_FROM_LATLNG.format(lng="longitude", lat="latitude"), persisted=True),
        nullable=True,
    )

    delivery_fee_base: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    min_order_amount: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    avg_prep_time_mins: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("20")
    )
    # Mutable — which is exactly why orders snapshot commission_amount (D6).
    commission_rate: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0.0000")
    )

    # {mon..sun: {is_open, opens_at "HH:MM", closes_at "HH:MM"}} — the Business
    # Hour screen. Informational: shown to customers, but nothing flips
    # `status` from it (no scheduler exists), so the manual toggle stays the
    # only thing that actually opens or closes the store.
    business_hours: Mapped[dict | None] = mapped_column(JSONB)

    owner: Mapped["User"] = relationship(back_populates="restaurant", lazy="raise")  # noqa: F821
    categories: Mapped[list["MenuCategory"]] = relationship(  # noqa: F821
        back_populates="restaurant", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("owner_role = 'VENDOR'", name="ck_restaurants_owner_role"),
        ForeignKeyConstraint(
            ["owner_id", "owner_role"],
            ["users.id", "users.role"],
            name="fk_restaurants_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_restaurants_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_restaurants_lng"),
        CheckConstraint(
            "rating_avg BETWEEN 0 AND 5 AND rating_count >= 0", name="ck_restaurants_rating"
        ),
        CheckConstraint(
            "delivery_fee_base >= 0 AND min_order_amount >= 0", name="ck_restaurants_money"
        ),
        CheckConstraint("commission_rate BETWEEN 0 AND 1", name="ck_restaurants_commission"),
        # Decision D1: one storefront per vendor. The code-level hedge lives in
        # app/api/deps.py::get_vendor_restaurant — vendor services must resolve
        # their restaurant through that dependency, never by querying owner_id.
        UniqueConstraint("owner_id", name="uq_restaurants_owner"),
        # The discovery index — GET /restaurants?lat=&lng= via ST_DWithin.
        Index("ix_restaurants_location", "location", postgresql_using="gist"),
        Index(
            "ix_restaurants_open_rating",
            "status",
            text("rating_avg DESC"),
            postgresql_where=text("is_active AND is_verified"),
        ),
        Index(
            "ix_restaurants_name_trgm",
            text("name gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index("ix_restaurants_cuisines", "cuisine_types", postgresql_using="gin"),
    )


class Favorite(Base, CreatedAtMixin):
    """[EXTENDED] N:M — GET/POST /users/me/favorites."""

    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("ix_favorites_restaurant", "restaurant_id"),)
