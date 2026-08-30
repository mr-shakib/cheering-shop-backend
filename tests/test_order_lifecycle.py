"""The whole order, placed to delivered, over the API alone.

Every other suite seeds its orders through the ORM because the module under
test is somewhere in the middle of the lifecycle. This one seeds nothing. A
customer browses, adds to a cart, checks out and pays; a kitchen accepts, cooks
and hands over against a PIN; a rider carries it and marks it delivered; the
customer reviews it and the vendor's earnings move.

If any single link is missing, this test is the one that notices.
"""

import uuid

import pytest

# `kitchen` (an OPEN restaurant with a real menu), `shopper` (a signed-in
# customer with a saved address) and `riders` live in conftest.py.
from tests.test_customer_ordering import _add_burger

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


@pytest.fixture
async def courier(client, admin_token):
    """A rider enrolled the way an administrator actually enrols one: through
    the API, with a password, so they can sign in and work."""
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.order import Order
    from app.models.user import User

    password = "RiderPassword1!"
    r = await client.post(
        f"{V1}/admin/riders",
        json={
            "full_name": "Jamil Hossain",
            "email": f"courier-{uuid.uuid4().hex[:10]}@example.com",
            "password": password,
            "vehicle_type": "MOTORCYCLE",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    rider = r.json()["data"]

    login = await client.post(
        f"{V1}/auth/login", json={"email": rider["email"], "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["tokens"]["access_token"]

    class _Courier:
        id = uuid.UUID(rider["id"])
        headers = {"Authorization": f"Bearer {token}"}
        data = rider

    yield _Courier()

    async with SessionLocal() as session:
        await session.execute(delete(Order).where(Order.rider_id == _Courier.id))
        await session.execute(delete(User).where(User.id == _Courier.id))
        await session.commit()


async def test_an_order_goes_from_cart_to_delivered_without_any_sql(
    client, kitchen, shopper, courier
):
    vendor = kitchen

    # 1. The customer builds a cart and places the order.
    await _add_burger(client, kitchen, shopper, quantity=2)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["data"]["id"]
    assert r.json()["data"]["payment_status"] == "PENDING"

    # 2. The kitchen accepts — and dispatch puts our courier on it.
    r = await client.post(f"{V1}/vendor/orders/{order_id}/accept", headers=vendor.headers)
    assert r.status_code == 200, r.text

    r = await client.get(f"{V1}/rider/orders", headers=courier.headers)
    assert r.status_code == 200, r.text
    jobs = r.json()["data"]
    assert [j["order_id"] for j in jobs] == [order_id]
    # COD: the rider is told exactly what cash to collect.
    assert jobs[0]["collect_on_delivery"] == jobs[0]["grand_total"]

    # 3. The food is ready. Both sides can now read the same code — the rider
    #    from their own job screen, which is decision D3 as designed.
    r = await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=vendor.headers)
    assert r.status_code == 200, r.text
    vendor_code = r.json()["data"]["handoff_code"]

    r = await client.get(f"{V1}/rider/orders/{order_id}", headers=courier.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["handoff_code"] == vendor_code

    # 4. The rider reads it out; the vendor types it back.
    r = await client.post(
        f"{V1}/vendor/orders/{order_id}/handoff",
        json={"rider_pin": vendor_code},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PICKED_UP"

    # The code is spent on both screens at once.
    r = await client.get(f"{V1}/rider/orders/{order_id}", headers=courier.headers)
    assert r.json()["data"]["handoff_code"] is None

    # The customer's map now names who is bringing it.
    r = await client.get(f"{V1}/orders/{order_id}/tracking", headers=shopper.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["rider"]["full_name"] == "Jamil Hossain"
    assert r.json()["data"]["live_tracking_available"] is False

    # 5. Delivered — the transition nothing in the system could make.
    r = await client.post(f"{V1}/rider/orders/{order_id}/deliver", headers=courier.headers)
    assert r.status_code == 200, r.text
    delivery = r.json()["data"]
    assert delivery["status"] == "DELIVERED"
    assert delivery["payment_status"] == "PAID", "COD is collected at the door"
    assert delivery["total_deliveries"] == 1

    # 6. Everything downstream of DELIVERED now works.
    r = await client.post(
        f"{V1}/orders/{order_id}/reviews",
        json={"restaurant_rating": 5, "rider_rating": 5, "comment": "Hot and on time"},
        headers=shopper.headers,
    )
    assert r.status_code in (200, 201), r.text

    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["available_balance"] > 0, "a delivered order must be earnable"

    r = await client.get(f"{V1}/rider/orders?tab=COMPLETE", headers=courier.headers)
    assert [j["order_id"] for j in r.json()["data"]] == [order_id]


async def test_a_rider_cannot_deliver_an_order_that_is_not_theirs(
    client, kitchen, shopper, courier, riders, admin_token
):
    """Somebody else's order is not found, not forbidden — an id that answers
    differently tells an enumerating caller which orders are real."""
    other = await riders(name="Somebody else")
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = r.json()["data"]["id"]

    # Dispatch would hand this to whichever rider is idlest, so the override is
    # what puts it definitively in somebody else's hands.
    from app.core.security import create_access_token

    await client.post(f"{V1}/vendor/orders/{order_id}/accept", headers=kitchen.headers)
    r = await client.post(
        f"{V1}/admin/orders/{order_id}/assign-rider",
        json={"rider_id": str(other.id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    other_headers = {"Authorization": f"Bearer {create_access_token(str(other.id), 'RIDER')}"}

    r = await client.get(f"{V1}/rider/orders/{order_id}", headers=courier.headers)
    assert r.status_code == 404, r.text
    r = await client.post(
        f"{V1}/rider/orders/{order_id}/deliver", headers=courier.headers
    )
    assert r.status_code == 404, r.text

    # And the rider who does hold it cannot deliver before collecting it.
    r = await client.post(f"{V1}/rider/orders/{order_id}/deliver", headers=other_headers)
    assert r.status_code == 409, r.text
    assert "delivered" in r.json()["error"]["message"].lower()


async def test_shift_toggle_takes_a_rider_out_of_the_dispatch_pool(
    client, kitchen, shopper, courier
):
    r = await client.patch(
        f"{V1}/rider/me/shift", json={"is_online": False}, headers=courier.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_online"] is False

    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = r.json()["data"]["id"]
    await client.post(f"{V1}/vendor/orders/{order_id}/accept", headers=kitchen.headers)

    r = await client.get(f"{V1}/rider/orders", headers=courier.headers)
    assert r.json()["data"] == [], "an off-shift rider must not be assigned work"


async def test_an_admin_can_confirm_a_delivery_the_rider_could_not(
    client, kitchen, shopper, courier, admin_token
):
    """The dead-phone fallback. Same money, same counters, different actor in
    the status history."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import OrderStatusHistory

    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = r.json()["data"]["id"]

    await client.post(f"{V1}/vendor/orders/{order_id}/accept", headers=kitchen.headers)
    r = await client.post(f"{V1}/vendor/orders/{order_id}/ready", headers=kitchen.headers)
    await client.post(
        f"{V1}/vendor/orders/{order_id}/handoff",
        json={"rider_pin": r.json()["data"]["handoff_code"]},
        headers=kitchen.headers,
    )

    r = await client.post(
        f"{V1}/admin/orders/{order_id}/deliver",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "DELIVERED"

    async with SessionLocal() as session:
        actor = await session.scalar(
            select(OrderStatusHistory.actor).where(
                OrderStatusHistory.order_id == uuid.UUID(order_id),
                OrderStatusHistory.to_status == "DELIVERED",
            )
        )
    assert actor == "ADMIN", "an operator-confirmed delivery must not look like a rider's"


async def test_only_riders_reach_the_rider_api(client, vendor, shopper):
    for headers in (vendor.headers, shopper.headers):
        r = await client.get(f"{V1}/rider/orders", headers=headers)
        assert r.status_code == 403, r.text
