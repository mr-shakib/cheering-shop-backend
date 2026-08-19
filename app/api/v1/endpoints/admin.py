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
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import (
    ApplicationDecisionRequest,
    PayoutFailRequest,
    VerifyRestaurantRequest,
)
from app.services import vendor_application_service, vendor_finance_service, vendor_service

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


# ---------------------------------------------------------------------------
# Vendor partner applications — the review queue behind the application form
# ---------------------------------------------------------------------------


@router.get("/vendor-applications", summary="Partner application queue [EXTENDED]")
async def list_vendor_applications(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        str | None, Query(alias="status", description="PENDING (default), APPROVED or REJECTED")
    ] = "PENDING",
):
    """**[EXTENDED]** — oldest first; the queue defaults to what needs doing.
    Pass `status=` (empty) or another value to see decided applications."""
    applications, total = await vendor_application_service.list_applications(
        db, status_filter or None, page.limit, page.offset
    )
    return paginated(
        [vendor_application_service.to_detail(a).model_dump() for a in applications],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/vendor-applications/{application_id}", summary="Application detail [EXTENDED]")
async def get_vendor_application(application_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — everything the form submitted: owner identity, NID,
    document URLs and payout details. This is the screen a decision is made on."""
    detail = await vendor_application_service.get_detail(db, application_id)
    return ok(detail.model_dump())


@router.post("/vendor-applications/{application_id}/approve", summary="Approve [EXTENDED]")
async def approve_vendor_application(
    application_id: uuid.UUID, body: ApplicationDecisionRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — verifies the restaurant and emails the owner sign-in
    instructions. The store stays CLOSED until the vendor opens it themselves.
    Decisions are final: an approved application cannot be re-decided (use
    `POST /admin/restaurants/{id}/verify` to suspend a live restaurant)."""
    application = await vendor_application_service.approve(db, application_id, admin, body.note)
    await db.commit()
    return ok(
        {
            "message": f"Application {application.application_no} approved",
            "application": vendor_application_service.to_detail(application).model_dump(),
        }
    )


@router.post("/vendor-applications/{application_id}/reject", summary="Reject [EXTENDED]")
async def reject_vendor_application(
    application_id: uuid.UUID, body: ApplicationDecisionRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the note is emailed to the applicant as the reason, so
    write it for them, not for the log."""
    application = await vendor_application_service.reject(db, application_id, admin, body.note)
    await db.commit()
    return ok(
        {
            "message": f"Application {application.application_no} rejected",
            "application": vendor_application_service.to_detail(application).model_dump(),
        }
    )


# ---------------------------------------------------------------------------
# Payouts — the transfer work queue
# ---------------------------------------------------------------------------


@router.get("/payouts", summary="Payout queue [EXTENDED]")
async def list_all_payouts(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status_filter: Annotated[
        str | None, Query(alias="status", description="PROCESSING (default), COMPLETED or FAILED")
    ] = "PROCESSING",
):
    """**[EXTENDED]** — withdrawals awaiting execution, oldest first. Each row
    carries the destination account exactly as the vendor entered it."""
    payouts, total = await vendor_finance_service.admin_list(
        db, status_filter or None, page.limit, page.offset
    )
    return paginated(
        [vendor_finance_service.to_out(p).model_dump() for p in payouts],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/payouts/{payout_id}/complete", summary="Confirm a transfer [EXTENDED]")
async def complete_payout(payout_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — record that the money was actually sent. Irreversible."""
    payout = await vendor_finance_service.admin_complete(db, payout_id, admin)
    await db.commit()
    return ok(
        {
            "message": f"Payout {payout.reference} completed",
            "payout": vendor_finance_service.to_out(payout).model_dump(),
        }
    )


@router.post("/payouts/{payout_id}/fail", summary="Bounce a transfer [EXTENDED]")
async def fail_payout(
    payout_id: uuid.UUID, body: PayoutFailRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the transfer could not be made (wrong account, wallet
    limit). Marking FAILED is itself the refund: the balance formula excludes
    failed rows, so the amount is immediately withdrawable again."""
    payout = await vendor_finance_service.admin_fail(db, payout_id, admin, body.reason)
    await db.commit()
    return ok(
        {
            "message": f"Payout {payout.reference} marked failed",
            "payout": vendor_finance_service.to_out(payout).model_dump(),
        }
    )
