"""The order bill — spec #28, and the arithmetic `POST /orders` persists.

**One function computes the quote, and both endpoints call it.** That is the
whole design. `GET /checkout/summary` shows the customer a number and `POST
/orders` charges it; if those two ran separate arithmetic they would eventually
disagree, and the disagreement would surface as a customer being charged
something other than what they agreed to. `orders.ck_orders_total_math` is a
CHECK constraint precisely because a mispriced order must be impossible to
persist, not merely unlikely.

Money is paisa throughout (decision D6). Percentages are basis points so the
whole computation stays in integers — see `core.money.percentage_of`.

What is NOT here: the cart's contents. `quote()` takes already-priced lines, so
it can be unit-tested against fixed inputs without a database, and so the cart
service owns "what is in the cart" while this owns "what it costs".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.money import percentage_of, to_minor

# Earth radius in km. Haversine is accurate to ~0.5% at delivery distances,
# which is far below the granularity of a per-km fee tier.
_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km.

    Deliberately not PostGIS: this runs on two points already in memory during
    checkout, and a round trip to the database to compute it would be slower
    than the arithmetic. Discovery, which ranks thousands of rows, does use
    PostGIS.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class QuoteAddOn:
    """One chosen add-on on a line: `quantity` of them per unit, paisa each."""

    add_on_id: str
    name: str
    price: int
    quantity: int = 1


@dataclass(frozen=True)
class QuoteLine:
    """One priced cart line. All money in paisa."""

    menu_item_id: str
    name: str
    quantity: int
    unit_price: int  # variant price if chosen, else base_price
    add_ons_total: int  # per single unit: Σ price × quantity over `add_ons`
    image_url: str | None = None
    variant_name: str | None = None
    add_on_names: list[str] = field(default_factory=list)
    notes: str | None = None
    add_ons: list[QuoteAddOn] = field(default_factory=list)
    # The product's or its category's rate, resolved by services.commission.
    # None falls back to the restaurant rate passed to `quote`.
    commission_rate: float | None = None

    @property
    def line_total(self) -> int:
        return (self.unit_price + self.add_ons_total) * self.quantity


@dataclass(frozen=True)
class Quote:
    """The complete bill. Every field is paisa."""

    item_total: int
    delivery_fee: int
    packaging_fee: int
    tax_amount: int
    platform_fee: int
    discount: int
    tip: int
    grand_total: int
    commission_amount: int
    distance_km: float
    lines: list[QuoteLine]

    def as_taka(self) -> dict:
        """Wire representation. The spec's example is whole taka, not paisa."""
        from app.core.money import to_major

        return {
            "item_total": to_major(self.item_total),
            "delivery_fee": to_major(self.delivery_fee),
            "packaging_fee": to_major(self.packaging_fee),
            "tax_amount": to_major(self.tax_amount),
            "platform_fee": to_major(self.platform_fee),
            "discount": to_major(self.discount),
            "tip": to_major(self.tip),
            "grand_total": to_major(self.grand_total),
            "distance_km": round(self.distance_km, 2),
        }


def _basis_points(line_rate: float | None, restaurant_rate: float) -> int:
    """Rates are FRACTIONS (Numeric(5,4), CHECK BETWEEN 0 AND 1), so 0.1500 is
    15%. Basis points are rate * 10_000, not * 100."""
    rate = restaurant_rate if line_rate is None else line_rate
    return int(round(rate * 10_000))


@dataclass(frozen=True)
class DeliveryFees:
    """The delivery tariff, in paisa. Built by `services.platform_settings`
    from the Settings screen, falling back to the server configuration."""

    base: int
    per_km: int
    minimum: int = 0
    surcharge: int = 0

    @classmethod
    def from_config(cls) -> DeliveryFees:
        return cls(
            base=to_minor(settings.DELIVERY_FEE_BASE),
            per_km=to_minor(settings.DELIVERY_FEE_PER_KM),
        )


