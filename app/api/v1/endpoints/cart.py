"""Cart & Checkout — spec endpoints #26–28."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CustomerUser, DbSession
from app.core.errors import NotImplementedYetError
from app.schemas.requests import CartItemRequest

router = APIRouter(tags=["Cart & Checkout"])


@router.get("/cart", summary="Get current cart")
async def get_cart(user: CustomerUser, db: DbSession):
    """Spec #26. Prices are recomputed live — the cart stores no price snapshot,
    so a menu change is reflected before the customer commits."""
    raise NotImplementedYetError()


@router.post("/cart/items", summary="Add, update or remove a cart item")
async def modify_cart_item(body: CartItemRequest, user: CustomerUser, db: DbSession):
    """Spec #27. `quantity: 0` removes the line.

    Enforces the single-restaurant rule with a 409. Note the database refuses a
    cross-restaurant item outright via paired composite FKs, so this check
    produces a courteous error for something already impossible to persist.

    Decision D4: when the menu item has variants, `variant_id` is required.
    """
    raise NotImplementedYetError()


@router.get("/checkout/summary", summary="Calculate the final bill")
async def checkout_summary(
    user: CustomerUser,
    db: DbSession,
    address_id: Annotated[str, Query()],
    promo_code: str | None = None,
    tip: Annotated[float, Query(ge=0)] = 0,
):
    """Spec #28. The backend is the single source of truth for pricing.

    Validates availability, then computes item_total, delivery_fee, packaging,
    tax, platform fee, discount and tip. The same arithmetic is re-run and
    persisted at POST /orders, where a CHECK constraint refuses any total that
    does not add up.
    """
    raise NotImplementedYetError()
