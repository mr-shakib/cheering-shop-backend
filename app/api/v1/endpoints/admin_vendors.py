"""Admin console — Active Vendors and the vendor profile tabs [EXTENDED].

Tab by tab: Store Info is `GET /admin/vendors/{id}`; Order is
`GET /admin/orders?restaurant_id=`; Review and Withdrawal have their own
endpoints below, and the Withdrawal table is `GET /admin/payouts?restaurant_id=`.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import PageMeta, ok, paginated
from app.services import admin_vendor_service
from app.services.admin.common import EXPORT_MAX_ROWS, csv_response

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/vendors", summary="Vendor list [EXTENDED]")
async def list_vendors(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[
        str, Query(description="ACTIVE (verified, the default), SUSPENDED or ALL")
    ] = "ACTIVE",
    q: Annotated[str | None, Query(description="Store name or phone")] = None,
    business_type: Annotated[
        str | None, Query(description="RESTAURANT, GROCERY or PHARMACY")
    ] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    format: Annotated[
        Literal["json", "csv"], Query(description=f"csv downloads up to {EXPORT_MAX_ROWS} rows")
    ] = "json",
):
    """**[EXTENDED]** — highest revenue first, with delivered-order count,
    revenue, rating and product count per vendor."""
    csv = format == "csv"
    rows, total = await admin_vendor_service.list_vendors(
        db,
        limit=EXPORT_MAX_ROWS if csv else page.limit,
        offset=0 if csv else page.offset,
        status=status,
        q=q,
        business_type=business_type,
        min_rating=min_rating,
    )
    if csv:
        return csv_response(rows, "vendors.csv")
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/vendors/{restaurant_id}", summary="Vendor details [EXTENDED]")
async def get_vendor(restaurant_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — the header card and Store Info: owner, NID and
    documents from the partner application, hours, fees and commission."""
    detail = await admin_vendor_service.get_vendor(db, restaurant_id)
    return ok(detail.model_dump())


@router.get("/vendors/{restaurant_id}/reviews", summary="Vendor reviews [EXTENDED]")
async def get_vendor_reviews(
    restaurant_id: uuid.UUID, admin: AdminUser, db: DbSession, page: Paginated
):
    """**[EXTENDED]** — the rating histogram plus one page of reviews, newest
    first. `meta` paginates the reviews; the summary always covers them all."""
    data, total = await admin_vendor_service.get_reviews(db, restaurant_id, page.limit, page.offset)
    return ok(
        data.model_dump(),
        PageMeta(
            total=total,
            limit=page.limit,
            offset=page.offset,
            page=(page.offset // page.limit) + 1 if page.limit else 1,
            has_more=page.offset + len(data.reviews) < total,
        ),
    )


@router.get("/vendors/{restaurant_id}/finance", summary="Vendor money tiles [EXTENDED]")
async def get_vendor_finance(restaurant_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — total earning, commission, paid out, pending and the
    balance the vendor could withdraw now, all from delivered orders and the
    payout ledger."""
    finance = await admin_vendor_service.get_finance(db, restaurant_id)
    return ok(finance.model_dump())
