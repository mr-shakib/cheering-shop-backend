"""Vendor signup and the admin approval gate.

The specification defines a VENDOR role and a permission matrix but no way to
create a vendor account — every signup path it describes produces a CUSTOMER.
These cover the flow that closes that gap.
"""

import uuid

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


def _email() -> str:
    return f"vendor-{uuid.uuid4().hex[:10]}@example.com"


def _restaurant(name: str | None = None) -> dict:
    return {
        "name": name or f"Test Kitchen {uuid.uuid4().hex[:6]}",
        "description": "Authentic Bangladeshi cuisine",
        "phone": "+8801712345678",
        "address_line": "House 12, Road 8, Dhanmondi, Dhaka",
        "latitude": 23.7936,
        "longitude": 90.4064,
        "cuisine_types": ["Bengali", "Biryani"],
    }


async def _register_vendor(client, cleanup, name: str | None = None) -> tuple[str, dict]:
    email = _email()
    cleanup(email)
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    assert r.status_code == 200, r.text
    code = r.json()["data"]["debug_code"]

    r = await client.post(
        f"{V1}/auth/register/vendor",
        json={
            "email": email,
            "code": code,
            "password": "VendorPass1!",
            "full_name": "Karim Ahmed",
            "restaurant": _restaurant(name),
        },
    )
    assert r.status_code == 201, r.text
    return email, r.json()["data"]


async def test_vendor_registration_creates_account_and_restaurant(
    client, cleanup_users, reset_limits
):
    email, data = await _register_vendor(client, cleanup_users)

    assert data["user"]["role"] == "VENDOR"
    assert data["user"]["is_email_verified"] is True
    assert "access_token" in data["tokens"]

    restaurant = data["restaurant"]
    assert restaurant["slug"], "no slug generated"
    assert restaurant["is_verified"] is False, "a new restaurant must await approval"
    assert restaurant["status"] == "CLOSED"
    assert "awaiting approval" in data["next_step"].lower()


