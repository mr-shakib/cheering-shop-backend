"""[EXTENDED] Platform-wide configuration and administrator invitations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, Money, UUIDPrimaryKey
from app.models.types import CIText


class PlatformSettings(Base):
    """The Settings screen. Exactly one row (`id = 1`).

    Every tunable is nullable, and NULL means "use the server configuration"
    (`app.core.config`). Nothing changes price until an administrator saves a
    value, and clearing a value hands it back to the config.
    """

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    app_name: Mapped[str | None] = mapped_column(String(80))
    support_email: Mapped[str | None] = mapped_column(String(254))
    support_phone: Mapped[str | None] = mapped_column(String(20))
    delivery_base_fee: Mapped[int | None] = mapped_column(Money)
    delivery_per_km_fee: Mapped[int | None] = mapped_column(Money)
    delivery_min_fee: Mapped[int | None] = mapped_column(Money)
    restaurant_commission_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    grocery_commission_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    pharmacy_commission_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    rain_surcharge: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    rain_surcharge_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    heatwave_fee: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    heatwave_fee_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    high_demand_fee: Mapped[int] = mapped_column(Money, nullable=False, server_default=text("0"))
    high_demand_fee_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_platform_settings_updated_by"),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
        CheckConstraint(
            "coalesce(delivery_base_fee, 0) >= 0 AND coalesce(delivery_per_km_fee, 0) >= 0 "
            "AND coalesce(delivery_min_fee, 0) >= 0 AND rain_surcharge >= 0 "
            "AND heatwave_fee >= 0 AND high_demand_fee >= 0",
            name="ck_platform_settings_money",
        ),
        CheckConstraint(
            "coalesce(restaurant_commission_rate, 0) BETWEEN 0 AND 1 "
            "AND coalesce(grocery_commission_rate, 0) BETWEEN 0 AND 1 "
            "AND coalesce(pharmacy_commission_rate, 0) BETWEEN 0 AND 1",
            name="ck_platform_settings_rates",
        ),
    )


class AdminInvitation(Base, UUIDPrimaryKey, CreatedAtMixin):
    """The only way to create a second administrator without shell access.

    Only a SHA-256 of the token is stored: a database read must not be enough
    to accept someone else's invitation.
    """

    __tablename__ = "admin_invitations"

    email: Mapped[str] = mapped_column(CIText(), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_admin_invitations_invited_by"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_admin_invitations_accepted_user"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_admin_invitations_token"),
        Index("ix_admin_invitations_email", "email"),
    )
