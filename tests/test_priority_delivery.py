"""Priority delivery: the Standard / Priority choice on the checkout screen.

Priority adds a flat fee (৳20 by default) to the bill. The rider who carries
the order earns all of it, priority orders head the rider's offer list, and
the quoted time window is shorter.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.test_customer_ordering import _add_burger
from tests.test_rider_dispatch import _as_rider
from tests.test_vendor_api import _seed_order

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _summary(client, shopper, **params):
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id, **params},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_checkout_offers_both_options_and_prices_priority(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)

    standard = await _summary(client, shopper)
    assert standard["delivery_type"] == "STANDARD"
    assert standard["priority_fee"] == 0
    options = {o["type"]: o for o in standard["delivery_options"]}
    assert options["STANDARD"]["extra_fee"] == 0 and options["STANDARD"]["is_selected"]
    assert options["PRIORITY"]["extra_fee"] == 20 and not options["PRIORITY"]["is_selected"]
    # A window, and priority's is earlier.
    for option in options.values():
        assert option["eta_max_minutes"] - option["eta_min_minutes"] == 10
    assert options["PRIORITY"]["eta_min_minutes"] < options["STANDARD"]["eta_min_minutes"]

    priority = await _summary(client, shopper, delivery_type="PRIORITY")
    assert priority["delivery_type"] == "PRIORITY"
    assert priority["priority_fee"] == 20
    # Priority is on top of delivery, not instead of it.
    assert priority["delivery_fee"] == standard["delivery_fee"]
    assert Decimal(str(priority["grand_total"])) == Decimal(str(standard["grand_total"])) + 20
    selected = next(o for o in priority["delivery_options"] if o["is_selected"])
    assert selected["type"] == "PRIORITY"
    assert priority["estimated_delivery_minutes"] == selected["eta_min_minutes"]


async def test_an_unknown_delivery_type_is_refused(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id, "delivery_type": "ROCKET"},
        headers=shopper.headers,
    )
    assert r.status_code == 400, r.text


async def test_a_priority_order_is_charged_and_remembered(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    quoted = await _summary(client, shopper, delivery_type="PRIORITY")

    r = await client.post(
        f"{V1}/orders",
        json={
            "payment_method": "COD",
            "address_id": shopper.address_id,
            "delivery_type": "PRIORITY",
        },
        headers=shopper.headers,
    )
    assert r.status_code == 201, r.text
    placed = r.json()["data"]
    assert placed["grand_total"] == quoted["grand_total"]

    detail = (
        await client.get(f"{V1}/orders/{placed['id']}", headers=shopper.headers)
    ).json()["data"]
    assert detail["delivery_type"] == "PRIORITY"
    assert detail["priority_fee"] == 20
    assert "tax_amount" not in detail and "packaging_fee" not in detail

    # The kitchen sees the flag.
    r = await client.get(f"{V1}/vendor/orders/{placed['id']}", headers=kitchen.headers)
    assert r.json()["data"]["delivery_type"] == "PRIORITY"


async def test_priority_cannot_be_scheduled(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    r = await client.post(
        f"{V1}/orders",
        json={
            "payment_method": "COD",
            "address_id": shopper.address_id,
            "delivery_type": "PRIORITY",
            "scheduled_for": later,
        },
        headers=shopper.headers,
    )
    assert r.status_code == 400, r.text
    assert "Priority" in r.json()["error"]["message"]


async def test_the_settings_screen_sets_the_priority_fee(
    client, admin, kitchen, shopper, fresh_settings
):
    r = await client.get(f"{V1}/admin/settings", headers=admin)
    assert r.json()["data"]["priority_delivery_fee"] == 20

    r = await client.patch(
        f"{V1}/admin/settings", json={"priority_delivery_fee": 35}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["priority_delivery_fee"] == 35

    await _add_burger(client, kitchen, shopper, quantity=1)
    bill = await _summary(client, shopper, delivery_type="PRIORITY")
    assert bill["priority_fee"] == 35
    assert next(o for o in bill["delivery_options"] if o["type"] == "PRIORITY")["extra_fee"] == 35


async def _make_priority(order, fee: int = 2000) -> None:
    """Turn a seeded order into a priority one, keeping the total math true."""
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.order import Order

    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(
                delivery_type="PRIORITY",
                priority_fee=fee,
                grand_total=Order.grand_total + fee,
            )
        )
        await s.commit()


async def test_riders_see_priority_offers_first_and_earn_the_fee(
    client, vendor, order_customer, riders
):
    rider = await riders(name="Quick")
    plain = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    rushed = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await _make_priority(rushed)
    for order in (plain, rushed):
        r = await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
        assert r.status_code == 200, r.text

    offers = (await client.get(f"{V1}/rider/offers", headers=_as_rider(rider))).json()["data"]
    mine = [o for o in offers if o["order_id"] in {str(plain.id), str(rushed.id)}]
    assert [o["order_id"] for o in mine] == [str(rushed.id), str(plain.id)]
    assert mine[0]["delivery_type"] == "PRIORITY"
    assert mine[0]["earning"] == mine[1]["earning"] + 20


async def test_the_priority_fee_counts_as_the_riders_delivery_earning(
    client, vendor, order_customer, riders
):
    rider = await riders(name="Earner")
    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        rider_id=rider.id,
        delivered_at=datetime.now(UTC),
    )
    await _make_priority(order, fee=2000)

    wallet = (await client.get(f"{V1}/rider/earnings", headers=_as_rider(rider))).json()["data"]
    assert wallet["totals"]["delivery_earning"] == 20.0
    assert wallet["available_balance"] == 20.0
