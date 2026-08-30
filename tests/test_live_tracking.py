"""Live rider position — decision D2 end to end.

Redis on the hot path, a decimated trail in Postgres, a fan-out to the
customer's socket, and GEOSEARCH feeding dispatch. The design was written down
long before anything produced a position; these tests are what say it now does.

The restaurant fixture sits at 23.7936, 90.4064 (Dhanmondi). Coordinates below
are chosen relative to that.
"""

import uuid

import pytest

from tests.test_customer_ordering import _add_burger

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"

KITCHEN = (23.7936, 90.4064)
# ~300 m north of the kitchen, and ~9 km away — outside DISPATCH_SEARCH_RADIUS_M.
NEARBY = (23.7963, 90.4064)
FAR = (23.8750, 90.4064)


@pytest.fixture(autouse=True)
async def clear_rider_geo():
    """Rider positions outlive a test otherwise, and a leftover point puts a
    deleted rider back in dispatch range."""
    from app.core.redis import RIDER_GEO_KEY, get_redis

    async def _wipe():
        redis = get_redis()
        await redis.delete(RIDER_GEO_KEY)
        for pattern in ("rider:*:state", "rider:*:trail_at"):
            keys = [k async for k in redis.scan_iter(pattern)]
            if keys:
                await redis.delete(*keys)

    await _wipe()
    yield
    await _wipe()


def _headers(rider):
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(rider.id), 'RIDER')}"}


async def _place_and_accept(client, kitchen, shopper) -> str:
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = r.json()["data"]["id"]
    await client.post(f"{V1}/vendor/orders/{order_id}/accept", headers=kitchen.headers)
    return order_id


# ---------------------------------------------------------------------------
# Reporting a position
# ---------------------------------------------------------------------------


async def test_a_ping_lands_in_redis_and_the_trail_is_decimated(client, riders):
    """Every ping hits Redis; roughly one in six reaches Postgres. That ratio is
    the whole reason the rider app can ping every five seconds."""
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.core.redis import get_rider_location
    from app.models.rider import RiderLocationPing

    rider = await riders()
    body = {"latitude": NEARBY[0], "longitude": NEARBY[1], "heading": 47, "speed_kph": 18.5}

    r = await client.post(f"{V1}/rider/location", json=body, headers=_headers(rider))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["trail_written"] is True

    # Same decimation window: Redis takes it, Postgres does not.
    r = await client.post(f"{V1}/rider/location", json=body, headers=_headers(rider))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["trail_written"] is False

    position = await get_rider_location(str(rider.id))
    assert position["latitude"] == pytest.approx(NEARBY[0])
    assert position["heading"] == 47

    async with SessionLocal() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(RiderLocationPing)
            .where(RiderLocationPing.rider_id == rider.id)
        )
    assert rows == 1, "two pings in one window must leave one trail point"


async def test_a_ping_syncs_the_last_known_column_dispatch_must_not_read(client, riders):
    """D2 keeps `rider_profiles.current_*` as a convenience for admin views. It
    is written on the decimated clock, not per ping."""

    from app.core.database import SessionLocal
    from app.models.rider import RiderProfile

    rider = await riders()
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1]},
        headers=_headers(rider),
    )

    async with SessionLocal() as session:
        profile = await session.get(RiderProfile, rider.id)
        assert profile.current_latitude == pytest.approx(NEARBY[0])
        assert profile.last_location_at is not None


async def test_only_riders_may_report_a_position(client, shopper, vendor):
    for headers in (shopper.headers, vendor.headers):
        r = await client.post(
            f"{V1}/rider/location", json={"latitude": 23.79, "longitude": 90.40}, headers=headers
        )
        assert r.status_code == 403, r.text


