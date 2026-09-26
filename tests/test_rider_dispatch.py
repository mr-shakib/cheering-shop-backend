"""Rider dispatch — offers every available rider can accept, the operator
override, the roster behind them — and the PIN reissue they unblock.

Before this module existed nothing wrote ``orders.rider_id``, which made spec
#42 — ``POST /vendor/orders/{id}/handoff`` — unreachable on every real order:
``ck_orders_rider_required`` forbids a PICKED_UP order without a rider, so the
handoff refused rather than violate the constraint. These tests are the proof
that the vendor's handoff screen now completes without anyone touching SQL.
"""

import uuid

import pytest

from tests.test_vendor_api import _seed_order

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


# ---------------------------------------------------------------------------
# Helpers — the `riders` factory fixture lives in conftest.py
# ---------------------------------------------------------------------------


async def _rider_id_of(order_id) -> uuid.UUID | None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    async with SessionLocal() as session:
        return await session.scalar(select(Order.rider_id).where(Order.id == order_id))


def _as_rider(rider) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(rider.id), 'RIDER')}"}


async def _take(client, rider, order_id):
    return await client.post(f"{V1}/rider/offers/{order_id}/accept", headers=_as_rider(rider))


# ---------------------------------------------------------------------------
# Offers — every available rider is asked, the first to accept wins
# ---------------------------------------------------------------------------


async def test_accepting_an_order_offers_it_to_every_available_rider(
    client, vendor, order_customer, riders
):
    """Nobody is chosen for the rider: the order waits for one to take it."""
    one, two = await riders(name="One"), await riders(name="Two")
    off_shift = await riders(is_online=False, name="Off shift")
    not_cleared = await riders(is_verified=False, name="Not cleared")
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")

    r = await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert await _rider_id_of(order.id) is None

    for rider in (one, two):
        r = await client.get(f"{V1}/rider/offers", headers=_as_rider(rider))
        assert r.status_code == 200, r.text
        offer = next(o for o in r.json()["data"] if o["order_id"] == str(order.id))
        assert offer["can_accept"] is True
        assert offer["trip_distance_km"] > 0
    for rider in (off_shift, not_cleared):
        r = await client.get(f"{V1}/rider/offers", headers=_as_rider(rider))
        assert r.status_code == 409, r.text


async def test_the_first_rider_to_accept_gets_the_order(client, vendor, order_customer, riders):
    fast, slow = await riders(name="Fast"), await riders(name="Slow")
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)

    r = await _take(client, fast, order.id)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["order_id"] == str(order.id)
    assert await _rider_id_of(order.id) == fast.id

    r = await _take(client, slow, order.id)
    assert r.status_code == 409, r.text
    assert "no longer available" in r.json()["error"]["message"]
    offers = (await client.get(f"{V1}/rider/offers", headers=_as_rider(slow))).json()["data"]
    assert str(order.id) not in {o["order_id"] for o in offers}


async def test_simultaneous_accepts_produce_exactly_one_winner(
    client, vendor, order_customer, riders
):
    import asyncio

    crowd = [await riders(name=f"Rider {i}") for i in range(5)]
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)

    results = await asyncio.gather(*(_take(client, r, order.id) for r in crowd))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409, 409]
    winner = crowd[[r.status_code for r in results].index(200)]
    assert await _rider_id_of(order.id) == winner.id


async def test_offers_are_announced_and_withdrawn_on_the_rider_channel(
    client, vendor, order_customer, riders
):
    import json

    from app.core.redis import get_redis
    from app.services import realtime

    rider = await riders()
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")

    pubsub = get_redis().pubsub()
    await pubsub.subscribe(realtime.rider_offers_channel())
    await pubsub.get_message(timeout=1)  # subscribe confirmation
    try:
        await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
        await _take(client, rider, order.id)
        frames = []
        for _ in range(10):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message:
                frame = json.loads(message["data"])
                if frame["order_id"] == str(order.id):
                    frames.append(frame["type"])
            if len(frames) == 2:
                break
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
    assert frames == ["offer.new", "offer.taken"]


