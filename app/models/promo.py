"""Promo codes and the redemption ledger."""

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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, Money, UUIDPrimaryKey
from app.models.enums import DiscountTypeType
from app.models.types import CIText


class PromoCode(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Required by GET /checkout/summary?promo_code=XYZ."""

    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(CIText(), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    discount_type: Mapped[str] = mapped_column(DiscountTypeType, nullable=False)
    # paisa when FIXED, basis points when PERCENTAGE (1500 == 15%) — keeping
    # percentages in bps means the whole calculation stays integer-exact.
    discount_value: Mapped[int] = mapped_column(Money, nullable=False)
    max_discount: Mapped[int | None] = mapped_column(Money)
    min_order_amount: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    times_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("valid_until > valid_from", name="ck_promo_window"),
        CheckConstraint("discount_value > 0", name="ck_promo_value"),
        CheckConstraint(
            "times_used >= 0 AND (usage_limit IS NULL OR usage_limit > 0)", name="ck_promo_usage"
        ),
        Index("ix_promo_active", "code", postgresql_where=text("is_active")),
    )


class PromoRedemption(Base, UUIDPrimaryKey, CreatedAtMixin):
    """[EXTENDED] Makes per_user_limit truthful — a counter on promo_codes alone
    cannot tell you *who* redeemed."""

    __tablename__ = "promo_redemptions"

    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    discount_applied: Mapped[int] = mapped_column(Money, nullable=False)

    __table_args__ = (
        UniqueConstraint("promo_code_id", "order_id", name="uq_promo_redemption_order"),
        Index("ix_promo_redemptions_user", "promo_code_id", "user_id"),
    )
