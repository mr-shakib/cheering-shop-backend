"""Delivery addresses."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GeoPoint, TimestampMixin, UUIDPrimaryKey
from app.models.enums import AddressTypeType

# The generated-column expression, shared by every geo table so the definition
# exists in exactly one place.
GEO_FROM_LATLNG = "ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326)::geography"


class Address(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "addresses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        AddressTypeType, nullable=False, server_default=text("'OTHER'")
    )
    label: Mapped[str | None] = mapped_column(String(80))
    street_address: Mapped[str] = mapped_column(Text, nullable=False)
    apartment: Mapped[str | None] = mapped_column(String(120))
    landmark: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    contact_phone: Mapped[str | None] = mapped_column(String(20))

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # GENERATED ALWAYS ... STORED — lat/lng and location can never drift apart.
    location: Mapped[object] = mapped_column(
        GeoPoint,
        Computed(GEO_FROM_LATLNG.format(lng="longitude", lat="latitude"), persisted=True),
        nullable=True,
    )

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    user: Mapped["User"] = relationship(back_populates="addresses", lazy="raise")  # noqa: F821

    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_addresses_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_addresses_lng"),
        # Spec §4 says the API must unset other defaults transactionally. This
        # makes a concurrent double-set fail loudly instead of silently leaving
        # a user with two default addresses.
        Index(
            "uq_addresses_one_default", "user_id", unique=True, postgresql_where=text("is_default")
        ),
        Index("ix_addresses_user", "user_id"),
        Index("ix_addresses_location", "location", postgresql_using="gist"),
    )
