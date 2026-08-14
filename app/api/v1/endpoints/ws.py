"""WebSocket channels — spec endpoints #33 and #38.

Authentication note: browsers cannot set an `Authorization` header on a
WebSocket handshake, so the token arrives as a query parameter or in the first
message frame. It is validated BEFORE `accept()`, so an unauthenticated peer
never reaches an open socket.
"""

import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.errors import NotImplementedYetError
from app.core.security import decode_token

router = APIRouter(prefix="/ws", tags=["WebSockets"])


async def _authenticate(websocket: WebSocket, token: str | None) -> dict:
    """Validate the handshake token, closing the socket if it fails."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION)
    try:
        return decode_token(token, expected_type="access")
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION) from None


@router.websocket("/orders/{order_id}/live-tracking")
async def order_live_tracking(
    websocket: WebSocket, order_id: uuid.UUID, token: str | None = Query(default=None)
):
    """Spec #33. Streams rider telemetry to the customer.

    Server -> client payload: `{lat, lng, heading, eta_mins}`.

    Fed by a Redis pub/sub subscription on `order:{id}:track` (decision D2), so
    any API worker can publish and every connected socket receives it — a
    process-local queue would only reach clients on the same worker.
    """
    _ = await _authenticate(websocket, token)
    raise NotImplementedYetError()


@router.websocket("/vendor/live")
async def vendor_live(websocket: WebSocket, token: str | None = Query(default=None)):
    """Spec #38. Pushes incoming orders to the vendor tablet.

    Subscribes to `vendor:{restaurant_id}:orders`. Exists to bypass HTTP polling
    latency — a vendor learning about an order 30 seconds late is a cold meal.
    """
    _ = await _authenticate(websocket, token)
    raise NotImplementedYetError()
