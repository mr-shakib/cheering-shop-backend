"""Rider profile and the decimated GPS trail (decision D2)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GeoPoint, TimestampMixin
from app.models.enums import UserRoleType


class RiderProfile(Base, TimestampMixin):
    """[EXTENDED] The spec defines a RIDER role, orders.rider_id, live GPS and
    rider earnings — but never models the rider.

    Decision D2: current_latitude/longitude are LAST KNOWN, synced periodically
    from Redis. They are NOT authoritative and must not be read by dispatch —
    Redis GEOSEARCH owns nearest-rider matching. Deliberately not GiST-indexed:
    an index updated every 5s per rider would generate a dead tuple and an index
    entry per ping (~8.6M/day at 500 riders) and degrade exactly when needed.
    """

    __tablename__ = "rider_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_role: Mapped[str] = mapped_column(
        UserRoleType, nullable=False, server_default=text("'RIDER'")
    )
    vehicle_type: Mapped[str | None] = mapped_column(String(40))
    license_number: Mapped[str | None] = mapped_column(String(60))
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    current_latitude: Mapped[float | None] = mapped_column(Float)
    current_longitude: Mapped[float | None] = mapped_column(Float)
    current_location: Mapped[object] = mapped_column(
        GeoPoint,
        Computed(
            "CASE WHEN current_latitude IS NULL OR current_longitude IS NULL THEN NULL "
            "ELSE ST_SetSRID(ST_MakePoint(current_longitude, current_latitude), 4326)::geography "
            "END",
            persisted=True,
        ),
        nullable=True,
    )
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rating_avg: Mapped[float] = mapped_column(
        Numeric(2, 1), nullable=False, server_default=text("0.0")
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("user_role = 'RIDER'", name="ck_rider_role"),
        ForeignKeyConstraint(
            ["user_id", "user_role"],
            ["users.id", "users.role"],
            name="fk_rider_user",
            ondelete="CASCADE",
        ),
        CheckConstraint("rating_avg BETWEEN 0 AND 5", name="ck_rider_rating"),
        # NOT a GiST index — see the D2 note above. This only serves admin
        # "who is on shift" views, which do not run per ping.
        Index("ix_rider_online", "is_online", postgresql_where=text("is_online")),
    )


class RiderLocationPing(Base):
    """[EXTENDED] The COLD trail — Redis serves the live feed.

    RANGE-partitioned monthly on recorded_at so retention is a DROP PARTITION
    rather than a mass DELETE. SQLAlchemy cannot express PARTITION BY, so the
    partitioning and the child partitions live in migration 0001; this model
    maps the parent table for ORM reads and writes, which route automatically.
    """

    __tablename__ = "rider_location_pings"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[object] = mapped_column(
        GeoPoint,
        Computed("ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography", persisted=True),
        nullable=True,
    )
    heading: Mapped[int | None] = mapped_column(SmallInteger)
    speed_kph: Mapped[float | None] = mapped_column(REAL)
    # Part of the PK because Postgres requires the partition key in it.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_rider_pings_order", "order_id", text("recorded_at DESC")),
        # BRIN on append-only time-ordered data: kilobytes where a B-tree costs
        # gigabytes.
        Index("ix_rider_pings_time", "recorded_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (recorded_at)"},
    )
