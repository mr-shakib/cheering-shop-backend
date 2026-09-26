"""The admin console API: orders, customers, vendors, dashboard, finance, search.

Orders are seeded through the ORM, as in test_vendor_api.py, so each test can
start from exactly the lifecycle state it is about.
"""

import uuid
from datetime import UTC, datetime

import pytest

V1 = "/api/v1"

pytestmark = pytest.mark.usefixtures("db_available")


async def _seed_order(
    restaurant_id,
    customer_id,
    *,
    status: str = "PENDING",
    item_total: int = 100_000,
    commission: int = 15_000,
    delivery_fee: int = 0,
    payment_method: str = "COD",
    payment_status: str = "PENDING",
    rider_id=None,
    delivered_at=None,
):
    """One order, money in paisa (100_000 == 1000 taka)."""
    from app.core.database import SessionLocal
    from app.models.order import Order

    now = datetime.now(UTC)
    order = Order(
        id=uuid.uuid4(),
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        status=status,
        item_total=item_total,
        delivery_fee=delivery_fee,
        grand_total=item_total + delivery_fee,
        commission_amount=commission,
        payment_method=payment_method,
        payment_status=payment_status,
        delivery_address_text="House 4, Road 2, Gulshan, Dhaka",
        delivery_latitude=23.7925,
        delivery_longitude=90.4078,
        delivery_contact_phone="+8801712345678",
        placed_at=now,
        delivered_at=delivered_at or (now if status == "DELIVERED" else None),
        rider_id=rider_id,
        rider_role="RIDER" if rider_id else None,
    )
    async with SessionLocal() as session:
        session.add(order)
        await session.commit()
    return order


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/admin/orders",
        "/admin/customers",
        "/admin/vendors",
        "/admin/dashboard",
        "/admin/analytics/revenue",
        "/admin/finance/summary",
        "/admin/finance/transactions",
        "/admin/search?q=ab",
    ],
)
async def test_only_administrators_get_in(client, vendor, path):
    r = await client.get(f"{V1}{path}", headers=vendor.headers)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


