"""Declarative base and shared column mixins."""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, DateTime, Float, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared metadata.

    The naming convention deliberately reproduces PostgreSQL's OWN default
    names rather than imposing a prettier scheme. Migration 0001 is raw,
    hand-verified DDL, so the database already contains server-assigned names
    like ``users_email_key`` and ``users_pkey``. A convention that generated
    ``uq_users_email`` instead would make ``alembic check`` report drift on
    every run for constraints that are in fact identical.

    Note ``ck``: the template is pass-through, because every CHECK in these
    models is explicitly named to match the DDL. A template of
    ``ck_%(table_name)s_%(constraint_name)s`` would double-prefix them into
    ``ck_reviews_ck_reviews_restaurant_rating``.
    """

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "%(table_name)s_%(column_0_N_name)s_key",
            "ck": "%(constraint_name)s",
            "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
            "pk": "%(table_name)s_pkey",
        }
    )


class UUIDPrimaryKey:
    """UUIDv4 PK — spec §2 requires these to prevent enumeration."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Money is always BIGINT minor units. Aliased so intent is unmissable at every
# column definition and nobody reaches for Numeric out of habit.
Money = BigInteger

# Coordinates: lat/lng are the source of truth, `location` is GENERATED from
# them in the database (see the Computed() calls on each geo model).
Latitude = Float
Longitude = Float
GeoPoint = Geography(geometry_type="POINT", srid=4326, spatial_index=False)
