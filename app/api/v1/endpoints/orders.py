"""Orders — spec endpoints #29–31."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CustomerUser, DbSession, IdempotencyKey, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import OrderCancelRequest, OrderCreateRequest
from app.services import idempotency, order_service, realtime

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Place an order")
async def create_order(
    body: OrderCreateRequest,
    user: CustomerUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
):
    """Spec #29. Converts the active cart into an order.

    One transaction: reprice, create the order and its line items with full
    price snapshots, record the promo redemption, write the first status-history
    row, and clear the cart. An order that existed while the cart was still
    full would let the customer place it twice.

    `Idempotency-Key` (spec §9) is honoured so a retry over a flaky cellular
    connection replays the original response instead of creating a second
    order. The key is claimed *before* the work runs, so a genuine double
    submit gets a 409 rather than racing.
    """
    replay = await idempotency.begin(
        db, user.id, idempotency_key, "POST /orders", body.model_dump()
    )
    if replay is not None:
        return replay

    order = await order_service.place_order(db, user.id, body)
    response = ok(order.model_dump())
    await idempotency.complete(
        db, user.id, idempotency_key, status.HTTP_201_CREATED, response
    )
    await db.commit()

    # Spec §8 step 5: alert the vendor tablet. Published AFTER the commit —
    # announcing an order that a rollback then erased would put a phantom
    # ticket on the kitchen screen. Best-effort by design: a Redis outage must
    # not fail an order that is already durably placed.
    await realtime.publish(
        realtime.vendor_channel(order.restaurant_id),
        {"type": "order.placed", "order": order.model_dump()},
    )
    return response


@router.get("", summary="Order history")
async def list_orders(
    user: CustomerUser, db: DbSession, page: Paginated, status_filter: str | None = None
):
    """Spec #31. Served by ix_orders_customer_history (customer_id, placed_at DESC).

    `status_filter=ACTIVE` means anything still in flight — the Order screen's
    tab. Spelling it as a status keeps the client from having to enumerate four
    of them.
    """
    orders, total = await order_service.list_orders(
        db, user.id, status=status_filter, limit=page.limit, offset=page.offset
    )
    return paginated(
        [o.model_dump() for o in orders], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{order_id}", summary="Order details")
async def get_order(order_id: uuid.UUID, user: CustomerUser, db: DbSession):
    """**[EXTENDED]** — the Order Details screen: full receipt plus timeline.

    A missing order and someone else's order return the same 404. The
    distinction would let anyone probe for valid ids.
    """
    order = await order_service.order_detail(db, user.id, str(order_id))
    return ok(order.model_dump())


@router.post("/{order_id}/cancel", summary="Cancel an order")
async def cancel_order(
    order_id: uuid.UUID, body: OrderCancelRequest, user: CustomerUser, db: DbSession
):
    """Spec #30. Grace-period cancellation — permitted only while PENDING.

    Once the vendor accepts, food is being cooked; cancelling then is a
    conversation with the restaurant, not an API call, and the 409 says so.
    """
    order = await order_service.cancel_order(db, user.id, str(order_id), body.reason)
    await db.commit()
    return ok(order.model_dump())
