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
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import (
    ApplicationDecisionRequest,
    AssignRiderRequest,
    PayoutFailRequest,
    RiderCreateRequest,
    RiderUpdateRequest,
    SetCommissionRequest,
    VerifyRestaurantRequest,
)
from app.schemas.rider import RiderAssignment
from app.services import (
    dispatch_service,
    realtime,
    rider_jobs_service,
    rider_roster_service,
    vendor_application_service,
    vendor_finance_service,
    vendor_service,
)

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


@router.patch("/restaurants/{restaurant_id}/commission", summary="Set commission rate [EXTENDED]")
async def set_commission(
    restaurant_id: uuid.UUID, body: SetCommissionRequest, admin: AdminUser, db: DbSession
):
    """Price a restaurant: what the platform keeps of each order's `item_total`.

    Nothing else can write this. Approval does not ask for a rate and the
    vendor is refused it on `PATCH /vendor/profile`, so without this endpoint a
    renegotiation meant hand-written SQL against production.

    **The change is forward-looking.** Each order stores the commission it was
    charged (decision D6), so this cannot rewrite—or repair—what a vendor
    earned on orders already placed. Repricing a restaurant that is mid-service
    applies from the next order in, not to the one being cooked.
    """
    restaurant = await vendor_service.set_commission_rate(
        db, restaurant_id, body.commission_rate
    )
    await db.commit()
    rate = Decimal(str(restaurant.commission_rate))
    return ok(
        {
            "message": f"Commission set to {rate * 100:.2f}%",
            "restaurant_id": str(restaurant.id),
            "name": restaurant.name,
            "commission_rate": rate,
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


# ---------------------------------------------------------------------------
# Riders & dispatch
# ---------------------------------------------------------------------------


@router.get("/riders", summary="The rider roster [EXTENDED]")
async def list_riders(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    online_only: Annotated[bool, Query(description="Only riders currently on shift")] = False,
):
    """Most idle first — the same order dispatch itself picks in, so an operator
    overriding a choice is looking at the list dispatch was choosing from."""
    riders, total = await rider_roster_service.list_riders(
        db, page.limit, page.offset, online_only=online_only
    )
    return paginated(
        [r.model_dump() for r in riders], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/riders", summary="Enrol a rider [EXTENDED]")
async def create_rider(body: RiderCreateRequest, admin: AdminUser, db: DbSession):
    """Riders are created here or not at all.

    `/auth/otp/send` accepts CUSTOMER and VENDOR only — a public endpoint that
    mints couriers would let anyone join the delivery fleet — so enrolment is
    gated on an administrator the same way vendor approval is. The account gets
    no password: there are no rider-facing endpoints for a token to reach yet,
    and a credential with nothing behind it is worse than none.
    """
    rider = await rider_roster_service.create_rider(db, body)
    await db.commit()
    return ok(rider.model_dump())


@router.patch("/riders/{rider_id}", summary="Shift state and clearance [EXTENDED]")
async def update_rider(
    rider_id: uuid.UUID, body: RiderUpdateRequest, admin: AdminUser, db: DbSession
):
    """The two flags dispatch filters on — `is_online` (on shift) and
    `is_verified` (cleared to carry food) — plus the rider's sign-in password.

    `password` is how a rider gets credentials after enrolment, or gets them
    reset. There is no self-service path: `/auth/password/forgot` mails an OTP,
    and a courier account is not something to hand back on the strength of an
    inbox.

    Taking a rider off shift does not touch what they are already holding —
    those orders are in a bag on a motorcycle, and unassigning them would
    strand the customer rather than recall the food.
    """
    rider = await rider_roster_service.set_flags(
        db,
        rider_id,
        is_online=body.is_online,
        is_verified=body.is_verified,
        password=body.password,
    )
    await db.commit()
    return ok(rider.model_dump())


@router.post("/orders/{order_id}/assign-rider", summary="Assign or reassign a rider [EXTENDED]")
async def assign_rider(
    order_id: uuid.UUID, body: AssignRiderRequest, admin: AdminUser, db: DbSession
):
    """The operator override on dispatch — foodpanda's control-centre reassign.

    Orders are assigned automatically when a vendor accepts them, and again at
    READY if the pool was empty the first time. This is what an operator uses
    when the automatic choice is wrong: a rider whose bike broke down, a
    no-show, a manual rebalance. Omit `rider_id` to ask dispatch to pick again
    instead of naming someone.

    The vendor API deliberately has no equivalent. A vendor choosing their own
    rider is not how any delivery platform works, and adding it later would be
    a breaking change to a shipped app.
    """
    order, rider = await dispatch_service.assign_to_order(db, order_id, body.rider_id)
    await db.commit()

    user, profile = await rider_roster_service.get_rider(db, rider.id)
    in_flight = await dispatch_service.count_in_flight(db, rider.id)
    return ok(
        RiderAssignment(
            order_id=str(order.id),
            status=str(order.status),
            rider=rider_roster_service.to_out(user, profile, in_flight),
            chosen_by="operator" if body.rider_id else "dispatch",
            message=f"{rider.full_name or 'The rider'} is now carrying this order",
        ).model_dump()
    )


@router.post("/orders/{order_id}/deliver", summary="Confirm a delivery [EXTENDED]")
async def force_deliver(order_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """The fallback for when the rider cannot mark it themselves — a dead phone,
    an uninstalled app, a dispute resolved in the customer's favour.

    Deliberately separate from `POST /rider/orders/{id}/deliver` rather than a
    shared endpoint with a role switch: the status history records ADMIN as the
    actor, so a delivery nobody was present for is visibly not the same event as
    one a courier confirmed at the door. Use it when the rider genuinely cannot,
    not as the normal path.
    """
    result = await rider_jobs_service.deliver_as_admin(db, admin, order_id)
    await db.commit()
    await realtime.publish_order_status(
        result.order_id, result.restaurant_id, result.status, delivered_at=result.delivered_at
    )
    return ok(result.model_dump())
