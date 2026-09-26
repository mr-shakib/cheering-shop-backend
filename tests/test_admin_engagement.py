"""Support tickets, notifications, admin invitations, ads and community."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

V1 = "/api/v1"

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _as(user) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user.id), str(user.role))}"}


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------


@pytest.fixture
async def tickets():
    """Remove tickets a test opened (users cascade them too, this is belt and braces)."""
    made: list[str] = []
    yield made
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.support import SupportTicket

    async with SessionLocal() as s:
        await s.execute(
            delete(SupportTicket).where(SupportTicket.id.in_([uuid.UUID(t) for t in made]))
        )
        await s.commit()


async def test_a_ticket_round_trip(client, admin, order_customer, tickets):
    me = _as(order_customer)
    r = await client.post(
        f"{V1}/support/tickets",
        json={
            "subject": "Rider was rude",
            "type": "RIDER_COMPLAINT",
            "message": "The rider was very rude when delivering my order.",
            "attachments": [{"url": "https://cdn.example.com/s.png", "name": "screenshot.png"}],
        },
        headers=me,
    )
    assert r.status_code == 201, r.text
    ticket = r.json()["data"]
    tickets.append(ticket["id"])
    assert ticket["code"] == f"TCK-{ticket['ticket_number']}"
    assert ticket["status"] == "OPEN"
    assert [m["kind"] for m in ticket["messages"]] == ["EVENT", "MESSAGE"]

    # Staff see it unread, open it, reply.
    r = await client.get(
        f"{V1}/admin/support/tickets?q=TCK-{ticket['ticket_number']}", headers=admin
    )
    [row] = r.json()["data"]
    assert row["unread"] is True
    assert row["user"]["full_name"] == "Rahim Uddin"
    assert r.json()["meta"]["counts"]["open"] >= 1

    await client.get(f"{V1}/admin/support/tickets/{ticket['id']}", headers=admin)
    r = await client.post(
        f"{V1}/admin/support/tickets/{ticket['id']}/messages",
        json={"body": "Sorry — let me look into this right away."},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    staff_view = r.json()["data"]
    assert staff_view["status"] == "PENDING"
    assert staff_view["assigned_to"] is not None
    assert staff_view["unread"] is False

    # The user sees the reply as unread, answers, and it is theirs to wait on no more.
    mine = (await client.get(f"{V1}/support/tickets", headers=me)).json()["data"]
    assert mine[0]["unread"] is True
    r = await client.post(
        f"{V1}/support/tickets/{ticket['id']}/messages",
        json={"body": "Order ID is ORD-48212."},
        headers=me,
    )
    assert r.json()["data"]["status"] == "OPEN"

    # Close, and nobody can write any more.
    r = await client.patch(
        f"{V1}/admin/support/tickets/{ticket['id']}",
        json={"status": "CLOSED", "priority": "HIGH"},
        headers=admin,
    )
    assert r.json()["data"]["status"] == "CLOSED"
    history = [m["body"] for m in r.json()["data"]["messages"] if m["kind"] == "EVENT"]
    assert "Marked closed" in history and "Priority set to high" in history
    r = await client.post(
        f"{V1}/support/tickets/{ticket['id']}/messages", json={"body": "hello?"}, headers=me
    )
    assert r.status_code == 409


async def test_tickets_are_private(client, order_customer, customer_user, tickets):
    r = await client.post(
        f"{V1}/support/tickets",
        json={"subject": "Refund", "type": "REFUND", "message": "Where is my refund?"},
        headers=_as(order_customer),
    )
    tickets.append(r.json()["data"]["id"])
    r = await client.get(f"{V1}/support/tickets/{tickets[0]}", headers=_as(customer_user))
    assert r.status_code == 404


async def test_a_ticket_can_only_cite_your_own_order(
    client, vendor, order_customer, customer_user, tickets
):
    from app.core.database import SessionLocal
    from app.models.order import Order

    order = Order(
        customer_id=order_customer.id,
        restaurant_id=vendor.restaurant.id,
        item_total=10_000,
        grand_total=10_000,
        payment_method="COD",
        delivery_address_text="x",
        delivery_latitude=23.79,
        delivery_longitude=90.40,
    )
    async with SessionLocal() as s:
        s.add(order)
        await s.commit()

    body = {"subject": "Late", "type": "ORDER_ISSUE", "message": "Late", "order_id": str(order.id)}
    r = await client.post(f"{V1}/support/tickets", json=body, headers=_as(customer_user))
    assert r.status_code == 404
    r = await client.post(f"{V1}/support/tickets", json=body, headers=_as(order_customer))
    assert r.status_code == 201
    tickets.append(r.json()["data"]["id"])
    assert r.json()["data"]["order_number"] == order.order_number


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@pytest.fixture
async def campaigns():
    made: list[str] = []
    yield made
    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.notification import NotificationCampaign

    async with SessionLocal() as s:
        await s.execute(
            delete(NotificationCampaign).where(
                NotificationCampaign.id.in_([uuid.UUID(c) for c in made])
            )
        )
        await s.commit()


async def test_send_now_reaches_the_audiences_inbox(
    client, admin, order_customer, vendor, campaigns
):
    me = _as(order_customer)
    r = await client.post(
        f"{V1}/users/me/devices",
        json={"fcm_token": f"token-{uuid.uuid4().hex}", "platform": "ANDROID"},
        headers=me,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"{V1}/admin/notifications",
        json={
            "title": "50% off all orders",
            "message": "Limited time deal!",
            "audience": "CUSTOMER",
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    campaign = r.json()["data"]
    campaigns.append(campaign["id"])
    assert campaign["status"] == "SENT"
    assert campaign["recipient_count"] >= 1
    assert campaign["push_enabled"] is False  # no FCM credentials in tests

    inbox = await client.get(f"{V1}/notifications", headers=me)
    assert inbox.json()["meta"]["unread"] >= 1
    item = next(i for i in inbox.json()["data"] if i["title"] == "50% off all orders")
    assert item["is_read"] is False

    # A vendor is not in a CUSTOMER campaign's audience.
    vendor_inbox = await client.get(f"{V1}/notifications", headers=vendor.headers)
    assert "50% off all orders" not in {i["title"] for i in vendor_inbox.json()["data"]}

    await client.post(f"{V1}/notifications/{item['id']}/read", headers=me)
    await client.post(f"{V1}/notifications/read-all", headers=me)
    assert (await client.get(f"{V1}/notifications", headers=me)).json()["meta"]["unread"] == 0


async def test_scheduled_campaigns_wait_for_the_worker(client, admin, order_customer, campaigns):
    from app.core.database import SessionLocal
    from app.models.notification import NotificationCampaign
    from app.services import notifications

    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = await client.post(
        f"{V1}/admin/notifications",
        json={
            "title": "Maintenance tonight",
            "message": "Brief downtime",
            "type": "ALERT",
            "audience": "ALL",
            "scheduled_for": later,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    campaign_id = r.json()["data"]["id"]
    campaigns.append(campaign_id)
    assert r.json()["data"]["status"] == "SCHEDULED"

    # Bring it due and run the sweep the worker runs every minute.
    async with SessionLocal() as s:
        row = await s.get(NotificationCampaign, uuid.UUID(campaign_id))
        row.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    async with SessionLocal() as s:
        assert await notifications.send_due(s) >= 1
        await s.commit()

    r = await client.get(f"{V1}/admin/notifications?status=SENT", headers=admin)
    assert campaign_id in {c["id"] for c in r.json()["data"]}
    inbox = (await client.get(f"{V1}/notifications", headers=_as(order_customer))).json()["data"]
    assert "Maintenance tonight" in {i["title"] for i in inbox}


async def test_a_scheduled_campaign_can_be_cancelled(client, admin, campaigns):
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = await client.post(
        f"{V1}/admin/notifications",
        json={"title": "Tomorrow", "message": "x", "audience": "RIDER", "scheduled_for": later},
        headers=admin,
    )
    campaigns.append(r.json()["data"]["id"])
    r = await client.post(f"{V1}/admin/notifications/{campaigns[0]}/cancel", headers=admin)
    assert r.json()["data"]["status"] == "CANCELLED"
    r = await client.post(f"{V1}/admin/notifications/{campaigns[0]}/cancel", headers=admin)
    assert r.status_code == 400

    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    r = await client.post(
        f"{V1}/admin/notifications",
        json={"title": "Past", "message": "x", "audience": "RIDER", "scheduled_for": past},
        headers=admin,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Admin invitations
# ---------------------------------------------------------------------------


async def test_invite_accept_and_sign_in(client, admin, cleanup_users, reset_limits):
    email = cleanup_users(f"new-admin-{uuid.uuid4().hex[:8]}@example.com")
    r = await client.post(
        f"{V1}/admin/invitations", json={"email": email, "full_name": "Jhony Peter"}, headers=admin
    )
    assert r.status_code == 201, r.text
    token = r.json()["data"]["debug_token"]
    assert r.json()["data"]["status"] == "PENDING"

    r = await client.get(f"{V1}/auth/admin-invitations/{token}")
    assert r.json()["data"]["email"] == email

    r = await client.post(
        f"{V1}/auth/admin-invitations/accept",
        json={"token": token, "full_name": "Jhony Peter", "password": "AdminPassword2!"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["user"]["role"] == "ADMIN"
    access = r.json()["data"]["tokens"]["access_token"]
    me = await client.get(f"{V1}/admin/dashboard", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200

    # One use only.
    r = await client.post(
        f"{V1}/auth/admin-invitations/accept",
        json={"token": token, "full_name": "Again", "password": "AdminPassword2!"},
    )
    assert r.status_code == 404

    r = await client.post(f"{V1}/admin/invitations", json={"email": email}, headers=admin)
    assert r.status_code == 409  # now has an account


async def test_reinviting_revokes_the_old_link(client, admin, reset_limits):
    email = f"pending-{uuid.uuid4().hex[:8]}@example.com"
    first = (
        await client.post(f"{V1}/admin/invitations", json={"email": email}, headers=admin)
    ).json()["data"]
    await client.post(f"{V1}/admin/invitations", json={"email": email}, headers=admin)
    r = await client.get(f"{V1}/auth/admin-invitations/{first['debug_token']}")
    assert r.status_code == 404

    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.platform import AdminInvitation

    async with SessionLocal() as s:
        await s.execute(delete(AdminInvitation).where(AdminInvitation.email == email))
        await s.commit()


# ---------------------------------------------------------------------------
# Advertisements
# ---------------------------------------------------------------------------


async def test_campaign_counters_and_admin_pause(client, admin, vendor):
    r = await client.post(
        f"{V1}/vendor/promotions",
        json={
            "discount_type": "PERCENTAGE",
            "discount_value": 20,
            "ends_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "budget_cap": 1779,
        },
        headers=vendor.headers,
    )
    assert r.status_code == 201, r.text
    promo_id = r.json()["data"]["id"]

    rid = str(vendor.restaurant.id)
    r = await client.post(
        f"{V1}/promotions/events", json={"impressions": [rid, rid], "clicks": [rid]}
    )
    assert r.json()["data"] == {"impressions": 1, "clicks": 1}

    r = await client.get(f"{V1}/admin/advertisements?restaurant_id={rid}", headers=admin)
    [ad] = r.json()["data"]
    assert (ad["campaign"], ad["impressions"], ad["clicks"], ad["status"]) == (
        "20% OFF",
        1,
        1,
        "ACTIVE",
    )
    assert ad["budget"] == 1779.0

    r = await client.patch(
        f"{V1}/admin/advertisements/{promo_id}", json={"status": "PAUSED"}, headers=admin
    )
    assert r.json()["data"]["status"] == "PAUSED"
    # A paused campaign stops counting.
    r = await client.post(f"{V1}/promotions/events", json={"impressions": [rid]})
    assert r.json()["data"]["impressions"] == 0

    await client.patch(
        f"{V1}/admin/advertisements/{promo_id}", json={"status": "ENDED"}, headers=admin
    )
    r = await client.patch(
        f"{V1}/admin/advertisements/{promo_id}", json={"status": "ACTIVE"}, headers=admin
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------


async def test_post_report_remove_and_ban(client, admin, order_customer, customer_user):
    author, reader = _as(order_customer), _as(customer_user)
    r = await client.post(
        f"{V1}/community/posts", json={"body": "Best grocery prices in Dhanmondi"}, headers=author
    )
    assert r.status_code == 201, r.text
    post_id = r.json()["data"]["id"]
    assert r.json()["data"]["is_mine"] is True

    for _ in range(2):
        r = await client.post(
            f"{V1}/community/posts/{post_id}/report", json={"reason": "spam"}, headers=reader
        )
    assert r.json()["data"]["report_count"] == 1  # once per reader
    r = await client.post(f"{V1}/community/posts/{post_id}/report", json={}, headers=author)
    assert r.status_code == 400

    r = await client.get(f"{V1}/admin/community/posts?status=REPORTED", headers=admin)
    row = next(p for p in r.json()["data"] if p["id"] == post_id)
    assert row["report_count"] == 1 and row["author_is_active"] is True

    r = await client.post(
        f"{V1}/admin/community/posts/{post_id}/remove",
        json={"reason": "Advertising"},
        headers=admin,
    )
    assert r.json()["data"]["is_removed"] is True
    feed = (await client.get(f"{V1}/community/posts", headers=reader)).json()["data"]
    assert post_id not in {p["id"] for p in feed}

    # Ban user: the existing block endpoint.
    r = await client.patch(
        f"{V1}/admin/users/{order_customer.id}/status", json={"is_active": False}, headers=admin
    )
    assert r.status_code == 200
    r = await client.post(f"{V1}/community/posts", json={"body": "back again"}, headers=author)
    assert r.status_code == 403
