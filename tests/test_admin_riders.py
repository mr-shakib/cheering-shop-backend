"""Settings, and the rider side of the admin console: applications, profile,
earnings, incentives, withdrawals and live tracking."""

import uuid
from datetime import UTC, datetime

import pytest

V1 = "/api/v1"

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _as(user) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user.id), str(user.role))}"}


@pytest.fixture
async def fresh_settings():
    """The settings row is shared by the whole suite: put it back to all
    server defaults before and after."""
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.platform import PlatformSettings

    async def _reset():
        async with SessionLocal() as s:
            await s.execute(
                update(PlatformSettings)
                .where(PlatformSettings.id == 1)
                .values(
                    app_name=None,
                    support_email=None,
                    support_phone=None,
                    delivery_base_fee=None,
                    delivery_per_km_fee=None,
                    delivery_min_fee=None,
                    restaurant_commission_rate=None,
                    grocery_commission_rate=None,
                    pharmacy_commission_rate=None,
                    rain_surcharge=0,
                    rain_surcharge_active=False,
                    heatwave_fee=0,
                    heatwave_fee_active=False,
                    high_demand_fee=0,
                    high_demand_fee_active=False,
                )
            )
            await s.commit()

    await _reset()
    yield
    await _reset()


@pytest.fixture(autouse=True)
async def clear_rider_geo():
    from app.core.redis import RIDER_GEO_KEY, get_redis

    async def _wipe():
        redis = get_redis()
        await redis.delete(RIDER_GEO_KEY)
        keys = [k async for k in redis.scan_iter("rider:*:state")]
        if keys:
            await redis.delete(*keys)

    await _wipe()
    yield
    await _wipe()


