"""Cart & Checkout — spec endpoints #26–28."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CustomerUser, DbSession
from app.core.responses import ok
from app.schemas.requests import CartItemRequest
from app.services import cart_service, order_service

router = APIRouter(tags=["Cart & Checkout"])


@router.get("/cart", summary="Get current cart")
async def get_cart(user: CustomerUser, db: DbSession):
    """Spec #26. Prices are recomputed live — the cart stores no price snapshot,
    so a menu change is reflected before the customer commits.

    An absent cart returns an empty one rather than a 404: the client renders
    Empty Cart either way, and a status code for an entirely normal state would
    only make it branch.
    """
    cart = await cart_service.get_cart(db, user.id)
    return ok(cart.model_dump())


@router.post("/cart/items", summary="Add, update or remove a cart item")
async def modify_cart_item(body: CartItemRequest, user: CustomerUser, db: DbSession):
    """Spec #27. `quantity: 0` removes the line.

    Enforces the single-restaurant rule with a 409. Note the database refuses a
    cross-restaurant item outright via paired composite FKs, so this check
    produces a courteous error for something already impossible to persist.

    Decision D4: when the menu item has variants, `variant_id` is required.
    Defaulting to the cheapest is how a customer ends up charged for a small
    when the screen said large.
    """
    cart = await cart_service.modify_item(db, user.id, body)
    await db.commit()
    return ok(cart.model_dump())


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

    An invalid promo code does not fail the call: the bill still returns with
    `promo_error` explaining why nothing was applied.
    """
    summary = await order_service.checkout_summary(db, user.id, address_id, promo_code, tip)
    return ok(summary.model_dump())
