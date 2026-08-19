"""Vendor payouts — the Withdraw screens.

One row per withdrawal request. The vendor's **available balance is never
stored**: it is always `sum(vendor payout of DELIVERED orders) - sum(payouts
not FAILED)`, derived at read time. A stored balance is a second copy of the
truth that drifts the first time a payout row and a balance update land in
different transactions; a derived one cannot disagree with the ledger.

Status is PROCESSING at request time. No gateway moves money yet — an
administrator confirms the transfer (COMPLETED) or bounces it (FAILED, which
by the balance formula automatically returns the amount). Same convention as
refunds: recorded, then executed by a human until a gateway lands.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, Money, UUIDPrimaryKey
from app.models.enums import PayoutMethodType, PayoutStatusType


class VendorPayout(Base, UUIDPrimaryKey, CreatedAtMixin):
    __tablename__ = "vendor_payouts"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Human-quotable, printed on the receipt screen — e.g. "CHR64445654".
    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    amount: Mapped[int] = mapped_column(Money, nullable=False)
    method: Mapped[str] = mapped_column(PayoutMethodType, nullable=False)
    # Destination snapshot: the account details as entered for THIS payout.
    # The application's saved payout details are a default, not a constraint.
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(150), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(150))
    branch_name: Mapped[str | None] = mapped_column(String(150))

    status: Mapped[str] = mapped_column(
        PayoutStatusType, nullable=False, server_default=text("'PROCESSING'")
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_vendor_payouts_amount"),
        # History screen: this vendor's payouts, newest first.
        Index("ix_vendor_payouts_restaurant", "restaurant_id", text("created_at DESC")),
        # The finance work queue.
        Index(
            "ix_vendor_payouts_processing",
            text("created_at ASC"),
            postgresql_where=text("status = 'PROCESSING'"),
        ),
    )
