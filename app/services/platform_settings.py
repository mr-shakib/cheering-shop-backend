"""The Settings screen: platform configuration an administrator can change
without a deploy.

One row. Every tunable column is nullable, and NULL means "use the server
configuration" (`app.core.config`). That keeps a fresh deployment priced
exactly as before, and lets an administrator hand a value back to the config
by clearing it.

What reads it:

* **Checkout** — `delivery_fees()` feeds `pricing.quote`: base fee, per-km
  fee, a minimum, any dynamic surcharge that is switched on, and the
  priority-delivery fee.
* **Vendor creation** — `default_commission_rate()` is the rate a new
  restaurant starts on, by business type.
"""

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.money import to_major, to_minor
from app.models.platform import PlatformSettings
from app.models.user import User
from app.schemas.admin import PlatformSettingsOut, SurchargeOut
from app.schemas.requests import PlatformSettingsUpdateRequest
from app.services.pricing import DeliveryFees

log = structlog.get_logger()

_COMMISSION_COLUMN = {
    "RESTAURANT": "restaurant_commission_rate",
    "GROCERY": "grocery_commission_rate",
    "PHARMACY": "pharmacy_commission_rate",
}
# Request field -> (column, is money)
_NULLABLE_FIELDS = {
    "app_name": ("app_name", False),
    "support_email": ("support_email", False),
    "support_phone": ("support_phone", False),
    "delivery_base_fee": ("delivery_base_fee", True),
    "delivery_per_km_fee": ("delivery_per_km_fee", True),
    "delivery_min_fee": ("delivery_min_fee", True),
    "priority_delivery_fee": ("priority_delivery_fee", True),
    "restaurant_commission_rate": ("restaurant_commission_rate", False),
    "grocery_commission_rate": ("grocery_commission_rate", False),
    "pharmacy_commission_rate": ("pharmacy_commission_rate", False),
}
_SURCHARGES = ("rain_surcharge", "heatwave_fee", "high_demand_fee")


async def get(db: AsyncSession) -> PlatformSettings:
    """The row, created on first use. Migration 0010 inserts it; this only
    matters for a database built some other way."""
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


def _default_rate() -> float:
    return settings.DEFAULT_COMMISSION_BASIS_POINTS / 10_000


def _rate(value) -> float:
    return float(value) if value is not None else _default_rate()


def fees_from(row: PlatformSettings) -> DeliveryFees:
    surcharge = sum(getattr(row, name) for name in _SURCHARGES if getattr(row, f"{name}_active"))
    config = DeliveryFees.from_config()
    return DeliveryFees(
        base=row.delivery_base_fee if row.delivery_base_fee is not None else config.base,
        per_km=row.delivery_per_km_fee if row.delivery_per_km_fee is not None else config.per_km,
        minimum=row.delivery_min_fee or 0,
        surcharge=surcharge,
        priority=row.priority_delivery_fee
        if row.priority_delivery_fee is not None
        else config.priority,
    )


async def delivery_fees(db: AsyncSession) -> DeliveryFees:
    return fees_from(await get(db))


async def default_commission_rate(db: AsyncSession, business_type: str | None = None) -> float:
    """The rate a new restaurant starts on, from the Settings screen's
    per-type rates, else `DEFAULT_COMMISSION_BASIS_POINTS`.

    Both creation paths (the registration fast path and applications) call
    this rather than letting the column default to 0. A restaurant that exists
    at 0% is not a pricing decision anyone made, and because each order
    snapshots `commission_amount`, every order it takes before someone notices
    is permanently un-billable. A restaurant created without a business type
    (the one-call registration path) is priced as a RESTAURANT."""
    row = await get(db)
    column = _COMMISSION_COLUMN.get(
        (business_type or "RESTAURANT").upper(), "restaurant_commission_rate"
    )
    return _rate(getattr(row, column))


def to_out(row: PlatformSettings) -> PlatformSettingsOut:
    fees = fees_from(row)
    return PlatformSettingsOut(
        app_name=row.app_name or settings.EMAIL_FROM_NAME,
        support_email=row.support_email or settings.EMAIL_REPLY_TO or None,
        support_phone=row.support_phone,
        delivery_base_fee=to_major(fees.base),
        delivery_per_km_fee=to_major(fees.per_km),
        delivery_min_fee=to_major(fees.minimum),
        delivery_free_km=settings.DELIVERY_FREE_KM,
        priority_delivery_fee=to_major(fees.priority),
        restaurant_commission_rate=_rate(row.restaurant_commission_rate),
        grocery_commission_rate=_rate(row.grocery_commission_rate),
        pharmacy_commission_rate=_rate(row.pharmacy_commission_rate),
        rain_surcharge=SurchargeOut(
            amount=to_major(row.rain_surcharge), active=row.rain_surcharge_active
        ),
        heatwave_fee=SurchargeOut(
            amount=to_major(row.heatwave_fee), active=row.heatwave_fee_active
        ),
        high_demand_fee=SurchargeOut(
            amount=to_major(row.high_demand_fee), active=row.high_demand_fee_active
        ),
        active_surcharge_total=to_major(fees.surcharge),
        using_server_defaults=sorted(
            field for field, (column, _) in _NULLABLE_FIELDS.items() if getattr(row, column) is None
        ),
        updated_at=row.updated_at,
        updated_by=str(row.updated_by) if row.updated_by else None,
    )


async def update(
    db: AsyncSession, admin: User, body: PlatformSettingsUpdateRequest
) -> PlatformSettingsOut:
    """PATCH semantics. An explicit null on a nullable field hands it back to
    the server configuration."""
    row = await get(db)
    fields = body.model_dump(exclude_unset=True)
    for field, (column, money) in _NULLABLE_FIELDS.items():
        if field in fields:
            value = fields[field]
            if money and value is not None:
                value = to_minor(value)
            setattr(row, column, value)
    for name in _SURCHARGES:
        if name in fields and fields[name] is not None:
            change = fields[name]
            if change.get("amount") is not None:
                setattr(row, name, to_minor(Decimal(str(change["amount"]))))
            if change.get("active") is not None:
                setattr(row, f"{name}_active", change["active"])
    row.updated_at = datetime.now(UTC)
    row.updated_by = admin.id
    await db.flush()
    log.info("platform_settings_updated", admin_id=str(admin.id), fields=sorted(fields))
    return to_out(row)
