"""Vendor partner applications.

One row per submitted application — the thing an administrator actually reviews.

The application is a **snapshot**, deliberately denormalised from the user and
restaurant rows it creates. An admin approving "Kolpatha Restaurant" needs to
see exactly what was submitted, and the vendor editing their storefront later
must not silently rewrite the record that approval was based on.

`application_no` (``PTN-88291``) is the reference shown to the applicant and
read over the phone to support. It is deliberately not the UUID: a human cannot
transcribe a UUID, and the public status endpoint keys on this value plus the
owner's email so the row id is never exposed.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import VendorApplicationStatusType
from app.models.types import CIText


class VendorApplication(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "vendor_applications"

    application_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    # The account and storefront created at submission. CASCADE on both: the
    # application is meaningless without them, and the test/GDPR cleanup path
    # deletes the restaurant first.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )

    # --- Business information (form step 1) --------------------------------
    business_name: Mapped[str] = mapped_column(String(180), nullable=False)
    business_type: Mapped[str] = mapped_column(String(40), nullable=False)
    business_category: Mapped[str] = mapped_column(String(80), nullable=False)
    branch_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    cuisine_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )

    # --- Location (form step 2) --------------------------------------------
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # --- Owner information (form step 3) -----------------------------------
    owner_full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    owner_email: Mapped[str] = mapped_column(CIText(), nullable=False)
    owner_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    national_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Documents & payout (form step 4) ----------------------------------
    # {kind: url} — kinds are validated at the schema boundary, but JSONB keeps
    # adding a document type a code change rather than a migration.
    documents: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    # Bank or mobile-wallet payout details. Free-shaped for the same reason.
    payout: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))

    agreed_to_terms: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # --- Review -------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        VendorApplicationStatusType, nullable=False, server_default=text("'PENDING'")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("branch_count >= 1", name="ck_vendor_applications_branches"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_vendor_applications_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_vendor_applications_lng"),
        CheckConstraint("agreed_to_terms", name="ck_vendor_applications_terms"),
        # The admin queue: pending applications, oldest first.
        Index(
            "ix_vendor_applications_queue",
            "status",
            text("created_at ASC"),
        ),
        Index("ix_vendor_applications_owner_email", "owner_email"),
    )
