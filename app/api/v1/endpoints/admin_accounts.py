"""Admin console — Customers, and blocking an account [EXTENDED]."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import UserStatusRequest
from app.services import admin_account_service
from app.services.admin.common import EXPORT_MAX_ROWS, csv_response

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/customers", summary="Customer list [EXTENDED]")
async def list_customers(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    q: Annotated[str | None, Query(description="Name, email or phone")] = None,
    status: Annotated[str | None, Query(description="ACTIVE or BLOCKED")] = None,
    format: Annotated[
        Literal["json", "csv"], Query(description=f"csv downloads up to {EXPORT_MAX_ROWS} rows")
    ] = "json",
):
    """**[EXTENDED]** — newest sign-ups first, with order count and lifetime
    spend (delivered orders only)."""
    csv = format == "csv"
    rows, total = await admin_account_service.list_customers(
        db,
        limit=EXPORT_MAX_ROWS if csv else page.limit,
        offset=0 if csv else page.offset,
        q=q,
        status=status,
    )
    if csv:
        return csv_response(rows, "customers.csv")
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/customers/{customer_id}", summary="Customer details [EXTENDED]")
async def get_customer(customer_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — profile and the Statics cards. The Recent orders table
    is `GET /admin/orders?customer_id=`."""
    detail = await admin_account_service.get_customer(db, customer_id)
    return ok(detail.model_dump())


@router.patch("/users/{user_id}/status", summary="Block or unblock an account [EXTENDED]")
async def set_user_status(
    user_id: uuid.UUID, body: UserStatusRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — customers and riders. Blocking takes effect on the
    account's next request and revokes every refresh token; a blocked rider is
    also taken off shift so dispatch stops choosing them. Vendors are
    suspended through `POST /admin/restaurants/{id}/verify` instead, which is
    what removes their storefront from discovery."""
    result = await admin_account_service.set_status(db, admin, user_id, body.is_active)
    await db.commit()
    return ok(result.model_dump())