async def test_vendor_can_sign_in_immediately(client, cleanup_users, reset_limits):
    """Waiting for approval must not block the vendor from building their menu."""
    email, _ = await _register_vendor(client, cleanup_users)

    r = await client.post(f"{V1}/auth/login", json={"email": email, "password": "VendorPass1!"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["user"]["role"] == "VENDOR"


async def test_vendor_reaches_vendor_endpoints_customer_does_not(
    client, cleanup_users, reset_limits, customer_token
):
    """The role guard must actually distinguish them."""
    _, data = await _register_vendor(client, cleanup_users)
    vendor_auth = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    # Vendor reaches the handler. A brand-new restaurant has no orders, so an
    # empty queue is the correct answer — what matters is that it is a 200 and
    # not a 403.
    r = await client.get(f"{V1}/vendor/orders", headers=vendor_auth)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []

    # Customer is stopped by the guard
    r = await client.get(
        f"{V1}/vendor/orders", headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert r.status_code == 403


async def test_duplicate_restaurant_names_get_distinct_slugs(client, cleanup_users, reset_limits):
    """`restaurants.slug` is UNIQUE and two "Pizza House" vendors is not exotic."""
    shared = f"Pizza House {uuid.uuid4().hex[:4]}"
    _, first = await _register_vendor(client, cleanup_users, name=shared)
    _, second = await _register_vendor(client, cleanup_users, name=shared)

    assert first["restaurant"]["slug"] != second["restaurant"]["slug"]
    assert second["restaurant"]["slug"].startswith(first["restaurant"]["slug"])


async def test_customer_email_cannot_become_a_vendor(
    client, cleanup_users, reset_limits, clear_cooldowns
):
    """Roles are fixed at creation — the composite role-guard FKs make a live
    change unsafe, and silently converting an account would be surprising."""
    email = _email()
    cleanup_users(email)

    # Register as a customer first
    code = (
        await client.post(f"{V1}/auth/otp/send", json={"email": email})
    ).json()["data"]["debug_code"]
    r = await client.post(f"{V1}/auth/otp/verify", json={"email": email, "code": code})
    assert r.status_code == 200

    # Now try to register the same address as a vendor
    await clear_cooldowns()  # a second code within 60s is correctly refused
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    code = r.json()["data"]["debug_code"]
    r = await client.post(
        f"{V1}/auth/register/vendor",
        json={"email": email, "code": code, "password": "VendorPass1!",
              "full_name": "Karim", "restaurant": _restaurant()},
    )
    assert r.status_code == 409, r.text
    assert "customer account" in r.json()["error"]["message"].lower()


async def test_one_restaurant_per_vendor(client, cleanup_users, reset_limits, clear_cooldowns):
    """Decision D1: UNIQUE(owner_id). A second attempt must 409, not 500."""
    email, _ = await _register_vendor(client, cleanup_users)

    await clear_cooldowns()
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    code = r.json()["data"]["debug_code"]
    r = await client.post(
        f"{V1}/auth/register/vendor",
        json={"email": email, "code": code, "password": "VendorPass1!",
              "full_name": "Karim", "restaurant": _restaurant()},
    )
    assert r.status_code == 409, r.text


async def test_self_service_role_escalation_is_blocked(client, cleanup_users, reset_limits):
    """Only CUSTOMER and VENDOR are self-service. Nobody makes themselves an
    admin by editing a JSON body."""
    email = _email()
    cleanup_users(email)
    for role in ("ADMIN", "RIDER"):
        r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": role})
        assert r.status_code == 400, f"{role} was accepted as a self-service role"


# ---------------------------------------------------------------------------
# Admin approval — the admin_token fixture lives in conftest.py, shared with
# tests/test_vendor_application.py
# ---------------------------------------------------------------------------


async def test_admin_approval_makes_a_restaurant_visible(
    client, cleanup_users, reset_limits, admin_token
):
    _, data = await _register_vendor(client, cleanup_users)
    restaurant_id = data["restaurant"]["id"]
    admin = {"Authorization": f"Bearer {admin_token}"}

    # It appears in the pending queue
    r = await client.get(f"{V1}/admin/restaurants/pending", headers=admin)
    assert r.status_code == 200, r.text
    assert restaurant_id in [x["id"] for x in r.json()["data"]]

    # Approve
    r = await client.post(
        f"{V1}/admin/restaurants/{restaurant_id}/verify",
        json={"is_verified": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["restaurant"]["is_verified"] is True

    # It leaves the queue
    r = await client.get(f"{V1}/admin/restaurants/pending", headers=admin)
    assert restaurant_id not in [x["id"] for x in r.json()["data"]]


async def test_suspending_closes_the_store(client, cleanup_users, reset_limits, admin_token):
    """Suspending must take it offline, not just hide it — otherwise in-flight
    traffic keeps ordering from a suspended vendor."""
    _, data = await _register_vendor(client, cleanup_users)
    restaurant_id = data["restaurant"]["id"]
    admin = {"Authorization": f"Bearer {admin_token}"}

    await client.post(
        f"{V1}/admin/restaurants/{restaurant_id}/verify",
        json={"is_verified": True}, headers=admin,
    )
    r = await client.post(
        f"{V1}/admin/restaurants/{restaurant_id}/verify",
        json={"is_verified": False}, headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["restaurant"]["status"] == "CLOSED"


async def test_non_admin_cannot_approve(client, cleanup_users, reset_limits, customer_token):
    """The approval gate is worthless if a vendor can approve themselves."""
    _, data = await _register_vendor(client, cleanup_users)
    restaurant_id = data["restaurant"]["id"]

    for token, who in (
        (data["tokens"]["access_token"], "the vendor themselves"),
        (customer_token, "a customer"),
    ):
        r = await client.post(
            f"{V1}/admin/restaurants/{restaurant_id}/verify",
            json={"is_verified": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, f"{who} approved a restaurant"
