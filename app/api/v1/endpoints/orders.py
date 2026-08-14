"""Orders — spec endpoints #29–31."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CustomerUser, DbSession, IdempotencyKey, Paginated
from app.core.errors import NotImplementedYetError
from app.schemas.requests import OrderCancelRequest, OrderCreateRequest

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Place an order")
async def create_order(
    body: OrderCreateRequest,
    user: CustomerUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
):
    """Spec #29. Converts the active cart into an order.

    Transactionally: reprice, create order + line items with full price
    snapshots, clear the cart, schedule the 60s auto-decline task, and publish
    to the vendor's WebSocket channel.

    Requires an `Idempotency-Key` header (spec §9) so a retry over a flaky
    cellular connection cannot create a second order.
    """
    raise NotImplementedYetError()


@router.get("", summary="Order history")
async def list_orders(
    user: CustomerUser, db: DbSession, page: Paginated, status_filter: str | None = None
):
    """Spec #31. Served by ix_orders_customer_history (customer_id, placed_at DESC)."""
    raise NotImplementedYetError()


@router.post("/{order_id}/cancel", summary="Cancel an order")
async def cancel_order(
    order_id: uuid.UUID, body: OrderCancelRequest, user: CustomerUser, db: DbSession
):
    """Spec #30. Grace-period cancellation — permitted only while PENDING."""
    raise NotImplementedYetError()