async def test_a_position_off_the_planet_is_refused(client, riders):
    rider = await riders()
    r = await client.post(
        f"{V1}/rider/location",
        json={"latitude": 91.0, "longitude": 90.4064},
        headers=_headers(rider),
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# What the customer sees
# ---------------------------------------------------------------------------


async def test_tracking_shows_the_position_only_while_the_order_is_in_flight(
    client, kitchen, shopper, riders
):
    """Before READY the rider is not yet going anywhere on this order; after
    DELIVERED where they drive next is nobody's business."""
    rider = await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1]},
        headers=_headers(rider),
    )

    # PREPARING — a rider is assigned and reporting, but nothing is en route.
    r = await client.get(f"{V1}/orders/{order_id}/tracking", headers=shopper.headers)
    assert r.json()["data"]["live_tracking_available"] is False
    assert r.json()["data"]["rider_location"] is None
    assert r.json()["data"]["rider"]["id"] == str(rider.id)

    # READY — now the journey has started.
    r = await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)
    pin = r.json()["data"]["handoff_code"]
    r = await client.get(f"{V1}/orders/{order_id}/tracking", headers=shopper.headers)
    data = r.json()["data"]
    assert data["live_tracking_available"] is True
    assert data["rider_location"]["latitude"] == pytest.approx(NEARBY[0])

    # DELIVERED — the dot goes away with the journey.
    await client.post(
        f"{V1}/vendor/orders/{order_id}/handoff",
        json={"rider_pin": pin},
        headers=kitchen.headers,
    )
    await client.post(f"{V1}/rider/orders/{order_id}/deliver", headers=_headers(rider))
    r = await client.get(f"{V1}/orders/{order_id}/tracking", headers=shopper.headers)
    assert r.json()["data"]["live_tracking_available"] is False
    assert r.json()["data"]["rider_location"] is None


async def test_a_rider_who_has_gone_quiet_reports_no_position_at_all(
    client, kitchen, shopper, riders
):
    """A dot frozen where a courier was ten minutes ago reads as someone who
    stopped moving, not as an app that went quiet."""
    from app.core.redis import RIDER_GEO_KEY, get_redis

    rider = await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1]},
        headers=_headers(rider),
    )
    await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)

    # The state hash expires; the geo point deliberately does not.
    redis = get_redis()
    await redis.delete(f"rider:{rider.id}:state")
    assert await redis.zscore(RIDER_GEO_KEY, str(rider.id)) is not None

    r = await client.get(f"{V1}/orders/{order_id}/tracking", headers=shopper.headers)
    assert r.json()["data"]["live_tracking_available"] is False
    assert r.json()["data"]["rider_location"] is None


async def test_a_ping_reaches_the_order_channel(client, kitchen, shopper, riders):
    """The fan-out the WebSocket consumes. Subscribing directly proves the
    message is published without needing a socket to observe it."""
    import asyncio
    import json

    from app.core.redis import get_redis
    from app.services import realtime

    rider = await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)
    await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)

    pubsub = get_redis().pubsub()
    await pubsub.subscribe(realtime.order_channel(order_id))
    await pubsub.get_message(timeout=1)  # the subscribe confirmation

    r = await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1], "heading": 90},
        headers=_headers(rider),
    )
    assert r.json()["data"]["orders_notified"] == 1

    frame = None
    for _ in range(20):
        message = await pubsub.get_message(timeout=0.25)
        if message and message.get("type") == "message":
            frame = json.loads(message["data"])
            break
        await asyncio.sleep(0.05)
    await pubsub.unsubscribe(realtime.order_channel(order_id))
    await pubsub.aclose()

    assert frame is not None, "the ping never reached the order channel"
    assert frame["type"] == "rider.location"
    assert frame["heading"] == 90


# ---------------------------------------------------------------------------
# Who may open the socket
# ---------------------------------------------------------------------------


async def test_the_tracking_channel_admits_the_customer_and_the_rider_only(
    client, kitchen, shopper, riders, vendor
):
    from app.core.database import SessionLocal
    from app.core.errors import AppError
    from app.services.rider import tracking

    rider = await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)

    async with SessionLocal() as db:
        order_uuid = uuid.UUID(order_id)
        assert await tracking.authorize_order_channel(db, shopper.id, order_uuid)
        assert await tracking.authorize_order_channel(db, rider.id, order_uuid)

        # The vendor has their own restaurant feed; a courier's minute-by-minute
        # position after the food left the kitchen is not theirs to watch.
        with pytest.raises(AppError):
            await tracking.authorize_order_channel(db, vendor.user.id, order_uuid)


