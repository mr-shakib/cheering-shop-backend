"""Order tracking — spec endpoint #32."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.responses import ok
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["Tracking"])


@router.get("/{order_id}/tracking", summary="Initialise map view")
async def get_tracking(order_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Spec #32. One-shot snapshot to bootstrap the map before the WebSocket
    takes over: current status, rider position, ETA, and the timeline assembled
    from order_status_history.

    `rider_location` is null and `live_tracking_available` false until a rider
    client exists to report a position. That is deliberate rather than
    unfinished: interpolating a plausible dot between restaurant and customer
    would show the user a courier who is not there.
    """
    tracking = await order_service.tracking(db, user.id, str(order_id))
    return ok(tracking.model_dump())