def delivery_fee_minor(
    distance_km: float, item_total: int, fees: DeliveryFees | None = None
) -> int:
    """Flat base covering the first kilometre, then per started km after it.

    Platform-wide. `restaurants.delivery_fee_base` used to feed this and no
    longer does: what a customer pays to be brought food should not depend on
    which kitchen cooked it, and a column every vendor could edit made the
    delivery fee a competitive lever rather than a cost. The column still
    exists — dropping it would need a migration and buys nothing — but nothing
    reads it.

    The threshold promotion waives the whole fee rather than discounting it:
    "free delivery over ৳500" that silently still charges ৳15 is the kind of
    thing customers screenshot.

    `fees` comes from the Settings screen (`services.platform_settings`); None
    means the server configuration. The minimum applies to the distance fee;
    active surcharges (rain, heatwave, high demand) are added on top. The
    free-delivery threshold waives all of it.
    """
    fees = fees or DeliveryFees.from_config()
    threshold = settings.FREE_DELIVERY_THRESHOLD
    if threshold and item_total >= to_minor(threshold):
        return 0
    chargeable_km = max(0.0, distance_km - settings.DELIVERY_FREE_KM)
    # Ceiling, not round: a 1.2 km overage is two started kilometres of rider
    # time, and rounding it down means the platform absorbs the difference on
    # every single order.
    distance_fee = fees.base + fees.per_km * math.ceil(chargeable_km)
    return max(distance_fee, fees.minimum) + fees.surcharge


def delivery_reach_km(budget: int, fees: DeliveryFees) -> float | None:
    """The farthest distance whose delivery fee fits `budget` (paisa) — the
    inverse of `delivery_fee_minor`, for the "max delivery fee" filter.

    None means every distance fits (no per-km charge); a negative value means
    none does. The free-delivery threshold is ignored: it depends on a cart
    the listing screens do not have.
    """
    headroom = budget - fees.surcharge
    if headroom < max(fees.base, fees.minimum):
        return -1.0
    if fees.per_km == 0:
        return None
    return settings.DELIVERY_FREE_KM + (headroom - fees.base) // fees.per_km


def quote(
    lines: list[QuoteLine],
    *,
    distance_km: float,
    commission_rate: float,
    discount: int = 0,
    tip: int = 0,
    delivery: DeliveryFees | None = None,
) -> Quote:
    """Build the bill. Pure arithmetic — no database, no clock, no config reads
    beyond the platform rates.

    Order of operations matters and is deliberate:

    * **Tax applies to food only**, not to delivery, packaging, the platform fee
      or the tip. Taxing our own service fee and then the tax on it is how
      bills become indefensible.
    * **Discount comes off last**, after tax, so a promo never silently reduces
      the tax we remit.
    * **Commission is on `item_total` before discount.** A platform-funded promo
      must not quietly cut the restaurant's earnings — the vendor sold the food
      at its listed price and is owed for it. If a vendor-funded promo type ever
      lands, that is the point at which this line needs a branch, not before.
    * **Commission is per line.** A line carrying its own rate (set on the
      product or its category) is charged at it; the rest at the restaurant's
      `commission_rate`. See `services.commission`.
    """
    item_total = sum(line.line_total for line in lines)
    delivery_fee = delivery_fee_minor(distance_km, item_total, delivery)
    packaging = to_minor(settings.PACKAGING_FEE_PER_ORDER) if lines else 0
    tax = percentage_of(item_total, settings.TAX_BASIS_POINTS)
    platform = percentage_of(item_total, settings.PLATFORM_FEE_BASIS_POINTS)

    # A discount larger than the bill would make grand_total negative, which
    # ck_orders_money_nonneg refuses. Clamping here means an over-generous promo
    # is a free order, never a payout to the customer.
    subtotal = item_total + delivery_fee + packaging + tax + platform + tip
    discount = max(0, min(discount, subtotal))

    return Quote(
        item_total=item_total,
        delivery_fee=delivery_fee,
        packaging_fee=packaging,
        tax_amount=tax,
        platform_fee=platform,
        discount=discount,
        tip=tip,
        grand_total=subtotal - discount,
        commission_amount=sum(
            percentage_of(line.line_total, _basis_points(line.commission_rate, commission_rate))
            for line in lines
        ),
        distance_km=distance_km,
        lines=lines,
    )
