"""Push notifications for orders and order chat.

FCM itself is replaced by a recorder: these tests check who is told what, and
that each endpoint queues the push after its commit. `push_service.send` is
the boundary — everything up to the HTTP call to Google is real.
"""

import base64
import json

import pytest

from tests.test_customer_ordering import _add_burger, _close_with_lunch_hours, _tomorrow_dhaka
from tests.test_rider_dispatch import _as_rider

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


@pytest.fixture
def pushes(monkeypatch):
    """Every push the app tries to send, as {token, title, body, data}."""
    from app.services import push_service

    sent: list[dict] = []

    async def record(db, tokens, title, body, data=None):
        for token in tokens:
            sent.append({"token": token, "title": title, "body": body, "data": data or {}})
        return push_service.PushResult(sent=len(tokens), failed=0, deactivated=0)

    monkeypatch.setattr(push_service, "enabled", lambda: True)
    monkeypatch.setattr(push_service, "send", record)
    return sent


async def _device(client, headers, token):
    r = await client.post(
        f"{V1}/users/me/devices",
        json={"fcm_token": token, "platform": "ANDROID"},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text


def _to(pushes, token, kind="order_update"):
    return [p for p in pushes if p["token"] == token and p["data"].get("type") == kind]


async def _place(client, kitchen, shopper, **extra):
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id, **extra},
        headers=shopper.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


@pytest.fixture
async def phones(client, kitchen, shopper, riders):
    """A customer, the kitchen's owner and an on-shift rider, each with a
    registered phone."""
    rider = await riders(name="Karim")
    await _device(client, shopper.headers, "customer-phone-token")
    await _device(client, kitchen.headers, "vendor-phone-token")
    await _device(client, _as_rider(rider), "rider-phone-token")
    return rider


async def test_an_order_pushes_each_party_at_their_step(client, kitchen, shopper, phones, pushes):
    rider = phones
    order = await _place(client, kitchen, shopper)
    oid, n = order["id"], order["order_number"]

    # Placed: the vendor, and only the vendor.
    (placed,) = _to(pushes, "vendor-phone-token")
    assert placed["title"] == f"New order #{n}"
    assert placed["data"] == {
        "type": "order_update",
        "order_id": oid,
        "order_number": str(n),
        "status": "PENDING",
    }
    assert not _to(pushes, "customer-phone-token")

    r = await client.post(f"{V1}/vendor/orders/{oid}/accept", headers=kitchen.headers)
    assert r.status_code == 200, r.text
    (accepted,) = _to(pushes, "customer-phone-token")
    assert accepted["title"] == "Order accepted"
    assert kitchen.restaurant.name in accepted["body"]

    r = await client.post(f"{V1}/rider/offers/{oid}/accept", headers=_as_rider(rider))
    assert r.status_code == 200, r.text

    r = await client.post(f"{V1}/vendor/orders/{oid}/ready", headers=kitchen.headers)
    assert r.status_code == 200, r.text
    pin = r.json()["data"]["handoff_code"]
    (ready,) = _to(pushes, "rider-phone-token")
    assert ready["title"] == f"Order #{n} is ready"

    r = await client.post(
        f"{V1}/vendor/orders/{oid}/handoff", json={"rider_pin": pin}, headers=kitchen.headers
    )
    assert r.status_code == 200, r.text
    on_the_way = _to(pushes, "customer-phone-token")[-1]
    assert on_the_way["title"] == "Your order is on the way"
    assert on_the_way["body"].startswith("Karim picked up")

    r = await client.post(f"{V1}/rider/orders/{oid}/deliver", headers=_as_rider(rider))
    assert r.status_code == 200, r.text
    delivered = _to(pushes, "customer-phone-token")[-1]
    assert delivered["title"] == "Order delivered"
    assert delivered["data"]["status"] == "DELIVERED"

    # Three customer pushes in all: accepted, on the way, delivered.
    assert [p["data"]["status"] for p in _to(pushes, "customer-phone-token")] == [
        "PREPARING",
        "PICKED_UP",
        "DELIVERED",
    ]
    # And the vendor heard about the new order, nothing else.
    assert len(_to(pushes, "vendor-phone-token")) == 1


async def test_a_scheduled_order_says_when(client, kitchen, shopper, phones, pushes):
    await _close_with_lunch_hours(kitchen)
    order = await _place(client, kitchen, shopper, scheduled_for=_tomorrow_dhaka(12, 30))

    (placed,) = _to(pushes, "vendor-phone-token")
    assert placed["title"] == f"New scheduled order #{order['order_number']}"
    assert "12:30 PM" in placed["body"]