async def test_orders_filter_by_vendor_status_and_number(
    client, admin, vendor, order_customer, rider
):
    r_id, c_id = vendor.restaurant.id, order_customer.id
    pending = await _seed_order(r_id, c_id)
    await _seed_order(r_id, c_id, status="PREPARING")
    await _seed_order(r_id, c_id, status="DELIVERED", rider_id=rider.id)

    mine = f"{V1}/admin/orders?restaurant_id={r_id}"
    r = await client.get(mine, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["total"] == 3
    row = r.json()["data"][0]
    assert row["restaurant_name"] == vendor.restaurant.name
    assert row["customer_name"] == "Rahim Uddin"

    r = await client.get(f"{mine}&status=PENDING,DELIVERED", headers=admin)
    assert {o["status"] for o in r.json()["data"]} == {"PENDING", "DELIVERED"}

    r = await client.get(f"{V1}/admin/orders?q=ORD-{pending.order_number}", headers=admin)
    assert [o["id"] for o in r.json()["data"]] == [str(pending.id)]

    r = await client.get(f"{V1}/admin/orders?customer_id={c_id}", headers=admin)
    assert r.json()["meta"]["total"] == 3


async def test_order_filters_reject_nonsense(client, admin):
    for query in ("payment_method=CHEQUE", "status=LOST", "customer_id=nope"):
        r = await client.get(f"{V1}/admin/orders?{query}", headers=admin)
        assert r.status_code == 400, (query, r.text)
    r = await client.get(
        f"{V1}/admin/orders?date_from=2026-09-10&date_to=2026-09-01", headers=admin
    )
    assert r.status_code == 400


async def test_orders_export_as_csv(client, admin, vendor, order_customer):
    await _seed_order(vendor.restaurant.id, order_customer.id)
    r = await client.get(
        f"{V1}/admin/orders?restaurant_id={vendor.restaurant.id}&format=csv", headers=admin
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    header, first = r.text.splitlines()[:2]
    assert header.startswith("id,order_number,status")
    assert vendor.restaurant.name in first


async def test_order_drawer_shows_every_party_and_the_buttons(
    client, admin, vendor, order_customer, riders
):
    rider = await riders(name="Jahid Hasan")
    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="PICKED_UP",
        payment_method="CARD",
        payment_status="PAID",
        rider_id=rider.id,
    )
    r = await client.get(f"{V1}/admin/orders/{order.id}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["customer"]["delivery_contact_phone"] == "+8801712345678"
    assert d["vendor"]["name"] == vendor.restaurant.name
    assert d["rider"]["full_name"] == "Jahid Hasan"
    assert d["money"]["commission_amount"] == 150.0
    assert d["money"]["vendor_payout"] == 850.0
    assert d["actions"] == {
        "can_assign_rider": False,
        "can_cancel": False,  # the rider has the food
        "can_refund": True,
        "can_force_deliver": True,
    }

    r = await client.get(f"{V1}/admin/orders/{uuid.uuid4()}", headers=admin)
    assert r.status_code == 404


async def test_cancelling_a_paid_order_refunds_it(client, admin, vendor, order_customer):
    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="PREPARING",
        payment_method="CARD",
        payment_status="PAID",
    )
    r = await client.post(
        f"{V1}/admin/orders/{order.id}/cancel",
        json={"reason": "Restaurant not answering"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "CANCELLED"
    assert d["cancelled_by"] == "ADMIN"
    assert d["payment"]["status"] == "REFUNDED"
    assert d["payment"]["refund_reason"] == "Restaurant not answering"
    assert d["payment"]["refunded_by"] is not None
    assert d["timeline"][-1] == {
        "status": "CANCELLED",
        "at": d["timeline"][-1]["at"],
        "actor": "ADMIN",
        "note": "Restaurant not answering",
    }
    assert d["actions"]["can_cancel"] is False

    again = await client.post(
        f"{V1}/admin/orders/{order.id}/cancel", json={"reason": "twice"}, headers=admin
    )
    assert again.status_code == 409


async def test_an_order_on_the_road_cannot_be_cancelled(
    client, admin, vendor, order_customer, riders
):
    rider = await riders()
    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="PICKED_UP", rider_id=rider.id
    )
    r = await client.post(
        f"{V1}/admin/orders/{order.id}/cancel", json={"reason": "Too late"}, headers=admin
    )
    assert r.status_code == 409


async def test_refund_needs_money_to_have_been_taken(client, admin, vendor, order_customer, rider):
    cod = await _seed_order(vendor.restaurant.id, order_customer.id)
    r = await client.post(
        f"{V1}/admin/orders/{cod.id}/refund", json={"reason": "Missing item"}, headers=admin
    )
    assert r.status_code == 409

    paid = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        rider_id=rider.id,
        payment_method="BKASH",
        payment_status="PAID",
    )
    r = await client.post(
        f"{V1}/admin/orders/{paid.id}/refund", json={"reason": "Missing item"}, headers=admin
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "DELIVERED"  # a refund is not a cancellation
    assert d["payment"]["status"] == "REFUNDED"

    r = await client.post(
        f"{V1}/admin/orders/{paid.id}/refund", json={"reason": "Again"}, headers=admin
    )
    assert r.status_code == 409


async def test_vendor_rejection_now_records_the_refund(client, vendor, order_customer):
    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        payment_method="CARD",
        payment_status="PAID",
    )
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/reject",
        json={"reason": "Out of rice"},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text

    from app.core.database import SessionLocal
    from app.models.order import Order

    async with SessionLocal() as s:
        saved = await s.get(Order, order.id)
    assert saved.payment_status == "REFUNDED"
    assert saved.refunded_by == vendor.user.id
    assert saved.refund_reason == "Out of rice"


# ---------------------------------------------------------------------------
# Customers & blocking
# ---------------------------------------------------------------------------


async def test_customer_list_and_statistics(client, admin, vendor, order_customer, rider):
    r_id, c_id = vendor.restaurant.id, order_customer.id
    await _seed_order(
        r_id, c_id, status="DELIVERED", rider_id=rider.id, item_total=30_000, commission=0
    )
    await _seed_order(
        r_id, c_id, status="DELIVERED", rider_id=rider.id, item_total=10_000, commission=0
    )
    cancelled = await _seed_order(r_id, c_id)
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.order import Order

    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == cancelled.id)
            .values(status="CANCELLED", cancelled_at=datetime.now(UTC))
        )
        await s.commit()

    r = await client.get(f"{V1}/admin/customers?q={order_customer.email}", headers=admin)
    assert r.status_code == 200, r.text
    [row] = r.json()["data"]
    assert row["order_count"] == 3
    assert row["total_spent"] == 400.0

    r = await client.get(f"{V1}/admin/customers/{c_id}", headers=admin)
    stats = r.json()["data"]["stats"]
    assert stats == {
        "total_orders": 3,
        "delivered_orders": 2,
        "cancelled_orders": 1,
        "total_spent": 400.0,
        "average_order": 200.0,
    }

    r = await client.get(f"{V1}/admin/customers/{vendor.user.id}", headers=admin)
    assert r.status_code == 404  # a vendor is not a customer


