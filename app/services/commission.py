"""Which commission rate applies to a dish — the one rule, in one place.

Commission can be set at three levels, and all three stay available:

    product  →  its section's browse category  →  the restaurant

Each order line is charged at the **most specific rate that is set** (a NULL
means "not set here"). The restaurant always has a rate, so the chain always
ends somewhere. Checkout, the cart and the admin product screens all resolve
through `resolve`, so the rate the console shows is the rate the order charges.

The order still snapshots the resulting amount in `orders.commission_amount`
(D6): changing a rate at any level never restates an order already placed.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.menu import MenuCategory

PRODUCT = "PRODUCT"
CATEGORY = "CATEGORY"
RESTAURANT = "RESTAURANT"


def resolve(
    product_rate: Decimal | float | None,
    category_rate: Decimal | float | None,
    restaurant_rate: Decimal | float,
) -> tuple[float, str]:
    """(rate as a fraction, which level it came from)."""
    if product_rate is not None:
        return float(product_rate), PRODUCT
    if category_rate is not None:
        return float(category_rate), CATEGORY
    return float(restaurant_rate), RESTAURANT


def line_rate(
    product_rate: Decimal | float | None, category_rate: Decimal | float | None
) -> float | None:
    """The rate a cart line carries into `pricing.quote`: the product's, else
    its category's. None means neither is set and the restaurant's applies."""
    for rate in (product_rate, category_rate):
        if rate is not None:
            return float(rate)
    return None


async def section_rates(
    db: AsyncSession, section_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Decimal | None]:
    """Menu section id → its browse category's rate (None when unset or the
    section is unlinked). One query for any number of sections."""
    if not section_ids:
        return {}
    rows = await db.execute(
        select(MenuCategory.id, Category.commission_rate)
        .outerjoin(Category, Category.id == MenuCategory.category_id)
        .where(MenuCategory.id.in_(section_ids))
    )
    return {section_id: rate for section_id, rate in rows.all()}
