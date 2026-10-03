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
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import ok, paginated
from app.schemas.requests import (
    ApplicationDecisionRequest,
    AssignRiderRequest,
    CategoryCreateRequest,
    CategoryMergeRequest,
    CategoryUpdateRequest,
    PayoutFailRequest,
    PayoutReopenRequest,
    RiderCreateRequest,
    RiderUpdateRequest,
    SetCommissionRequest,
    VerifyRestaurantRequest,
)
from app.schemas.rider import RiderAssignment
from app.services import (
    admin_rider_service,
    admin_vendor_service,
    category_service,
    dispatch_service,
    order_push,
    realtime,
    rider_jobs_service,
    rider_offer_service,
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
    q: Annotated[
        str | None, Query(description="Store or owner name, phone, or application number")
    ] = None,
    business_type: Annotated[
        str | None, Query(description="RESTAURANT, GROCERY or PHARMACY")
    ] = None,
):
    """**[EXTENDED]** — oldest first; the queue defaults to what needs doing.
    Pass `status=` (empty) or another value to see decided applications."""
    applications, total = await vendor_application_service.list_applications(
        db, status_filter or None, page.limit, page.offset, q=q, business_type=business_type
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
# Browse categories — the chip row on the customer home screen
#
# Vendors populate this table by naming menu sections (see
# services.category_service.resolve), but a category created that way is
# HIDDEN until approved here: the home screen is the platform's most valuable
# surface and must not be writable by anyone who signs up. The rest of the
# job is making the result look like a product — an image on each chip, a
# deliberate order at the top, and one "Burger" where three vendors typed
# three spellings.
# ---------------------------------------------------------------------------


@router.get("/categories", summary="All browse categories, hidden and empty included [EXTENDED]")
async def list_categories(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    pending: Annotated[
        bool,
        Query(description="Only categories awaiting a decision — the review queue"),
    ] = False,
    q: Annotated[str | None, Query(description="Name or alias")] = None,
    kind: Annotated[str | None, Query(description="RESTAURANT or STORE — the tabs")] = None,
    sort: Annotated[
        Literal["default", "name", "-name"],
        Query(description="default = customer order; name = A to Z"),
    ] = "default",
):
    """**[EXTENDED]** — the curation screen. Customer order (pinned, then by
    restaurant count), but nothing filtered: a hidden category and one no
    restaurant sells under yet both appear here, with their counts, because
    those are exactly the rows an operator has decisions to make about.

    `pending=true` narrows it to the review queue: categories a vendor's menu
    section name brought into existence and nobody has decided about. Those
    are invisible to customers until approved, so this is the list that
    matters — anything sitting in it is a vendor whose food is not browsable.
    """
    rows, total = await category_service.admin_list(
        db, page.limit, page.offset, pending_only=pending, q=q, kind=kind, sort=sort
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post(
    "/categories",
    status_code=status.HTTP_201_CREATED,
    summary="Create a browse category [EXTENDED]",
)
async def create_category(body: CategoryCreateRequest, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — add a category deliberately: with an image, pinned,
    and with the spellings vendors will type as `aliases`, before any vendor
    has a section under it. A name another category already answers to —
    as its name, its slug or one of its aliases — is a 409."""
    category = await category_service.admin_create(db, body)
    await db.commit()
    return ok(category.model_dump())


@router.patch("/categories/{category_id}", summary="Curate a category [EXTENDED]")
async def update_category(
    category_id: uuid.UUID, body: CategoryUpdateRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — approve, rename, set the image, pin (`sort_order`) or
    un-pin (`sort_order: null`), hide (`is_active: false`), or replace the
    alias list.

    **Approving a pending category is `{"is_active": true}` here.** Any call
    marks the row reviewed, including one that changes nothing, so an operator
    can also say "I looked, it stays hidden" and have it leave the queue for
    good rather than reappear on every refresh.

    Renaming keeps the slug and records the old name as an alias, so links
    already shared and vendor sections named the old way both still land here.
    Hiding removes the chip everywhere but keeps every section's link, so
    un-hiding restores it exactly.
    """
    category = await category_service.admin_update(db, category_id, body)
    await db.commit()
    return ok(category.model_dump())


@router.delete("/categories/{category_id}", summary="Delete an unused category [EXTENDED]")
async def delete_category(category_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — remove a category no menu section links to.

    409 while sections still point at it: deleting would silently drop those
    restaurants out of the chip. Merge (the sections belong elsewhere) or hide
    (the chip should not show) are the two operations that mean something.
    """
    await category_service.admin_delete(db, category_id)
    await db.commit()
    return ok({"message": "Category deleted", "category_id": str(category_id)})


@router.post("/categories/{category_id}/merge", summary="Merge into another category [EXTENDED]")
async def merge_category(
    category_id: uuid.UUID, body: CategoryMergeRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — fold the category in the path into `into_id`.

    Every menu section moves to the survivor, the survivor learns the old
    name and slug as aliases (so "Burgers" resolves to Burger from now on and
    old links keep working), and the old row is deleted. Returns the survivor.
    """
    category = await category_service.admin_merge(db, category_id, body)
    await db.commit()
    return ok(category.model_dump())


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
    restaurant_id: Annotated[
        str | None, Query(description="One vendor's payouts — the Withdrawal tab")
    ] = None,
    q: Annotated[str | None, Query(description="Payout reference or vendor name")] = None,
    date_from: Annotated[date | None, Query(description="Requested on or after")] = None,
    date_to: Annotated[date | None, Query(description="Requested on or before")] = None,
):
    """**[EXTENDED]** — withdrawals awaiting execution, oldest first. Each row
    carries the destination account exactly as the vendor entered it, and the
    vendor's name. Pass `status=` (empty) for every status."""
    payouts, total = await admin_vendor_service.list_payouts(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status_filter or None,
        restaurant_id=restaurant_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    return paginated(
        [p.model_dump() for p in payouts], total=total, limit=page.limit, offset=page.offset
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


@router.post("/payouts/{payout_id}/reopen", summary="Mark a paid payout unpaid [EXTENDED]")
async def reopen_payout(
    payout_id: uuid.UUID, body: PayoutReopenRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the console's Mark Unpaid: a COMPLETED payout goes back
    to PROCESSING, with who reopened it and why. The vendor's balance does not
    change — money waiting to be sent is deducted exactly as money sent is — so
    reopening cannot let the same amount be withdrawn twice."""
    row = await admin_vendor_service.reopen_payout(db, payout_id, admin, body.reason)
    await db.commit()
    return ok(
        {"message": f"Payout {row.reference} is back in the queue", "payout": row.model_dump()}
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
    q: Annotated[str | None, Query(description="Name, phone or email")] = None,
    vehicle_type: Annotated[str | None, Query(description="e.g. CYCLE, MOTORCYCLE")] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    status: Annotated[
        str | None, Query(description="ACTIVE, SUSPENDED (not cleared) or BLOCKED")
    ] = None,
):
    """On-shift riders first, then most idle — the order dispatch itself picks
    in, so an operator overriding a choice is looking at the list dispatch was
    choosing from. Rows carry phone, vehicle, deliveries and rating."""
    riders, total = await admin_rider_service.list_riders(
        db,
        limit=page.limit,
        offset=page.offset,
        online_only=online_only,
        q=q,
        vehicle_type=vehicle_type,
        min_rating=min_rating,
        status=status,
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


@router.patch("/riders/{rider_id}", summary="Shift, clearance and profile [EXTENDED]")
async def update_rider(
    rider_id: uuid.UUID, body: RiderUpdateRequest, admin: AdminUser, db: DbSession
):
    """The two flags dispatch filters on — `is_online` (on shift) and
    `is_verified` (cleared to carry food) — the rider's sign-in password, and
    the Personal Info fields (name, vehicle, licence, date of birth, NID,
    documents). Returns the full Rider Details view.

    `password` is how a rider gets credentials after enrolment, or gets them
    reset. There is no self-service path: `/auth/password/forgot` mails an OTP,
    and a courier account is not something to hand back on the strength of an
    inbox.

    Taking a rider off shift does not touch what they are already holding —
    those orders are in a bag on a motorcycle, and unassigning them would
    strand the customer rather than recall the food.
    """
    rider = await admin_rider_service.update_rider(db, rider_id, body)
    await db.commit()
    return ok(rider.model_dump())


@router.post("/orders/{order_id}/assign-rider", summary="Assign or reassign a rider [EXTENDED]")
async def assign_rider(
    order_id: uuid.UUID, body: AssignRiderRequest, admin: AdminUser, db: DbSession
):
    """The operator override — foodpanda's control-centre reassign.

    An accepted order is offered to every available rider and the first to
    accept carries it. This is what an operator uses when that does not work
    out: nobody accepted in time, a rider's bike broke down, a no-show. Omit
    `rider_id` to let the platform pick (nearest, else least busy) instead of
    naming someone.

    The vendor API deliberately has no equivalent. A vendor choosing their own
    rider is not how any delivery platform works, and adding it later would be
    a breaking change to a shipped app.
    """
    order, rider = await dispatch_service.assign_to_order(db, order_id, body.rider_id)
    await db.commit()
    # If it was still on offer, take it off every rider's screen.
    await rider_offer_service.announce_taken(order.id, rider.id)

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
async def force_deliver(
    order_id: uuid.UUID, admin: AdminUser, db: DbSession, background: BackgroundTasks
):
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
    background.add_task(order_push.order_status, result.order_id, result.status)
    return ok(result.model_dump())
