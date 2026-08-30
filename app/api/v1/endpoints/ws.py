"""WebSocket channels — spec endpoints #33 and #38.

Authentication note: browsers cannot set an `Authorization` header on a
WebSocket handshake, so the token arrives as a query parameter or in the first
message frame. It is validated BEFORE `accept()`, so an unauthenticated peer
never reaches an open socket.
"""

import asyncio
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.errors import AppError
from app.core.security import decode_token
from app.services import realtime

router = APIRouter(prefix="/ws", tags=["WebSockets"])

# How long a socket waits for a message before sending a keepalive. Proxies and
# mobile networks drop idle connections well inside a delivery, so silence is
# not an option even when nothing is happening.
_KEEPALIVE_SECONDS = 25


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


async def _pump(websocket: WebSocket, channel: str) -> None:
    """Relay a Redis channel to an open socket until the peer goes away.

    The keepalive matters more than it looks: an idle WebSocket through a
    reverse proxy is usually killed within 30–60 seconds, and a vendor tablet
    that quietly lost its socket looks identical to one with no new orders.
    """
    async with realtime.subscribe(channel) as messages:
        stream = messages.__aiter__()
        while True:
            try:
                payload = await asyncio.wait_for(stream.__anext__(), timeout=_KEEPALIVE_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            except StopAsyncIteration:  # pragma: no cover - subscription closed
                break
            await websocket.send_json(payload)


@router.websocket("/orders/{order_id}/live-tracking")
async def order_live_tracking(
    websocket: WebSocket, order_id: uuid.UUID, token: str | None = Query(default=None)
):
    """Spec #33. Streams rider telemetry to the customer.

    Two parties may listen: the customer who placed the order and the rider
    carrying it. The vendor is excluded — they have their own restaurant-scoped
    feed, and where a courier is minute by minute after the food left the
    kitchen is not theirs to watch. Anyone else gets the same close code as a
    non-existent order, because distinguishing them confirms which ids are real.

    A snapshot goes out before the stream, so a client connecting mid-journey
    draws immediately instead of holding a blank map until the next ping. After
    that the channel carries `rider.location` frames from `POST /rider/location`
    and `order.status` frames from the lifecycle, interleaved with `ping`
    keepalives.

    `live_tracking_available: false` in the snapshot means exactly what it says:
    nobody has heard from the rider recently. The socket stays open — the app
    may come back — but nothing invents a position in the meantime.
    """
    payload = await _authenticate(websocket, token)
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Malformed token")
        return

    from app.core.database import SessionLocal
    from app.services import rider_tracking_service

    async with SessionLocal() as db:
        try:
            order = await rider_tracking_service.authorize_order_channel(
                db, uuid.UUID(user_id), order_id
            )
        except AppError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not your order")
            return
        snapshot = await rider_tracking_service.snapshot(db, order)

    await websocket.accept()
    await websocket.send_json(snapshot)
    try:
        await _pump(websocket, realtime.order_channel(str(order_id)))
    except WebSocketDisconnect:
        return


@router.websocket("/vendor/live")
async def vendor_live(websocket: WebSocket, token: str | None = Query(default=None)):
    """Spec #38. Pushes incoming orders to the vendor tablet.

    Subscribes to `vendor:{restaurant_id}:orders`. Exists to bypass HTTP polling
    latency — a vendor learning about an order 30 seconds late is a cold meal,
    and the 60-second auto-decline means half the window can be gone before a
    poll even fires.

    The restaurant is resolved from the token rather than accepted as a
    parameter: a vendor must not be able to subscribe to a competitor's order
    feed by editing a query string.
    """
    payload = await _authenticate(websocket, token)
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Malformed token")
        return

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    async with SessionLocal() as db:
        restaurant_id = await db.scalar(
            select(Restaurant.id).where(Restaurant.owner_id == uuid.UUID(user_id))
        )
    if restaurant_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not a vendor")
        return

    await websocket.accept()
    try:
        await _pump(websocket, realtime.vendor_channel(str(restaurant_id)))
    except WebSocketDisconnect:
        return