async def test_a_customer_cancel_tells_the_vendor(client, kitchen, shopper, phones, pushes):
    order = await _place(client, kitchen, shopper)
    r = await client.post(
        f"{V1}/orders/{order['id']}/cancel",
        json={"reason": "Ordered twice"},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text

    cancelled = _to(pushes, "vendor-phone-token")[-1]
    assert cancelled["title"] == f"Order #{order['order_number']} cancelled"
    assert cancelled["body"] == "The customer cancelled it: Ordered twice"
    assert not _to(pushes, "customer-phone-token"), "the customer did it; no need to tell them"


async def test_a_vendor_refusal_tells_the_customer_why(client, kitchen, shopper, phones, pushes):
    order = await _place(client, kitchen, shopper)
    r = await client.post(
        f"{V1}/vendor/orders/{order['id']}/reject",
        json={"reason": "Out of beef"},
        headers=kitchen.headers,
    )
    assert r.status_code == 200, r.text

    (declined,) = _to(pushes, "customer-phone-token")
    assert declined["title"] == f"Order #{order['order_number']} was declined"
    assert declined["body"].endswith(": Out of beef")


async def test_support_cancelling_tells_all_three(
    client, kitchen, shopper, phones, pushes, admin_token
):
    rider = phones
    order = await _place(client, kitchen, shopper)
    oid = order["id"]
    await client.post(f"{V1}/vendor/orders/{oid}/accept", headers=kitchen.headers)
    await client.post(f"{V1}/rider/offers/{oid}/accept", headers=_as_rider(rider))
    pushes.clear()

    r = await client.post(
        f"{V1}/admin/orders/{oid}/cancel",
        json={"reason": "Customer unreachable"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text

    for phone in ("customer-phone-token", "vendor-phone-token", "rider-phone-token"):
        (told,) = _to(pushes, phone)
        assert told["data"]["status"] == "CANCELLED", phone
    assert "Don't pick it up" in _to(pushes, "rider-phone-token")[0]["body"]


async def test_a_chat_message_reaches_everyone_but_its_sender(
    client, kitchen, shopper, phones, pushes
):
    rider = phones
    order = await _place(client, kitchen, shopper)
    oid = order["id"]
    await client.post(f"{V1}/vendor/orders/{oid}/accept", headers=kitchen.headers)
    await client.post(f"{V1}/rider/offers/{oid}/accept", headers=_as_rider(rider))
    pushes.clear()

    r = await client.post(
        f"{V1}/orders/{oid}/messages", json={"body": "Gate 2, please"}, headers=shopper.headers
    )
    assert r.status_code == 201, r.text

    assert not _to(pushes, "customer-phone-token", "chat_message")
    for phone in ("vendor-phone-token", "rider-phone-token"):
        (message,) = _to(pushes, phone, "chat_message")
        assert message["title"] == f"Rahim Uddin · Order #{order['order_number']}"
        assert message["body"] == "Gate 2, please"


async def test_nothing_is_attempted_without_a_key(client, kitchen, shopper, monkeypatch):
    """No key, no feature: the order goes through and no push is tried."""
    from app.services import order_push, push_service

    calls = []
    monkeypatch.setattr(push_service, "enabled", lambda: False)
    monkeypatch.setattr(push_service, "send", lambda *a, **k: calls.append(a))
    order = await _place(client, kitchen, shopper)
    assert await order_push.order_status(order["id"], "PENDING") == 0
    assert calls == []


def test_the_key_is_read_inline_or_base64(monkeypatch):
    from app.core.config import settings
    from app.services import push_service

    key = {"project_id": "p", "client_email": "a@p.iam", "private_key": "-----BEGIN…"}
    raw = json.dumps(key)
    for value in (raw, base64.b64encode(raw.encode()).decode()):
        monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", value)
        assert push_service._account() == key
        assert push_service.check_push_config() == {
            "status": "ok",
            "provider": "fcm",
            "project": "p",
        }

    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "{not json")
    assert push_service.check_push_config()["status"] == "error"


def test_scheduled_times_read_on_the_dhaka_clock():
    from datetime import UTC, datetime

    from app.models.order import Order
    from app.services.order_push import _when

    # 06:30 UTC is 12:30 PM in Dhaka.
    order = Order(scheduled_for=datetime(2026, 10, 4, 6, 30, tzinfo=UTC))
    assert _when(order) == "Sun 4 Oct, 12:30 PM"
