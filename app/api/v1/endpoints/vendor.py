"""Vendor Operations — spec endpoints #36–37, #39–46.

Every handler here takes `restaurant: VendorRestaurant` rather than querying
`owner_id`. That is decision D1's hedge: resolution is concentrated in one
dependency, so supporting multi-outlet vendors later costs one migration and one
function body instead of rewriting ten endpoints.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, Paginated, VendorRestaurant, VendorUser
from app.core.errors import NotImplementedYetError
from app.schemas.requests import (
    HandoffRequest,
    MenuItemCreateRequest,
    MenuItemStatusRequest,
    OrderRejectRequest,
    StoreStatusRequest,
)

router = APIRouter(prefix="/vendor", tags=["Vendor"])


@router.patch("/store/status", summary="Open or close the store")
async def set_store_status(body: StoreStatusRequest, restaurant: VendorRestaurant, db: DbSession):
    """Spec #36. Response echoes `restaurant_id` — see the D1 note above."""
    raise NotImplementedYetError()


@router.get("/orders", summary="Incoming order queue")
async def list_vendor_orders(
    restaurant: VendorRestaurant,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
):
    """Spec #37. Served by ix_orders_vendor_queue
    (restaurant_id, status, placed_at DESC)."""
    raise NotImplementedYetError()


@router.post("/orders/{order_id}/accept", summary="Accept an order")
async def accept_order(order_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """Spec #39. PENDING -> PREPARING, and cancels the queued auto-decline task."""
    raise NotImplementedYetError()


@router.post("/orders/{order_id}/reject", summary="Reject an order")
async def reject_order(
    order_id: uuid.UUID, body: OrderRejectRequest, restaurant: VendorRestaurant, db: DbSession
):
    """Spec #40. Cancels the order and triggers refund/rebooking.

    Spec §12 leaves the rebooking policy unresolved — whether the backend
    silently re-places with a nearby vendor or simply refunds and suggests. This
    handler will need that ruling before Step 4 completes it.
    """
    raise NotImplementedYetError()


@router.post("/orders/{order_id}/ready", summary="Mark order ready")
async def mark_ready(order_id: uuid.UUID, restaurant: VendorRestaurant, db: DbSession):
    """Spec #41. PREPARING -> READY.

    Decision D3: this is where the rider PIN is generated and HMAC'd — not at
    order creation, so it does not exist during the whole cooking window.
    """
    raise NotImplementedYetError()


@router.post("/orders/{order_id}/handoff", summary="Verify rider PIN and hand off")
async def handoff_order(
    order_id: uuid.UUID, body: HandoffRequest, restaurant: VendorRestaurant, db: DbSession
):
    """Spec #42. READY -> PICKED_UP. Returns 400 on an invalid PIN.

    Constant-time HMAC comparison with an attempt counter — the counter is what
    actually protects a 4-digit space, since 10,000 candidates fall to brute
    force regardless of how the digest is computed.
    """
    raise NotImplementedYetError()


@router.get("/analytics", summary="Earnings dashboard")
async def vendor_analytics(
    restaurant: VendorRestaurant,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Spec #43. Served by the partial index ix_orders_analytics
    (restaurant_id, delivered_at) WHERE status = 'DELIVERED'.

    Earnings use the per-order `commission_amount` snapshot, never the live
    `restaurants.commission_rate` — otherwise changing a vendor's rate would
    retroactively rewrite historical earnings (decision D6).
    """
    raise NotImplementedYetError()


@router.get("/menu/categories", summary="List menu categories")
async def list_categories(restaurant: VendorRestaurant, db: DbSession):
    """Spec #44."""
    raise NotImplementedYetError()


@router.post("/menu/items", status_code=status.HTTP_201_CREATED, summary="Create a menu item")
async def create_menu_item(
    body: MenuItemCreateRequest, restaurant: VendorRestaurant, db: DbSession
):
    """Spec #45. Creates the item with its variants and add-ons in one
    transaction. The composite FK to menu_categories guarantees the category
    belongs to this vendor's restaurant — a forged category_id cannot smuggle an
    item onto someone else's menu."""
    raise NotImplementedYetError()


@router.patch("/menu/items/{item_id}/status", summary="Toggle item availability")
async def set_menu_item_status(
    item_id: uuid.UUID,
    body: MenuItemStatusRequest,
    restaurant: VendorRestaurant,
    db: DbSession,
):
    """Spec #46. The high-frequency 'sold out' toggle."""
    raise NotImplementedYetError()


_ = VendorUser  # role guard is applied transitively via VendorRestaurant
