"""Admin console — the Orders screen and the order drawer [EXTENDED].

Assigning a rider and confirming a delivery predate this module and stay in
`admin.py` with the rest of dispatch; this file is the table, the drawer, and
the two money-facing actions on it.
"""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import AdminOrderCancelRequest, AdminOrderRefundRequest
from app.services import admin_order_service, realtime
from app.services.admin.common import EXPORT_MAX_ROWS, csv_response

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/orders", summary="Every order on the platform [EXTENDED]")
async def list_orders(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[
        str | None,
        Query(description="A status, a comma list, or a tab: NEW, PREPARING, COMPLETE, ACTIVE"),
    ] = None,
    payment_method: Annotated[str | None, Query(description="COD, WALLET, BKASH or CARD")] = None,
    date_from: Annotated[date | None, Query(description="Placed on or after (UTC day)")] = None,
    date_to: Annotated[date | None, Query(description="Placed on or before (UTC day)")] = None,
    q: Annotated[
        str | None, Query(description="Order number, customer name or phone, vendor name")
    ] = None,
    customer_id: Annotated[str | None, Query(description="One customer's orders")] = None,
    restaurant_id: Annotated[str | None, Query(description="One vendor's orders")] = None,
    rider_id: Annotated[str | None, Query(description="One rider's orders")] = None,
    awaiting_rider: Annotated[
        bool, Query(description="Only accepted orders no rider has taken yet")
    ] = False,
    format: Annotated[
        Literal["json", "csv"], Query(description=f"csv downloads up to {EXPORT_MAX_ROWS} rows")
    ] = "json",
):
    """**[EXTENDED]** — newest first. The customer, vendor and rider profile
    tabs are this endpoint with an id filter, so every order list in the
    console has the same columns and the same filters."""
    csv = format == "csv"
    rows, total = await admin_order_service.list_orders(
        db,
        limit=EXPORT_MAX_ROWS if csv else page.limit,
        offset=0 if csv else page.offset,
        status=status,
        payment_method=payment_method,
        date_from=date_from,
        date_to=date_to,
        q=q,
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        rider_id=rider_id,
        awaiting_rider=awaiting_rider,
    )
    if csv:
        return csv_response(rows, "orders.csv")
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/orders/{order_id}", summary="The order drawer [EXTENDED]")
async def get_order(order_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — timeline, the three parties, money including the
    platform's commission, line items, the rider's live position while in
    flight, and `actions` saying which drawer buttons will succeed."""
    detail = await admin_order_service.get_detail(db, order_id)
    return ok(detail.model_dump())


@router.post("/orders/{order_id}/cancel", summary="Cancel an order [EXTENDED]")
async def cancel_order(
    order_id: uuid.UUID, body: AdminOrderCancelRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — PENDING, PREPARING or READY only: once a rider has the
    food it can only be delivered. A paid order is refunded in the same step.
    The customer and the vendor tablet are told over their live channels."""
    detail = await admin_order_service.cancel_order(db, admin, order_id, body.reason)
    await db.commit()
    await realtime.publish_order_status(
        detail.id, detail.restaurant_id, detail.status, cancelled_by="ADMIN"
    )
    return ok(detail.model_dump())


@router.post("/orders/{order_id}/refund", summary="Refund an order [EXTENDED]")
async def refund_order(
    order_id: uuid.UUID, body: AdminOrderRefundRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — records that a PAID order's money is owed back, with
    who did it and why. Does not cancel: a delivered order with a missing item
    stays delivered. No gateway is wired up, so the transfer itself happens
    outside the platform, as payouts do."""
    detail = await admin_order_service.refund_order(db, admin, order_id, body.reason)
    await db.commit()
    return ok(detail.model_dump())
