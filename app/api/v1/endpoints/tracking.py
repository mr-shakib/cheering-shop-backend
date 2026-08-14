"""Order tracking — spec endpoint #32."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotImplementedYetError

router = APIRouter(prefix="/orders", tags=["Tracking"])


@router.get("/{order_id}/tracking", summary="Initialise map view")
async def get_tracking(order_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Spec #32. One-shot snapshot to bootstrap the map before the WebSocket
    takes over: current status, rider position, ETA, and the timeline assembled
    from order_status_history."""
    raise NotImplementedYetError()