async def test_a_blocked_customer_is_locked_out_at_once(client, admin, order_customer):
    from app.core.security import create_access_token

    token = create_access_token(str(order_customer.id), order_customer.role)
    me = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"{V1}/users/me", headers=me)).status_code == 200

    r = await client.patch(
        f"{V1}/admin/users/{order_customer.id}/status", json={"is_active": False}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_active"] is False
    assert (await client.get(f"{V1}/users/me", headers=me)).status_code == 403

    r = await client.get(
        f"{V1}/admin/customers?status=BLOCKED&q={order_customer.email}", headers=admin
    )
    assert r.json()["meta"]["total"] == 1

    await client.patch(
        f"{V1}/admin/users/{order_customer.id}/status", json={"is_active": True}, headers=admin
    )
    assert (await client.get(f"{V1}/users/me", headers=me)).status_code == 200


async def test_blocking_a_rider_takes_them_off_shift(client, admin, riders):
    rider = await riders(is_online=True)
    r = await client.patch(
        f"{V1}/admin/users/{rider.id}/status", json={"is_active": False}, headers=admin
    )
    assert r.status_code == 200, r.text

    from app.core.database import SessionLocal
    from app.models.rider import RiderProfile

    async with SessionLocal() as s:
        assert (await s.get(RiderProfile, rider.id)).is_online is False


async def test_vendors_are_suspended_through_their_restaurant(client, admin, vendor):
    r = await client.patch(
        f"{V1}/admin/users/{vendor.user.id}/status", json={"is_active": False}, headers=admin
    )
    assert r.status_code == 409
    assert "restaurant" in r.text


# ---------------------------------------------------------------------------
# Vendors & payouts
# ---------------------------------------------------------------------------


async def test_vendor_list_profile_and_money(client, admin, vendor, order_customer, rider):
    r_id = vendor.restaurant.id
    await _seed_order(
        r_id, order_customer.id, status="DELIVERED", rider_id=rider.id
    )  # 1000 taka, 150 commission

    r = await client.get(f"{V1}/admin/vendors?q={vendor.restaurant.name}", headers=admin)
    assert r.status_code == 200, r.text
    [row] = r.json()["data"]
    assert row["order_count"] == 1
    assert row["revenue"] == 1000.0
    assert row["business_type"] is None  # created without an application

    r = await client.get(f"{V1}/admin/vendors/{r_id}", headers=admin)
    assert r.status_code == 200, r.text
    detail = r.json()["data"]
    assert detail["owner"]["email"] == vendor.user.email
    assert detail["commission_rate"] == 0.15

    r = await client.get(f"{V1}/admin/vendors/{r_id}/finance", headers=admin)
    assert r.json()["data"] == {
        "restaurant_id": str(r_id),
        "total_earning": 1000.0,
        "total_commission": 150.0,
        "total_payout": 0.0,
        "pending_amount": 0.0,
        "available_balance": 850.0,
    }

    r = await client.get(f"{V1}/admin/vendors/{r_id}/reviews", headers=admin)
    assert r.status_code == 200
    assert r.json()["data"]["summary"]["rating_count"] == 0
    assert r.json()["meta"]["total"] == 0

    r = await client.get(f"{V1}/admin/vendors?business_type=BAKERY", headers=admin)
    assert r.status_code == 400


async def test_suspended_vendors_leave_the_active_list(client, admin, pending_vendor):
    name = pending_vendor.restaurant.name
    r = await client.get(f"{V1}/admin/vendors?q={name}", headers=admin)
    assert r.json()["meta"]["total"] == 0
    r = await client.get(f"{V1}/admin/vendors?q={name}&status=SUSPENDED", headers=admin)
    assert r.json()["meta"]["total"] == 1


async def test_payouts_filter_to_one_vendor(client, admin, vendor, other_vendor):
    from app.core.database import SessionLocal
    from app.models.payout import VendorPayout

    async with SessionLocal() as s:
        for v in (vendor, other_vendor):
            s.add(
                VendorPayout(
                    restaurant_id=v.restaurant.id,
                    reference=f"CHR{uuid.uuid4().int % 10**9:09d}",
                    amount=50_000,
                    method="BKASH",
                    account_number="01712345678",
                    account_name="Karim Ahmed",
                )
            )
        await s.commit()

    r = await client.get(f"{V1}/admin/payouts?restaurant_id={vendor.restaurant.id}", headers=admin)
    assert r.status_code == 200, r.text
    [row] = r.json()["data"]
    assert row["restaurant_name"] == vendor.restaurant.name
    assert row["amount"] == 500.0


# ---------------------------------------------------------------------------
# Dashboard, finance, search
# ---------------------------------------------------------------------------


async def test_dashboard_counts_todays_delivered_money(
    client, admin, vendor, order_customer, rider
):
    before = (await client.get(f"{V1}/admin/dashboard", headers=admin)).json()["data"]
    await _seed_order(
        vendor.restaurant.id, order_customer.id, status="DELIVERED", rider_id=rider.id
    )
    await _seed_order(vendor.restaurant.id, order_customer.id)  # PENDING — not revenue

    r = await client.get(f"{V1}/admin/dashboard", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    gained = float(d["revenue_today"]["value"]) - float(before["revenue_today"]["value"])
    assert gained == 1000.0
    assert d["orders_today"]["value"] == before["orders_today"]["value"] + 2
    assert d["live_orders"]["new"] >= 1
    assert len(d["recent_orders"]) <= 8


@pytest.mark.parametrize(
    ("range_", "points", "granularity"),
    [("7d", 7, "day"), ("30d", 30, "day"), ("12m", 12, "month")],
)
async def test_revenue_chart_has_every_bucket(client, admin, range_, points, granularity):
    r = await client.get(f"{V1}/admin/analytics/revenue?range={range_}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["granularity"] == granularity
    assert len(d["points"]) == points
    starts = [p["period_start"] for p in d["points"]]
    assert starts == sorted(starts)


async def test_finance_counts_commission_and_delivery(client, admin, vendor, order_customer, rider):
    before = (await client.get(f"{V1}/admin/finance/summary", headers=admin)).json()["data"]
    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        rider_id=rider.id,
        delivery_fee=6_000,
    )
    r = await client.get(f"{V1}/admin/finance/summary", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]

    def moved(key):
        return round(float(d[key]["value"]) - float(before[key]["value"]), 2)

    assert moved("gmv") == 1060.0
    assert moved("commission_revenue") == 150.0
    assert moved("delivery_revenue") == 60.0
    assert moved("net_revenue") == 150.0  # delivery fees go to riders
    assert abs(sum(s["share_pct"] for s in d["revenue_by_service"]) - 100) < 0.5

    r = await client.get(f"{V1}/admin/finance/transactions?q={order.order_number}", headers=admin)
    [tx] = r.json()["data"]
    assert tx["amount"] == 1060.0
    assert tx["restaurant_name"] == vendor.restaurant.name


async def test_search_finds_orders_and_vendors(client, admin, vendor, order_customer):
    order = await _seed_order(vendor.restaurant.id, order_customer.id)
    r = await client.get(f"{V1}/admin/search?q=%23{order.order_number}", headers=admin)
    assert r.status_code == 200, r.text
    assert [h["id"] for h in r.json()["data"]["orders"]] == [str(order.id)]

    r = await client.get(f"{V1}/admin/search?q={vendor.restaurant.name}", headers=admin)
    assert str(vendor.restaurant.id) in [h["id"] for h in r.json()["data"]["vendors"]]

    r = await client.get(f"{V1}/admin/search?q=Rahim Uddin", headers=admin)
    assert str(order_customer.id) in [h["id"] for h in r.json()["data"]["customers"]]