# ---------------------------------------------------------------------------
# Dispatch, now that positions exist
# ---------------------------------------------------------------------------


async def test_dispatch_prefers_the_nearest_rider_with_a_live_position(
    client, kitchen, shopper, riders
):
    """D2 put nearest-rider matching in Redis GEOSEARCH. This is it working."""
    far = await riders(name="Far away")
    near = await riders(name="Round the corner")
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": FAR[0], "longitude": FAR[1]},
        headers=_headers(far),
    )
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1]},
        headers=_headers(near),
    )

    order_id = await _place_and_accept(client, kitchen, shopper)

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    async with SessionLocal() as session:
        assigned = await session.scalar(
            select(Order.rider_id).where(Order.id == uuid.UUID(order_id))
        )
    assert assigned == near.id, "the nearest live rider should have been chosen"


async def test_dispatch_falls_back_to_load_when_nobody_has_reported_a_position(
    client, kitchen, shopper, riders
):
    """Not a degraded mode: a fleet that has not shipped location reporting, or
    a rider whose phone lost GPS in a basement, still gets work."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    only = await riders(name="No GPS")
    order_id = await _place_and_accept(client, kitchen, shopper)

    async with SessionLocal() as session:
        assigned = await session.scalar(
            select(Order.rider_id).where(Order.id == uuid.UUID(order_id))
        )
    assert assigned == only.id


async def test_the_socket_snapshot_draws_the_map_before_the_first_ping(
    client, kitchen, shopper, riders
):
    """The first frame a subscriber receives. Without it a client joining
    mid-journey holds a blank map until the next ping arrives."""
    from app.core.database import SessionLocal
    from app.models.order import Order
    from app.services.rider import tracking

    rider = await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)
    await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)
    await client.post(
        f"{V1}/rider/location",
        json={"latitude": NEARBY[0], "longitude": NEARBY[1], "heading": 12},
        headers=_headers(rider),
    )

    async with SessionLocal() as db:
        order = await db.get(Order, uuid.UUID(order_id))
        frame = await tracking.snapshot(db, order)

    assert frame["type"] == "tracking.snapshot"
    assert frame["status"] == "READY"
    assert frame["live_tracking_available"] is True
    assert frame["rider_location"]["heading"] == 12
    # JSON-serialisable, because it goes straight out over the socket.
    import json

    json.dumps(frame)


async def test_the_snapshot_is_honest_when_nobody_has_pinged(client, kitchen, shopper, riders):
    from app.core.database import SessionLocal
    from app.models.order import Order
    from app.services.rider import tracking

    await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)
    await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)

    async with SessionLocal() as db:
        frame = await tracking.snapshot(db, await db.get(Order, uuid.UUID(order_id)))

    assert frame["live_tracking_available"] is False
    assert frame["rider_location"] is None


async def test_a_lifecycle_change_reaches_both_the_vendor_and_the_customer(
    client, kitchen, shopper, riders
):
    """One transition, two audiences. A status that reaches one screen and not
    the other is worse than one that reaches neither."""
    import json

    from app.core.redis import get_redis
    from app.services import realtime

    await riders()
    order_id = await _place_and_accept(client, kitchen, shopper)

    pubsub = get_redis().pubsub()
    await pubsub.subscribe(
        realtime.order_channel(order_id),
        realtime.vendor_channel(str(kitchen.restaurant.id)),
    )
    for _ in range(2):
        await pubsub.get_message(timeout=1)  # subscribe confirmations

    await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)

    seen = set()
    for _ in range(30):
        message = await pubsub.get_message(timeout=0.25)
        if message and message.get("type") == "message":
            frame = json.loads(message["data"])
            if frame.get("type") == "order.status":
                seen.add(message["channel"])
    await pubsub.aclose()

    assert seen == {
        realtime.order_channel(order_id),
        realtime.vendor_channel(str(kitchen.restaurant.id)),
    }