async def test_a_rider_at_capacity_cannot_accept_more(client, vendor, order_customer, riders):
    from app.core.config import settings

    busy = await riders(name="Busy")
    for _ in range(settings.MAX_CONCURRENT_JOBS):
        await _seed_order(
            vendor.restaurant.id, order_customer.id, status="PREPARING", rider_id=busy.id
        )
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)

    offers = (await client.get(f"{V1}/rider/offers", headers=_as_rider(busy))).json()["data"]
    assert next(o for o in offers if o["order_id"] == str(order.id))["can_accept"] is False
    r = await _take(client, busy, order.id)
    assert r.status_code == 409, r.text


async def test_an_unclaimed_order_stays_on_offer_and_blocks_only_the_handoff(
    client, vendor, order_customer, riders
):
    """Nobody on shift is the platform's problem, not the vendor's: accept and
    ready both succeed; only the handoff has to wait for a rider."""
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    assert r.status_code == 200, r.text
    pin = r.json()["data"]["handoff_code"]

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": pin}, headers=vendor.headers
    )
    assert r.status_code == 409, r.text

    # A rider comes on shift, sees it still on offer, and takes it.
    late = await riders(name="Late")
    offers = (await client.get(f"{V1}/rider/offers", headers=_as_rider(late))).json()["data"]
    assert str(order.id) in {o["order_id"] for o in offers}
    assert (await _take(client, late, order.id)).status_code == 200
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": pin}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text


async def test_a_rejected_order_is_withdrawn(client, vendor, order_customer, riders):
    rider = await riders()
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    await client.post(
        f"{V1}/vendor/orders/{order.id}/reject",
        json={"reason": "Out of stock"},
        headers=vendor.headers,
    )
    r = await _take(client, rider, order.id)
    assert r.status_code == 409, r.text


# ---------------------------------------------------------------------------
# The handoff, end to end
# ---------------------------------------------------------------------------


async def test_the_whole_handoff_runs_without_touching_sql(
    client, vendor, order_customer, riders
):
    """The regression this module exists to prevent: PENDING to PICKED_UP over
    the API alone."""
    rider = await riders()
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")

    r = await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert (await _take(client, rider, order.id)).status_code == 200

    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    assert r.status_code == 200, r.text
    pin = r.json()["data"]["handoff_code"]

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": pin}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PICKED_UP"


# ---------------------------------------------------------------------------
# PIN reissue — the way out of the lockout
# ---------------------------------------------------------------------------


async def test_a_locked_pin_is_reissued_by_marking_ready_again(
    client, vendor, order_customer, riders
):
    """The documented recovery path, which ORDER_TRANSITIONS used to make
    impossible: READY has no self-edge, so `_transition` refused."""
    from app.core.config import settings

    rider = await riders()
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    await _take(client, rider, order.id)
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    first_pin = r.json()["data"]["handoff_code"]
    wrong = "0000" if first_pin != "0000" else "1111"

    for _ in range(settings.HANDOFF_MAX_ATTEMPTS):
        await client.post(
            f"{V1}/vendor/orders/{order.id}/handoff",
            json={"rider_pin": wrong},
            headers=vendor.headers,
        )

    # Locked: even the right code is refused.
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff",
        json={"rider_pin": first_pin},
        headers=vendor.headers,
    )
    assert r.status_code == 409, r.text

    # Mark ready again -> fresh code, fresh budget, and the handoff completes.
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    assert r.status_code == 200, r.text
    second_pin = r.json()["data"]["handoff_code"]
    assert r.json()["data"]["status"] == "READY"

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff",
        json={"rider_pin": second_pin},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PICKED_UP"


async def test_reissue_keeps_ready_at_and_writes_no_history_row(
    client, vendor, order_customer, riders
):
    """A reissue is not a status change: prep-time analytics must not be
    rewritten, and the audit trail must not claim a transition happened."""
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models.order import OrderStatusHistory

    await riders()
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)

    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    first = r.json()["data"]
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    second = r.json()["data"]

    assert second["handoff_code"] != first["handoff_code"]
    assert second["ready_at"] == first["ready_at"]

    async with SessionLocal() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(OrderStatusHistory)
            .where(
                OrderStatusHistory.order_id == order.id,
                OrderStatusHistory.to_status == "READY",
            )
        )
    assert rows == 1, "the reissue must not record a READY -> READY transition"