async def _seed_order(
    restaurant_id, customer_id, rider_id, *, status="DELIVERED", fee=6_000, tip=2_000
):
    from app.core.database import SessionLocal
    from app.models.order import Order

    now = datetime.now(UTC)
    order = Order(
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        rider_id=rider_id,
        rider_role="RIDER",
        status=status,
        item_total=50_000,
        delivery_fee=fee,
        tip=tip,
        grand_total=50_000 + fee + tip,
        commission_amount=7_500,
        payment_method="COD",
        delivery_address_text="House 4, Road 2, Gulshan, Dhaka",
        delivery_latitude=23.7925,
        delivery_longitude=90.4078,
        placed_at=now,
        delivered_at=now if status == "DELIVERED" else None,
    )
    async with SessionLocal() as s:
        s.add(order)
        await s.commit()
    return order


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def test_settings_fall_back_to_the_server_config(client, admin, fresh_settings):
    from app.core.config import settings

    r = await client.get(f"{V1}/admin/settings", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["delivery_base_fee"] == settings.DELIVERY_FEE_BASE
    assert d["restaurant_commission_rate"] == settings.DEFAULT_COMMISSION_BASIS_POINTS / 10_000
    assert "delivery_base_fee" in d["using_server_defaults"]
    assert d["active_surcharge_total"] == 0


async def test_delivery_settings_price_the_next_checkout(
    client, admin, kitchen, shopper, fresh_settings
):
    await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 1},
        headers=shopper.headers,
    )
    summary = f"{V1}/checkout/summary?address_id={shopper.address_id}"
    before = (await client.get(summary, headers=shopper.headers)).json()["data"]["delivery_fee"]

    r = await client.patch(
        f"{V1}/admin/settings",
        json={"delivery_base_fee": 50, "rain_surcharge": {"amount": 15, "active": True}},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["active_surcharge_total"] == 15
    from app.core.config import settings

    after = (await client.get(summary, headers=shopper.headers)).json()["data"]["delivery_fee"]
    assert after == before - settings.DELIVERY_FEE_BASE + 50 + 15

    # A minimum above the distance fee wins; switching the surcharge off drops it.
    await client.patch(
        f"{V1}/admin/settings",
        json={"delivery_min_fee": 500, "rain_surcharge": {"active": False}},
        headers=admin,
    )
    assert (await client.get(summary, headers=shopper.headers)).json()["data"][
        "delivery_fee"
    ] == 500

    # null hands the fields back to the config.
    r = await client.patch(
        f"{V1}/admin/settings",
        json={"delivery_base_fee": None, "delivery_min_fee": None},
        headers=admin,
    )
    assert "delivery_base_fee" in r.json()["data"]["using_server_defaults"]
    assert (await client.get(summary, headers=shopper.headers)).json()["data"][
        "delivery_fee"
    ] == before


async def test_per_type_commission_is_the_new_vendor_default(client, admin, fresh_settings):
    from app.core.database import SessionLocal
    from app.services import platform_settings

    await client.patch(
        f"{V1}/admin/settings", json={"grocery_commission_rate": 0.12}, headers=admin
    )
    async with SessionLocal() as s:
        assert await platform_settings.default_commission_rate(s, "GROCERY") == 0.12
        assert await platform_settings.default_commission_rate(s, "RESTAURANT") == 0.15


async def test_settings_reject_nonsense(client, admin, fresh_settings, vendor):
    for bad in ({"grocery_commission_rate": 12}, {"delivery_base_fee": -1}, {"theme": "dark"}):
        r = await client.patch(f"{V1}/admin/settings", json=bad, headers=admin)
        assert r.status_code == 400, (bad, r.text)
    r = await client.get(f"{V1}/admin/settings", headers=vendor.headers)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Rider applications
# ---------------------------------------------------------------------------


@pytest.fixture
async def applicant():
    """A unique applicant email, with every row it produces removed after."""
    email = f"rider-app-{uuid.uuid4().hex[:10]}@example.com"
    yield email

    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.rider_application import RiderApplication
    from app.models.user import User

    async with SessionLocal() as s:
        await s.execute(delete(RiderApplication).where(RiderApplication.email == email))
        await s.execute(delete(User).where(User.email == email))
        await s.commit()


def _application(email: str, **overrides) -> dict:
    body = {
        "full_name": "Omar Farouk",
        "email": email,
        "phone": f"+88017{uuid.uuid4().int % 10**8:08d}",
        "vehicle_type": "CYCLE",
        "date_of_birth": "2000-06-12",
        "national_id": "465454556",
        "documents": {
            "nid": "https://cdn.example.com/nid.pdf",
            "profile_photo": "https://cdn.example.com/me.jpg",
        },
        "payout": {
            "method": "BKASH",
            "account_name": "Omar Farouk",
            "account_number": "01712345678",
        },
        "agreed_to_terms": True,
    }
    body.update(overrides)
    return body


async def test_a_rider_applies_and_is_approved(client, admin, applicant, reset_limits):
    r = await client.post(f"{V1}/rider-applications", json=_application(applicant))
    assert r.status_code == 201, r.text
    number = r.json()["data"]["application_no"]
    assert number.startswith("RDR-")

    again = await client.post(f"{V1}/rider-applications", json=_application(applicant))
    assert again.status_code == 409

    r = await client.get(f"{V1}/rider-applications/{number}?email={applicant}")
    assert r.json()["data"]["status"] == "PENDING"
    r = await client.get(f"{V1}/rider-applications/{number}?email=someone@example.com")
    assert r.status_code == 404

    r = await client.get(f"{V1}/admin/rider-applications?q={number}", headers=admin)
    [row] = r.json()["data"]
    assert row["documents"]["nid"].endswith("nid.pdf")

    r = await client.post(
        f"{V1}/admin/rider-applications/{row['id']}/approve",
        json={"password": "RiderPassword1!"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    rider_id = r.json()["data"]["rider_id"]

    r = await client.get(f"{V1}/admin/riders/{rider_id}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["national_id"] == "465454556"
    assert d["date_of_birth"] == "2000-06-12"
    assert d["is_verified"] is True and d["is_online"] is False
    assert d["avatar_url"].endswith("me.jpg")

    login = await client.post(
        f"{V1}/auth/login", json={"email": applicant, "password": "RiderPassword1!"}
    )
    assert login.status_code == 200, login.text

    r = await client.post(
        f"{V1}/admin/rider-applications/{row['id']}/reject", json={"note": "late"}, headers=admin
    )
    assert r.status_code == 409  # already decided


async def test_a_rejected_applicant_sees_the_reason(client, admin, applicant, reset_limits):
    r = await client.post(f"{V1}/rider-applications", json=_application(applicant))
    number = r.json()["data"]["application_no"]
    r = await client.get(f"{V1}/admin/rider-applications?q={number}", headers=admin)
    app_id = r.json()["data"][0]["id"]

    r = await client.post(
        f"{V1}/admin/rider-applications/{app_id}/reject",
        json={"note": "NID photo is unreadable"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{V1}/rider-applications/{number}?email={applicant}")
    assert r.json()["data"] == {
        **r.json()["data"],
        "status": "REJECTED",
        "review_note": "NID photo is unreadable",
    }


async def test_motorised_applicants_need_a_licence(client, applicant, reset_limits):
    r = await client.post(
        f"{V1}/rider-applications", json=_application(applicant, vehicle_type="MOTORCYCLE")
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Profile, earnings, incentives, withdrawals
# ---------------------------------------------------------------------------


async def test_admin_edits_a_riders_profile(client, admin, riders):
    rider = await riders(name="Liam O'Connor")
    r = await client.patch(
        f"{V1}/admin/riders/{rider.id}",
        json={"national_id": "1990123", "date_of_birth": "1995-01-02", "vehicle_type": "BIKE"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert (d["national_id"], d["date_of_birth"], d["vehicle_type"]) == (
        "1990123",
        "1995-01-02",
        "BIKE",
    )

    r = await client.get(f"{V1}/admin/riders?q=Liam O'Connor", headers=admin)
    [row] = r.json()["data"]
    assert row["live_status"] == "ONLINE"
    assert "rating_avg" in row


async def test_rider_earnings_withdrawal_and_mark_unpaid(
    client, admin, riders, vendor, order_customer
):
    rider = await riders(name="Earning Rider")
    for _ in range(2):  # 2 × (৳60 delivery + ৳20 tip)
        await _seed_order(vendor.restaurant.id, order_customer.id, rider.id)
    await _seed_order(vendor.restaurant.id, order_customer.id, rider.id, status="PICKED_UP")

    r = await client.post(
        f"{V1}/admin/riders/{rider.id}/incentives",
        json={"amount": 100, "reason": "Rain bonus"},
        headers=admin,
    )
    assert r.status_code == 200, r.text

    me = _as(rider)
    wallet = (await client.get(f"{V1}/rider/earnings", headers=me)).json()["data"]
    assert wallet["totals"] == {
        "delivery_earning": 120.0,
        "tips": 40.0,
        "incentives": 100.0,
        "total": 260.0,
    }
    assert wallet["today"] == 260.0
    assert wallet["available_balance"] == 260.0

    days = (await client.get(f"{V1}/rider/earnings/days", headers=me)).json()["data"]
    assert days[0]["date"] == str(datetime.now(UTC).date())
    assert (days[0]["orders"], days[0]["total"]) == (2, 260.0)

    payout = {
        "amount": 200,
        "method": "BKASH",
        "account_number": "01712345678",
        "account_name": "Rider",
    }
    r = await client.post(f"{V1}/rider/payouts", json=payout, headers=me)
    assert r.status_code == 201, r.text
    payout_id = r.json()["data"]["id"]
    r = await client.post(f"{V1}/rider/payouts", json={**payout, "amount": 100}, headers=me)
    assert r.status_code == 400  # only ৳60 left

    r = await client.get(f"{V1}/admin/rider-payouts?rider_id={rider.id}", headers=admin)
    [row] = r.json()["data"]
    assert row["rider_name"] == "Earning Rider"

    assert (
        await client.post(f"{V1}/admin/rider-payouts/{payout_id}/complete", headers=admin)
    ).status_code == 200
    r = await client.post(
        f"{V1}/admin/rider-payouts/{payout_id}/reopen",
        json={"reason": "bKash bounced"},
        headers=admin,
    )
    assert r.json()["data"]["status"] == "PROCESSING"
    assert (await client.get(f"{V1}/rider/earnings", headers=me)).json()["data"][
        "available_balance"
    ] == 60.0

    await client.post(
        f"{V1}/admin/rider-payouts/{payout_id}/fail", json={"reason": "Wrong number"}, headers=admin
    )
    assert (await client.get(f"{V1}/rider/earnings", headers=me)).json()["data"][
        "available_balance"
    ] == 260.0

    detail = (await client.get(f"{V1}/admin/riders/{rider.id}", headers=admin)).json()["data"]
    assert detail["delivered_orders"] == 2
    assert detail["earnings"]["totals"]["total"] == 260.0
    r = await client.get(f"{V1}/admin/riders/{rider.id}/earnings", headers=admin)
    assert r.json()["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# Live tracking
# ---------------------------------------------------------------------------


async def test_live_map_shows_position_and_what_each_rider_is_doing(
    client, admin, riders, vendor, order_customer
):
    idle = await riders(name="Idle Rider")
    busy = await riders(name="Busy Rider")
    await _seed_order(vendor.restaurant.id, order_customer.id, busy.id, status="PREPARING")
    await riders(name="Off Shift", is_online=False)

    r = await client.post(
        f"{V1}/rider/location", json={"latitude": 23.79, "longitude": 90.40}, headers=_as(busy)
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"{V1}/admin/riders/live", headers=admin)
    assert r.status_code == 200, r.text
    by_id = {x["id"]: x for x in r.json()["data"]}
    assert by_id[str(idle.id)]["status"] == "AVAILABLE"
    assert by_id[str(idle.id)]["has_live_location"] is False
    b = by_id[str(busy.id)]
    assert b["status"] == "HEADING_TO_PICKUP"
    assert b["has_live_location"] is True
    assert b["orders"][0]["distance_to_dropoff_km"] is not None
    assert "Off Shift" not in {x["full_name"] for x in r.json()["data"]}

    r = await client.get(f"{V1}/admin/riders/live?status=AVAILABLE", headers=admin)
    assert str(busy.id) not in {x["id"] for x in r.json()["data"]}
