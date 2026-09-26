"""Admin console — Rider Details, Rider Withdrawal, Rider Application and Live
Tracking [EXTENDED].

The roster list and the flags PATCH live in `admin.py` with dispatch. Route
order matters here: `/riders/live` is registered before `/riders/{rider_id}`
so the literal is never parsed as an id.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, Paginated
from app.core.responses import PageMeta, ok, paginated
from app.schemas.requests import (
    PayoutFailRequest,
    PayoutReopenRequest,
    RiderApplicationApproveRequest,
    RiderApplicationRejectRequest,
    RiderIncentiveRequest,
)
from app.services import admin_rider_service, rider_application_service, rider_earnings_service

router = APIRouter(prefix="/admin", tags=["Admin"])


# --- Live tracking ----------------------------------------------------------


@router.get("/riders/live", summary="Riders on shift, with live positions [EXTENDED]")
async def live_riders(
    admin: AdminUser,
    db: DbSession,
    status: Annotated[
        str | None,
        Query(description="AVAILABLE, HEADING_TO_PICKUP or DELIVERING — the filter chips"),
    ] = None,
):
    """**[EXTENDED]** — every rider on shift: position (only if fresh), what
    they are doing, and the orders they hold with the distance to each
    drop-off. Poll every 10–15 seconds while the map is open."""
    riders = await admin_rider_service.live_riders(db, status)
    return ok([r.model_dump() for r in riders], {"total": len(riders)})


# --- Rider details ------------------------------------------------------------


@router.get("/riders/{rider_id}", summary="Rider details [EXTENDED]")
async def get_rider(rider_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """**[EXTENDED]** — Personal Info, Account Information, the earnings tiles
    and documents. The Order tab is `GET /admin/orders?rider_id=`."""
    return ok((await admin_rider_service.get_rider(db, rider_id)).model_dump())


@router.get("/riders/{rider_id}/earnings", summary="Rider earnings [EXTENDED]")
async def rider_earnings(rider_id: uuid.UUID, admin: AdminUser, db: DbSession, page: Paginated):
    """**[EXTENDED]** — the four tiles and one page of days. `meta` paginates
    the days."""
    data, total = await admin_rider_service.rider_earnings(db, rider_id, page.limit, page.offset)
    return ok(
        data.model_dump(),
        PageMeta(
            total=total,
            limit=page.limit,
            offset=page.offset,
            page=(page.offset // page.limit) + 1 if page.limit else 1,
            has_more=page.offset + len(data.days) < total,
        ),
    )


@router.post("/riders/{rider_id}/incentives", summary="Grant an incentive [EXTENDED]")
async def grant_incentive(
    rider_id: uuid.UUID, body: RiderIncentiveRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — a bonus, added to the rider's balance immediately and
    shown in the Incentives column."""
    incentive = await admin_rider_service.grant_incentive(
        db, admin, rider_id, body.amount, body.reason
    )
    await db.commit()
    return ok(incentive.model_dump())


# --- Rider withdrawals ------------------------------------------------------


@router.get("/rider-payouts", summary="Rider withdrawal queue [EXTENDED]")
async def list_rider_payouts(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[
        str | None, Query(description="PROCESSING (default), COMPLETED or FAILED; empty for all")
    ] = "PROCESSING",
    rider_id: Annotated[str | None, Query(description="One rider — the Withdrawal tab")] = None,
    q: Annotated[str | None, Query(description="Reference or rider name")] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
):
    """**[EXTENDED]** — oldest first, with the rider's name and photo."""
    rows, total = await admin_rider_service.list_payouts(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status or None,
        rider_id=rider_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/rider-payouts/{payout_id}/complete", summary="Mark a rider payout paid [EXTENDED]")
async def complete_rider_payout(payout_id: uuid.UUID, admin: AdminUser, db: DbSession):
    payout = await rider_earnings_service.admin_complete(db, payout_id, admin)
    await db.commit()
    return ok((await admin_rider_service.payout_row_by_id(db, payout)).model_dump())


@router.post("/rider-payouts/{payout_id}/fail", summary="Bounce a rider payout [EXTENDED]")
async def fail_rider_payout(
    payout_id: uuid.UUID, body: PayoutFailRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — the amount returns to the rider's balance."""
    payout = await rider_earnings_service.admin_fail(db, payout_id, admin, body.reason)
    await db.commit()
    return ok((await admin_rider_service.payout_row_by_id(db, payout)).model_dump())


@router.post("/rider-payouts/{payout_id}/reopen", summary="Mark a rider payout unpaid [EXTENDED]")
async def reopen_rider_payout(
    payout_id: uuid.UUID, body: PayoutReopenRequest, admin: AdminUser, db: DbSession
):
    """**[EXTENDED]** — COMPLETED back to PROCESSING, with a reason. The
    rider's balance does not change."""
    payout = await rider_earnings_service.admin_reopen(db, payout_id, admin, body.reason)
    await db.commit()
    return ok((await admin_rider_service.payout_row_by_id(db, payout)).model_dump())


# --- Rider applications -----------------------------------------------------


@router.get("/rider-applications", summary="Rider application queue [EXTENDED]")
async def list_rider_applications(
    admin: AdminUser,
    db: DbSession,
    page: Paginated,
    status: Annotated[
        str | None, Query(description="PENDING (default), APPROVED or REJECTED; empty for all")
    ] = "PENDING",
    q: Annotated[str | None, Query(description="Name, phone, email or application number")] = None,
    vehicle_type: Annotated[str | None, Query()] = None,
):
    """**[EXTENDED]** — oldest first: the queue is work, not a feed."""
    rows, total = await rider_application_service.admin_list(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status or None,
        q=q,
        vehicle_type=vehicle_type,
    )
    return paginated(
        [r.model_dump() for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/rider-applications/{application_id}", summary="Rider application [EXTENDED]")
async def get_rider_application(application_id: uuid.UUID, admin: AdminUser, db: DbSession):
    return ok((await rider_application_service.admin_get(db, application_id)).model_dump())


@router.post("/rider-applications/{application_id}/approve", summary="Approve a rider [EXTENDED]")
async def approve_rider_application(
    application_id: uuid.UUID,
    body: RiderApplicationApproveRequest,
    admin: AdminUser,
    db: DbSession,
):
    """**[EXTENDED]** — creates the RIDER account, cleared to ride but off
    shift, with the application's documents on the profile. `409` if the email
    or phone already belongs to another account."""
    result = await rider_application_service.approve(
        db, admin, application_id, body.note, body.password
    )
    await db.commit()
    return ok(result.model_dump())


@router.post("/rider-applications/{application_id}/reject", summary="Reject a rider [EXTENDED]")
async def reject_rider_application(
    application_id: uuid.UUID,
    body: RiderApplicationRejectRequest,
    admin: AdminUser,
    db: DbSession,
):
    """**[EXTENDED]** — the note is emailed to the applicant as the reason."""
    result = await rider_application_service.reject(db, admin, application_id, body.note)
    await db.commit()
    return ok(result.model_dump())
