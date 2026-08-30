"""The rider app — [EXTENDED].

The specification names a RIDER in its permission matrix (§7), hangs
``orders.rider_id`` off every order, and describes live GPS and rider earnings,
but defines no endpoint a rider can call. That gap had a concrete cost:
``PICKED_UP -> DELIVERED`` was the one transition nothing in the system could
perform, so every order stopped a step short of done and everything derived
from a delivered order — earnings, payouts, reviews — was unreachable.

Riders are enrolled by an administrator (`POST /admin/riders`) and sign in at
`/auth/login` with the password issued there. There is no rider self-signup:
`/auth/otp/send` accepts CUSTOMER and VENDOR only, deliberately.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, Paginated, RiderUser
from app.core.responses import ok, paginated
from app.schemas.requests import RiderLocationRequest, RiderShiftRequest
from app.services import (
    realtime,
    rider_jobs_service,
    rider_roster_service,
    rider_tracking_service,
)

router = APIRouter(prefix="/rider", tags=["Rider"])


@router.get("/orders", summary="My jobs [EXTENDED]")
async def list_jobs(
    rider: RiderUser,
    db: DbSession,
    page: Paginated,
    tab: Annotated[str, Query(description="ACTIVE or COMPLETE")] = "ACTIVE",
):
    """The two tabs a courier screen has: what I am carrying, what I finished.

    ACTIVE runs oldest first — the job accepted longest ago is the one going
    cold. COMPLETE runs newest first, because that is a history, not a queue.
    A cancelled order appears in neither: it is gone, and filing it under
    completed would credit a delivery that never happened.
    """
    jobs, total = await rider_jobs_service.list_jobs(db, rider.id, page.limit, page.offset, tab)
    return paginated(
        [j.model_dump() for j in jobs], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/orders/{order_id}", summary="One job [EXTENDED]")
async def job_detail(order_id: uuid.UUID, rider: RiderUser, db: DbSession):
    """Where to collect, what to collect, where it goes — and the handoff code.

    `handoff_code` here is **decision D3 as designed**: the code sits on the
    rider's screen, so a vendor typing it back is evidence that the rider is
    standing at the counter. The vendor still receives it too, because their
    app is being built against that field right now; removing it there is a
    one-line change whenever they are ready, and the verification underneath
    does not move.

    An order belonging to another rider is a 404 rather than a 403 — confirming
    that an id exists tells anyone enumerating them which orders are real.
    """
    job = await rider_jobs_service.job_detail(db, rider.id, order_id)
    return ok(job.model_dump())


@router.post("/orders/{order_id}/deliver", summary="Mark delivered [EXTENDED]")
async def deliver(order_id: uuid.UUID, rider: RiderUser, db: DbSession):
    """PICKED_UP -> DELIVERED. **No body** — the path parameter is the order.

    Only the assigned rider may call this, and only on an order they are
    actually holding: a delivery confirmed by anyone else is an unverifiable
    claim about a doorstep they were not standing at.

    A COD order becomes PAID here, because this is the moment the cash changes
    hands — the one payment this platform genuinely executes. Prepaid methods
    are untouched; flipping them would forge a capture that never occurred.
    """
    result = await rider_jobs_service.deliver(db, rider, order_id)
    await db.commit()
    await realtime.publish_order_status(
        result.order_id, result.restaurant_id, result.status, delivered_at=result.delivered_at
    )
    return ok(result.model_dump())


@router.patch("/me/shift", summary="Go on or off shift [EXTENDED]")
async def set_shift(body: RiderShiftRequest, rider: RiderUser, db: DbSession):
    """Clocking on is what puts a rider in the dispatch pool.

    Writes the same `is_online` column an administrator writes, on purpose: a
    rider who thinks they are on shift while dispatch thinks otherwise is the
    disagreement that shows up as an order nobody collects. Clocking off never
    releases orders already assigned.
    """
    state = await rider_roster_service.set_shift(db, rider, body.is_online)
    await db.commit()
    return ok(state.model_dump())


@router.post("/location", summary="Report my position [EXTENDED]")
async def report_location(body: RiderLocationRequest, rider: RiderUser, db: DbSession):
    """Decision D2's hot path. Send this every `next_ping_seconds` while on shift.

    Three stores on three clocks, because a fleet of 500 riders reporting every
    five seconds is a hundred writes a second and they cannot all be cheap:
    Redis takes every ping and is the only copy anything reads live; the
    Postgres trail and `rider_profiles` take one ping per decimation window,
    which is enough to answer "where were you at 19:40" without generating
    millions of dead tuples a day.

    The response tells you what actually happened — how many customers got the
    update over their socket, whether this one was trailed — so a rider app can
    show an honest "live" indicator instead of assuming.
    """
    result = await rider_tracking_service.record_ping(
        db,
        rider,
        latitude=body.latitude,
        longitude=body.longitude,
        heading=body.heading,
        speed_kph=body.speed_kph,
    )
    await db.commit()
    return ok(result.model_dump())
