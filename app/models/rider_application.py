"""[EXTENDED] Rider applications — the Rider Application review queue.

The rider twin of `vendor_applications`, with one deliberate difference: no
account exists until an administrator approves. `/auth/otp/send` refuses the
RIDER role because a public endpoint that mints couriers would let anyone join
the fleet; an application is a request to be let in, not a way in.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import VendorApplicationStatusType
from app.models.types import CIText


class RiderApplication(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "rider_applications"

    application_no: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(CIText(), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(40), nullable=False)
    license_number: Mapped[str | None] = mapped_column(String(60))
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    national_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # {kind: url}: nid, driving_license, profile_photo, payout_proof.
    documents: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    payout: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))

    # Same three states as a vendor application, so the same enum.
    status: Mapped[str] = mapped_column(
        VendorApplicationStatusType, nullable=False, server_default=text("'PENDING'")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_rider_applications_reviewed_by"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The RIDER account approval created.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_rider_applications_user"),
    )

    __table_args__ = (
        UniqueConstraint("application_no", name="uq_rider_applications_no"),
        Index("ix_rider_applications_queue", "status", text("created_at ASC")),
        Index("ix_rider_applications_email", "email"),
    )