# ---------------------------------------------------------------------------
# The roster and the operator override
# ---------------------------------------------------------------------------


async def test_admin_enrols_lists_and_updates_a_rider(client, admin_token, cleanup_users):
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.user import User

    headers = {"Authorization": f"Bearer {admin_token}"}
    email = f"rider-{uuid.uuid4().hex[:10]}@example.com"

    r = await client.post(
        f"{V1}/admin/riders",
        json={"full_name": "Karim Ali", "email": email, "vehicle_type": "MOTORCYCLE"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    created = r.json()["data"]
    assert created["is_online"] is True
    assert created["is_verified"] is True
    assert created["orders_in_flight"] == 0

    try:
        # The same identifier cannot become a second account.
        r = await client.post(
            f"{V1}/admin/riders", json={"full_name": "Impostor", "email": email}, headers=headers
        )
        assert r.status_code == 409, r.text

        r = await client.get(f"{V1}/admin/riders?online_only=true", headers=headers)
        assert r.status_code == 200, r.text
        assert created["id"] in [row["id"] for row in r.json()["data"]]

        r = await client.patch(
            f"{V1}/admin/riders/{created['id']}", json={"is_online": False}, headers=headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["is_online"] is False

        # A patch that changes nothing is a client bug, not a no-op.
        r = await client.patch(
            f"{V1}/admin/riders/{created['id']}", json={}, headers=headers
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.id == uuid.UUID(created["id"])))
            await session.commit()


async def test_a_rider_needs_an_email_or_a_phone(client, admin_token):
    r = await client.post(
        f"{V1}/admin/riders",
        json={"full_name": "Nameless"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400, r.text
    assert "email or phone" in " ".join(r.json()["error"]["details"])


async def test_operator_override_reassigns_an_order(
    client, vendor, order_customer, riders, admin_token
):
    first = await riders(name="First choice")
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    await _take(client, first, order.id)
    assert await _rider_id_of(order.id) == first.id

    replacement = await riders(name="Replacement")
    r = await client.post(
        f"{V1}/admin/orders/{order.id}/assign-rider",
        json={"rider_id": str(replacement.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["chosen_by"] == "operator"
    assert body["rider"]["id"] == str(replacement.id)
    assert await _rider_id_of(order.id) == replacement.id


async def test_an_order_in_a_riders_hands_cannot_be_reassigned(
    client, vendor, order_customer, riders, admin_token
):
    """PICKED_UP means the food is on a motorcycle. Rewriting the column would
    rewrite history, not change a plan."""
    rider = await riders()
    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="PICKED_UP", rider_id=rider.id
    )
    r = await client.post(
        f"{V1}/admin/orders/{order.id}/assign-rider",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 409, r.text


async def test_unverified_riders_are_refused_even_when_named(
    client, vendor, order_customer, riders, admin_token
):
    unverified = await riders(is_verified=False)
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    r = await client.post(
        f"{V1}/admin/orders/{order.id}/assign-rider",
        json={"rider_id": str(unverified.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 409, r.text
    assert "verified" in r.json()["error"]["message"].lower()


async def test_vendors_cannot_reach_the_dispatch_endpoints(client, vendor, order_customer):
    """A vendor choosing their own rider is not how delivery works."""
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    for method, path, body in (
        ("get", f"{V1}/admin/riders", None),
        ("post", f"{V1}/admin/riders", {"full_name": "X", "email": "x@example.com"}),
        ("post", f"{V1}/admin/orders/{order.id}/assign-rider", {}),
    ):
        call = getattr(client, method)
        r = await call(path, headers=vendor.headers) if body is None else await call(
            path, json=body, headers=vendor.headers
        )
        assert r.status_code == 403, f"{method} {path}: {r.text}"
