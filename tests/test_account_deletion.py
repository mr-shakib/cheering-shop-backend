"""DELETE /users/me — account self-deletion, as Google Play requires.

The account's row survives (orders reference it with ON DELETE RESTRICT) but
nothing on it identifies the person any more, everything that was only about
them is gone, and the records that must be kept stay.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.usefixtures("db_available", "reset_limits")

V1 = "/api/v1"


def _auth(user) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


async def _seed_order(restaurant_id, customer_id, *, status: str, rider_id=None, fee: int = 0):
    """One order; money in paisa. `fee` is the delivery fee a rider earns."""
    from app.core.database import SessionLocal
    from app.models.order import Order

    now = datetime.now(UTC)
    order = Order(
        id=uuid.uuid4(),
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        status=status,
        item_total=100_000,
        delivery_fee=fee,
        grand_total=100_000 + fee,
        commission_amount=100_000,  # leaves the vendor nothing owed
        payment_method="COD",
        delivery_address_text="House 4, Road 2, Gulshan, Dhaka",
        delivery_latitude=23.7925,
        delivery_longitude=90.4078,
        delivery_contact_phone="+8801712345678",
        special_instructions="Call me at 01712345678",
        placed_at=now,
        delivered_at=now if status == "DELIVERED" else None,
        rider_id=rider_id,
        rider_role="RIDER" if rider_id else None,
    )
    async with SessionLocal() as s:
        s.add(order)
        await s.commit()
    return order


async def _reload(model, key):
    from app.core.database import SessionLocal

    async with SessionLocal() as s:
        return await s.get(model, key)


async def _count(model, *where) -> int:
    from app.core.database import SessionLocal

    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where)) or 0


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


async def test_customer_deletion_wipes_the_person_and_keeps_the_order(
    client, vendor, order_customer, rider
):
    from app.core.database import SessionLocal
    from app.models.address import Address
    from app.models.notification import UserNotification
    from app.models.order import Order
    from app.models.restaurant import Favorite
    from app.models.user import RefreshToken, User, UserDevice
    from app.services import token_service

    email = order_customer.email
    async with SessionLocal() as s:
        user = await s.get(User, order_customer.id)
        s.add(
            Address(
                user_id=user.id,
                street_address="House 4, Road 2",
                latitude=23.79,
                longitude=90.40,
                is_default=True,
            )
        )
        s.add(Favorite(user_id=user.id, restaurant_id=vendor.restaurant.id))
        s.add(UserDevice(user_id=user.id, fcm_token=f"fcm-{uuid.uuid4().hex}", platform="ANDROID"))
        s.add(UserNotification(user_id=user.id, title="Hi", message="Hello", type="UPDATE"))
        tokens = await token_service.issue_token_pair(s, user)
        await s.commit()
    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="DELIVERED", rider_id=rider.id
    )

    r = await client.request("DELETE", f"{V1}/users/me", json={}, headers=_auth(order_customer))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["message"] == "Your account has been deleted"

    gone = await _reload(User, order_customer.id)
    assert gone.deleted_at is not None
    assert gone.is_active is False
    assert (gone.email, gone.phone, gone.full_name, gone.avatar_url) == (None, None, None, None)
    for model in (Address, Favorite, UserDevice, UserNotification, RefreshToken):
        assert await _count(model, model.user_id == order_customer.id) == 0, model.__name__

    # The order is a record we keep; how to reach the customer is not.
    kept = await _reload(Order, order.id)
    assert kept.delivery_address_text == "House 4, Road 2, Gulshan, Dhaka"
    assert kept.delivery_contact_phone is None
    assert kept.special_instructions is None

    # The email is free again: nothing answers to it.
    assert await _count(User, User.email == email) == 0

    # The access token still in the app's hands stops working at once, and
    # the refresh token can mint nothing.
    r = await client.get(f"{V1}/users/me", headers=_auth(order_customer))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "ACCOUNT_DELETED"
    r = await client.post(f"{V1}/auth/refresh", json={"refresh_token": tokens.refresh_token})
    assert r.status_code == 401


async def test_no_body_is_accepted_for_an_account_without_a_password(client, order_customer):
    r = await client.delete(f"{V1}/users/me", headers=_auth(order_customer))
    assert r.status_code == 200, r.text


async def test_a_password_account_must_confirm_with_its_password(client, order_customer):
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User

    async with SessionLocal() as s:
        user = await s.get(User, order_customer.id)
        user.password_hash = hash_password("CorrectHorse9!")
        await s.commit()
    headers = _auth(order_customer)

    r = await client.request("DELETE", f"{V1}/users/me", json={}, headers=headers)
    assert r.status_code == 400
    r = await client.request(
        "DELETE", f"{V1}/users/me", json={"password": "wrong-password"}, headers=headers
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert (await _reload(User, order_customer.id)).deleted_at is None

    r = await client.request(
        "DELETE", f"{V1}/users/me", json={"password": "CorrectHorse9!"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert (await _reload(User, order_customer.id)).password_hash is None


async def test_refused_while_an_order_is_under_way(client, vendor, order_customer):
    from app.models.user import User

    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PREPARING")

    r = await client.delete(f"{V1}/users/me", headers=_auth(order_customer))
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "ACCOUNT_HAS_ACTIVE_ORDERS"
    assert error["details"] == [f"Order #{order.order_number}"]
    assert (await _reload(User, order_customer.id)).deleted_at is None


async def test_administrators_cannot_delete_themselves_here(client, admin_token):
    r = await client.delete(
        f"{V1}/users/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 403


async def test_admin_cannot_unblock_a_deleted_account_and_no_longer_lists_it(
    client, order_customer, admin_token
):
    admin = {"Authorization": f"Bearer {admin_token}"}
    r = await client.delete(f"{V1}/users/me", headers=_auth(order_customer))
    assert r.status_code == 200, r.text

    r = await client.patch(
        f"{V1}/admin/users/{order_customer.id}/status", json={"is_active": True}, headers=admin
    )
    assert r.status_code == 409

    r = await client.get(f"{V1}/admin/customers", params={"limit": 100}, headers=admin)
    assert r.status_code == 200, r.text
    assert str(order_customer.id) not in {row["id"] for row in r.json()["data"]}


# ---------------------------------------------------------------------------
# Riders
# ---------------------------------------------------------------------------


async def test_rider_with_unpaid_earnings_is_refused(client, vendor, order_customer, riders):
    from app.models.user import User

    rider = await riders()
    await _seed_order(
        vendor.restaurant.id, order_customer.id, status="DELIVERED", rider_id=rider.id, fee=6_000
    )

    r = await client.delete(f"{V1}/users/me", headers=_auth(rider))
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "ACCOUNT_HAS_BALANCE"
    assert error["details"] == ["Unpaid balance: ৳60.00"]
    assert (await _reload(User, rider.id)).deleted_at is None


async def test_rider_deletion_takes_them_off_shift_and_wipes_their_documents(client, riders):
    from app.core.database import SessionLocal
    from app.models.rider import RiderProfile

    rider = await riders(is_online=True)
    async with SessionLocal() as s:
        profile = await s.get(RiderProfile, rider.id)
        profile.national_id = "1990123456789"
        profile.license_number = "DK-0042"
        profile.documents = {"nid": "https://cdn.example/nid.jpg"}
        profile.payout = {"method": "BKASH", "account_number": "01712447567"}
        await s.commit()

    r = await client.delete(f"{V1}/users/me", headers=_auth(rider))
    assert r.status_code == 200, r.text

    profile = await _reload(RiderProfile, rider.id)
    assert profile.is_online is False
    assert (profile.national_id, profile.license_number) == (None, None)
    assert (profile.documents, profile.payout) == ({}, {})
    assert profile.vehicle_type == "MOTORCYCLE"


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


async def test_vendor_deletion_closes_the_store_for_good(client, vendor):
    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    async with SessionLocal() as s:
        r = await s.get(Restaurant, vendor.restaurant.id)
        r.status = "OPEN"
        r.business_hours = {"mon": {"is_open": True, "opens_at": "09:00", "closes_at": "23:00"}}
        await s.commit()
    assert (await client.get(f"{V1}/restaurants/{vendor.restaurant.id}")).status_code == 200

    r = await client.delete(f"{V1}/users/me", headers=vendor.headers)
    assert r.status_code == 200, r.text

    store = await _reload(Restaurant, vendor.restaurant.id)
    assert (store.is_active, store.status, store.business_hours) == (False, "CLOSED", None)
    assert (await client.get(f"{V1}/restaurants/{vendor.restaurant.id}")).status_code == 404


async def test_vendor_with_an_unpaid_balance_is_refused(client, vendor, order_customer, rider):
    from app.core.database import SessionLocal
    from app.models.order import Order

    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="DELIVERED", rider_id=rider.id
    )
    async with SessionLocal() as s:
        row = await s.get(Order, order.id)
        row.commission_amount = 15_000  # the vendor is now owed ৳850
        await s.commit()

    r = await client.delete(f"{V1}/users/me", headers=vendor.headers)
    assert r.status_code == 409
    assert r.json()["error"]["details"] == ["Unpaid balance: ৳850.00"]
