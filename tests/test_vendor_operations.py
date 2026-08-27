"""The vendor app's operational screens: dashboard, performance, earnings &
payouts, business hours, promotions, feedback summary, report CSV.

Covers what `ui/full vendor/` renders beyond the order lifecycle (which
tests/test_vendor_api.py owns). Orders are seeded through the ORM for the same
reason as there: `POST /orders` is still 501, and the vendor endpoints are the
system under test.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

# The vendor/order_customer/rider/other_vendor fixtures live in conftest.py;
# only the order seeder is imported here.
from tests.test_vendor_api import _seed_order

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


# ---------------------------------------------------------------------------
# Dashboard & performance
# ---------------------------------------------------------------------------


async def test_dashboard_counts_queue_and_today(client, vendor, order_customer, rider):
    now = datetime.now(UTC)
    await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await _seed_order(vendor.restaurant.id, order_customer.id, status="PREPARING")
    await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        item_total=80_000,
        commission=12_000,
        delivered_at=now,
        rider_id=rider.id,
    )

    r = await client.get(f"{V1}/vendor/dashboard", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["queue"] == {
        "new": 1,
        "preparing": 1,
        "complete": 1,
        "ready": 0,
        "completed_today": 1,
    }
    assert data["today_orders"] == 1
    assert data["today_earnings"] == 680.0  # 800 - 120 commission
    assert len(data["last_7_days"]) == 7
    assert data["last_7_days"][-1]["earnings"] == 680.0
    assert len(data["recent_orders"]) == 3
    assert data["store_status"] == "CLOSED"


async def test_acceptance_rate_ignores_customer_cancellations(
    client, vendor, order_customer
):
    """2 accepted, 1 vendor-rejected, 1 customer-cancelled -> 2/3, not 2/4."""
    now = datetime.now(UTC)
    for _ in range(2):
        order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PREPARING")
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/reject",
        json={"reason": "Item unavailable"},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text

    from app.core.database import SessionLocal
    from app.models.order import Order

    cancelled = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    async with SessionLocal() as session:
        row = await session.get(Order, cancelled.id)
        row.status = "CANCELLED"
        row.cancelled_by = "CUSTOMER"
        row.cancelled_at = now
        row.auto_decline_at = None
        await session.commit()

    # accepted_at is set by the transition; seeded PREPARING rows lack it, so
    # stamp them the way accept_order would have.
    async with SessionLocal() as session:
        from sqlalchemy import update

        await session.execute(
            update(Order)
            .where(Order.restaurant_id == vendor.restaurant.id, Order.status == "PREPARING")
            .values(accepted_at=now)
        )
        await session.commit()

    r = await client.get(f"{V1}/vendor/performance", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["acceptance_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert r.json()["data"]["rejections_this_week"] == 1


async def test_performance_rates_are_null_without_data(client, vendor):
    r = await client.get(f"{V1}/vendor/performance", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["acceptance_rate"] is None
    assert data["on_time_rate"] is None


# ---------------------------------------------------------------------------
# Earnings & payouts
# ---------------------------------------------------------------------------


async def _seed_delivered(vendor, order_customer, rider, item_total: int, commission: int):
    return await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        item_total=item_total,
        commission=commission,
        delivered_at=datetime.now(UTC),
        rider_id=rider.id,
    )


async def test_balance_is_earnings_minus_payouts(client, vendor, order_customer, rider):
    await _seed_delivered(vendor, order_customer, rider, 200_000, 30_000)  # +1700
    await _seed_delivered(vendor, order_customer, rider, 100_000, 15_000)  # +850

    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["available_balance"] == 2550.0
    assert data["lifetime_earnings"] == 2550.0
    assert len(data["recent_transactions"]) == 2

    r = await client.post(
        f"{V1}/vendor/payouts",
        json={
            "amount": 1000,
            "method": "BKASH",
            "account_number": "01712447567",
            "account_name": "Karim Ahmed",
        },
        headers=vendor.headers,
    )
    assert r.status_code == 201, r.text
    payout = r.json()["data"]
    assert payout["status"] == "PROCESSING"
    assert payout["reference"].startswith("CHR")

    # PROCESSING is already deducted — money on its way out is not available.
    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    assert r.json()["data"]["available_balance"] == 1550.0
    assert r.json()["data"]["processing_payouts"] == 1000.0


async def test_payout_cannot_exceed_balance_or_minimum(client, vendor, order_customer, rider):
    await _seed_delivered(vendor, order_customer, rider, 50_000, 10_000)  # balance 400

    body = {
        "amount": 500,
        "method": "NAGAD",
        "account_number": "01712447567",
        "account_name": "Karim Ahmed",
    }
    r = await client.post(f"{V1}/vendor/payouts", json=body, headers=vendor.headers)
    assert r.status_code == 400
    assert "Insufficient balance" in r.json()["error"]["message"]

    r = await client.post(
        f"{V1}/vendor/payouts", json={**body, "amount": 50}, headers=vendor.headers
    )
    assert r.status_code == 400
    assert "Minimum withdrawal" in r.json()["error"]["message"]

    r = await client.post(
        f"{V1}/vendor/payouts",
        json={**body, "amount": 400, "method": "BANK"},
        headers=vendor.headers,
    )
    assert r.status_code == 400, "BANK without bank_name must be rejected"


async def test_failed_payout_returns_the_money(
    client, vendor, order_customer, rider, admin_token
):
    await _seed_delivered(vendor, order_customer, rider, 200_000, 30_000)  # 1700
    r = await client.post(
        f"{V1}/vendor/payouts",
        json={
            "amount": 1700,
            "method": "ROCKET",
            "account_number": "01712447567",
            "account_name": "Karim Ahmed",
        },
        headers=vendor.headers,
    )
    assert r.status_code == 201, r.text
    payout_id = r.json()["data"]["id"]

    # Balance is drained; a second withdrawal is refused.
    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    assert r.json()["data"]["available_balance"] == 0.0

    admin = {"Authorization": f"Bearer {admin_token}"}
    r = await client.get(f"{V1}/admin/payouts", headers=admin)
    assert payout_id in [p["id"] for p in r.json()["data"]]

    r = await client.post(
        f"{V1}/admin/payouts/{payout_id}/fail",
        json={"reason": "Wallet number not registered"},
        headers=admin,
    )
    assert r.status_code == 200, r.text

    # Marking FAILED is itself the refund.
    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    assert r.json()["data"]["available_balance"] == 1700.0

    r = await client.get(f"{V1}/vendor/payouts", headers=vendor.headers)
    row = r.json()["data"][0]
    assert row["status"] == "FAILED"
    assert row["failure_reason"] == "Wallet number not registered"

    # A decided payout cannot be re-decided.
    r = await client.post(f"{V1}/admin/payouts/{payout_id}/complete", headers=admin)
    assert r.status_code == 400


async def test_completed_payout_stays_withdrawn(
    client, vendor, order_customer, rider, admin_token
):
    await _seed_delivered(vendor, order_customer, rider, 100_000, 15_000)  # 850
    r = await client.post(
        f"{V1}/vendor/payouts",
        json={
            "amount": 500,
            "method": "BKASH",
            "account_number": "01712447567",
            "account_name": "Karim Ahmed",
        },
        headers=vendor.headers,
    )
    payout_id = r.json()["data"]["id"]

    admin = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(f"{V1}/admin/payouts/{payout_id}/complete", headers=admin)
    assert r.status_code == 200, r.text

    r = await client.get(f"{V1}/vendor/earnings", headers=vendor.headers)
    data = r.json()["data"]
    assert data["available_balance"] == 350.0
    assert data["total_withdrawn"] == 500.0
    assert data["processing_payouts"] == 0.0


async def test_vendor_cannot_touch_admin_payout_queue(client, vendor):
    r = await client.get(f"{V1}/admin/payouts", headers=vendor.headers)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Business hours
# ---------------------------------------------------------------------------


def _week(**overrides) -> dict:
    day = {"is_open": True, "opens_at": "10:00", "closes_at": "22:00"}
    week = {k: dict(day) for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    for key, value in overrides.items():
        week[key] = value
    return week


async def test_hours_roundtrip(client, vendor):
    r = await client.get(f"{V1}/vendor/hours", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_configured"] is False

    week = _week(
        fri={"is_open": True, "opens_at": "14:00", "closes_at": "23:00"},
        sun={"is_open": False},
    )
    r = await client.put(f"{V1}/vendor/hours", json=week, headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["is_configured"] is True
    assert data["days"]["fri"] == {"is_open": True, "opens_at": "14:00", "closes_at": "23:00"}
    assert data["days"]["sun"] == {"is_open": False, "opens_at": None, "closes_at": None}

    r = await client.get(f"{V1}/vendor/hours", headers=vendor.headers)
    assert r.json()["data"]["days"]["fri"]["opens_at"] == "14:00"


async def test_open_day_requires_both_times(client, vendor):
    week = _week(wed={"is_open": True, "opens_at": "10:00", "closes_at": None})
    r = await client.put(f"{V1}/vendor/hours", json=week, headers=vendor.headers)
    assert r.status_code == 400
    assert "wed" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


async def _launch(client, vendor, **overrides) -> dict:
    body = {
        "discount_type": "PERCENTAGE",
        "discount_value": 20,
        "min_order_amount": 400,
        "ends_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "budget_cap": 5000,
    }
    body.update(overrides)
    r = await client.post(f"{V1}/vendor/promotions", json=body, headers=vendor.headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_promotion_lifecycle(client, vendor):
    promo = await _launch(client, vendor)
    assert promo["title"] == "20% OFF"
    assert promo["state"] == "ACTIVE"
    assert promo["applies_to_all_items"] is True
    assert promo["budget_cap"] == 5000.0
    assert promo["budget_spent"] == 0.0
    assert promo["code"], "a typeable code must be generated"

    # Detail carries the 7-day chart.
    r = await client.get(f"{V1}/vendor/promotions/{promo['id']}", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]["last_7_days"]) == 7

    # Pause, resume, then end early — which is final.
    r = await client.patch(
        f"{V1}/vendor/promotions/{promo['id']}", json={"is_active": False}, headers=vendor.headers
    )
    assert r.json()["data"]["state"] == "PAUSED"
    r = await client.patch(
        f"{V1}/vendor/promotions/{promo['id']}", json={"is_active": True}, headers=vendor.headers
    )
    assert r.json()["data"]["state"] == "ACTIVE"
    r = await client.patch(
        f"{V1}/vendor/promotions/{promo['id']}", json={"end_now": True}, headers=vendor.headers
    )
    assert r.json()["data"]["state"] == "ENDED"
    r = await client.patch(
        f"{V1}/vendor/promotions/{promo['id']}", json={"is_active": True}, headers=vendor.headers
    )
    assert r.status_code == 400, "an ended promotion must be immutable"


async def test_promotion_value_rules(client, vendor):
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    bad = [
        {"discount_type": "PERCENTAGE", "discount_value": 120, "ends_at": future},
        {"discount_type": "FLAT", "ends_at": future},
        {"discount_type": "FREE_DELIVERY", "discount_value": 10, "ends_at": future},
    ]
    for body in bad:
        r = await client.post(f"{V1}/vendor/promotions", json=body, headers=vendor.headers)
        assert r.status_code == 400, f"accepted: {body}"

    promo = await _launch(client, vendor, discount_type="FREE_DELIVERY", discount_value=None)
    assert promo["title"] == "Free delivery"
    assert promo["discount_value"] is None


async def test_promotion_item_scope_must_be_own_menu(client, vendor):
    r = await client.post(
        f"{V1}/vendor/promotions",
        json={
            "discount_type": "FLAT",
            "discount_value": 50,
            "ends_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            "item_ids": [str(uuid.uuid4())],
        },
        headers=vendor.headers,
    )
    assert r.status_code == 400
    assert "menu" in r.json()["error"]["message"].lower()


async def test_promotions_are_isolated_between_vendors(client, vendor, other_vendor):
    promo = await _launch(client, vendor)
    r = await client.get(
        f"{V1}/vendor/promotions/{promo['id']}", headers=other_vendor.headers
    )
    assert r.status_code == 404, "someone else's promotion must be a 404, not a 403"


# ---------------------------------------------------------------------------
# Feedback summary & report CSV
# ---------------------------------------------------------------------------


async def test_reviews_summary_histogram(client, vendor, order_customer, rider):
    from app.core.database import SessionLocal
    from app.models.review import Review

    order = await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        delivered_at=datetime.now(UTC),
        rider_id=rider.id,
    )
    async with SessionLocal() as session:
        session.add(
            Review(
                order_id=order.id,
                customer_id=order_customer.id,
                restaurant_id=vendor.restaurant.id,
                restaurant_rating=4,
                comment="Great taste",
            )
        )
        await session.commit()

    r = await client.get(f"{V1}/vendor/reviews/summary", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["rating_count"] == 1
    assert data["rating_avg"] == 4.0
    assert data["histogram"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0}


async def test_report_csv_downloads_delivered_orders(client, vendor, order_customer, rider):
    await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        item_total=80_000,
        commission=12_000,
        delivered_at=datetime.now(UTC),
        rider_id=rider.id,
    )

    r = await client.get(f"{V1}/vendor/reports/csv", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    lines = r.text.strip().splitlines()
    assert lines[0].startswith("order_number,delivered_at_utc")
    assert len(lines) == 2
    assert ",800.00," in lines[1] and ",680.00" in lines[1]
