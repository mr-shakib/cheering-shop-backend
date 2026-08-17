"""Administrator operations — [EXTENDED].

The specification defines an ADMIN role in its permission matrix (§7) but no
endpoints for one. Vendor registration is self-service and gated on approval, so
without these a vendor registers and then waits forever with nobody able to let
them through.

Bootstrapping: the first administrator cannot be created through the API — a
public "make me an admin" endpoint would be an obvious hole. Use
`scripts/create_admin.py`, which requires shell access to the server.
"""

import uuid

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import VerifyRestaurantRequest
from app.services import vendor_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/restaurants/pending", summary="Restaurants awaiting approval [EXTENDED]")
async def pending_restaurants(admin: AdminUser, db: DbSession, page: Paginated):
    """Oldest first — this is a work queue, not a feed."""
    restaurants, total = await vendor_service.list_pending(db, page.limit, page.offset)
    return paginated(
        [vendor_service.to_summary(r).model_dump() for r in restaurants],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/restaurants/{restaurant_id}/verify", summary="Approve or suspend [EXTENDED]")
async def verify_restaurant(
    restaurant_id: uuid.UUID, body: VerifyRestaurantRequest, admin: AdminUser, db: DbSession
):
    """Approve a restaurant so customers can find it, or suspend one.

    Suspending is not a delete: the storefront leaves discovery but its menu,
    order history and payout records stay intact. It also forces the store
    CLOSED, so in-flight traffic cannot keep ordering from it.
    """
    restaurant = await vendor_service.set_verified(db, restaurant_id, body.is_verified)
    await db.commit()
    return ok(
        {
            "message": "Restaurant approved" if body.is_verified else "Restaurant suspended",
            "restaurant": vendor_service.to_summary(restaurant).model_dump(),
        }
    )
