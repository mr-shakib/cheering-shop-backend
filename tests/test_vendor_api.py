"""Vendor operations: storefront, menu, order queue, handoff, analytics.

Orders are seeded directly through the ORM rather than placed through the API,
because `POST /orders` is still a 501 stub. That is not a shortcut around the
system under test — the vendor endpoints are the system under test, and seeding
lets them be exercised against real rows with every check constraint live. A
mis-shaped Order (bad total arithmetic, a PICKED_UP row with no rider) fails at
the database, so the fixtures cannot quietly drift from what the application
will actually produce.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _seed_order(
    restaurant_id,
    customer_id,
    *,
    status: str = "PENDING",
    item_total: int = 100_000,
    commission: int = 15_000,
    rider_id=None,
    delivered_at=None,
    with_items: bool = False,
):
    """Insert one order. Money is in paisa — 100_000 == 1000 taka."""
    from app.core.database import SessionLocal
    from app.models.order import Order, OrderItem

    now = datetime.now(UTC)
    order = Order(
        id=uuid.uuid4(),
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        status=status,
        item_total=item_total,
        grand_total=item_total,
        commission_amount=commission,
        payment_method="COD",
        delivery_address_text="House 4, Road 2, Gulshan, Dhaka",
        delivery_latitude=23.7925,
        delivery_longitude=90.4078,
        delivery_contact_phone="+8801712345678",
        special_instructions="Ring the bell twice",
        placed_at=now,
        auto_decline_at=now + timedelta(seconds=60) if status == "PENDING" else None,
        delivered_at=delivered_at,
        rider_id=rider_id,
        rider_role="RIDER" if rider_id else None,
    )
    async with SessionLocal() as session:
        session.add(order)
        await session.flush()
        if with_items:
            session.add(
                OrderItem(
                    order_id=order.id,
                    item_name="Chicken Biryani",
                    variant_name="Full",
                    unit_price=item_total,
                    add_ons_total=0,
                    quantity=1,
                    line_total=item_total,
                    notes="Extra spicy",
                )
            )
        await session.commit()
    return order


async def _approve_and_open(restaurant_id) -> None:
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    async with SessionLocal() as session:
        await session.execute(
            update(Restaurant)
            .where(Restaurant.id == restaurant_id)
            .values(is_verified=True, status="OPEN")
        )
        await session.commit()


async def _make_category(client, vendor, name="Biryani") -> str:
    r = await client.post(
        f"{V1}/vendor/menu/categories", json={"name": name}, headers=vendor.headers
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def _make_item(client, vendor, category_id, **overrides) -> dict:
    payload = {
        "name": "Chicken Biryani",
        "category_id": category_id,
        "base_price": 180,
        "variants": [
            {"name": "Half", "price": 180, "is_default": True},
            {"name": "Full", "price": 320},
        ],
        "add_ons": [{"name": "Extra raita", "price": 30}],
    }
    payload.update(overrides)
    r = await client.post(f"{V1}/vendor/menu/items", json=payload, headers=vendor.headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def test_customer_cannot_reach_vendor_endpoints(client, customer_token):
    """The role guard, on a route that now returns real data."""
    r = await client.get(
        f"{V1}/vendor/profile", headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_vendor_endpoints_require_a_token(client):
    r = await client.get(f"{V1}/vendor/profile")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Storefront
# ---------------------------------------------------------------------------


async def test_profile_returns_the_owners_view(client, vendor):
    r = await client.get(f"{V1}/vendor/profile", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["id"] == str(vendor.restaurant.id)
    assert data["is_verified"] is True
    # Verified but CLOSED — the vendor's own switch is still off.
    assert data["is_accepting_orders"] is False
    assert data["commission_rate"] == 0.15


async def test_pending_vendor_can_read_their_own_restaurant(client, pending_vendor):
    """The reason this endpoint exists: discovery would 404 an unapproved store."""
    r = await client.get(f"{V1}/vendor/profile", headers=pending_vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_verified"] is False


async def test_profile_update_applies_only_what_was_sent(client, vendor):
    r = await client.patch(
        f"{V1}/vendor/profile",
        json={"description": "Authentic Bengali", "delivery_fee_base": 70},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["description"] == "Authentic Bengali"
    assert data["delivery_fee_base"] == 70
    # Untouched by a PATCH that never mentioned it.
    assert data["name"] == vendor.restaurant.name


async def test_renaming_does_not_change_the_slug(client, vendor):
    """The slug is the public URL — a rebrand must not break existing links."""
    original = vendor.restaurant.slug
    r = await client.patch(
        f"{V1}/vendor/profile", json={"name": "Kitchen & Grill"}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"] == "Kitchen & Grill"
    assert r.json()["data"]["slug"] == original


async def test_profile_rejects_fields_the_vendor_does_not_own(client, vendor):
    for field, value in (
        ("is_verified", True),
        ("commission_rate", 0),
        ("slug", "something-else"),
    ):
        r = await client.patch(f"{V1}/vendor/profile", json={field: value}, headers=vendor.headers)
        assert r.status_code == 400, f"{field}: {r.text}"
        assert r.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_coordinates_must_move_together(client, vendor):
    r = await client.patch(f"{V1}/vendor/profile", json={"latitude": 24.0}, headers=vendor.headers)
    assert r.status_code == 400, r.text
    assert "together" in r.json()["error"]["message"]

    r = await client.patch(
        f"{V1}/vendor/profile", json={"latitude": 24.0, "longitude": 90.5}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["latitude"] == 24.0


async def test_store_status_is_honest_about_approval(client, pending_vendor):
    """Opening an unapproved store is accepted and does nothing — and says so."""
    r = await client.patch(
        f"{V1}/vendor/store/status", json={"status": "OPEN"}, headers=pending_vendor.headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "OPEN"
    assert data["is_accepting_orders"] is False
    assert "awaiting approval" in data["message"]


async def test_store_status_opens_an_approved_restaurant(client, vendor):
    r = await client.patch(
        f"{V1}/vendor/store/status", json={"status": "OPEN"}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_accepting_orders"] is True

    r = await client.patch(
        f"{V1}/vendor/store/status", json={"status": "CLOSED"}, headers=vendor.headers
    )
    assert r.json()["data"]["is_accepting_orders"] is False


# ---------------------------------------------------------------------------
# Menu — categories
# ---------------------------------------------------------------------------


async def test_category_create_list_and_rename(client, vendor):
    category_id = await _make_category(client, vendor, "Starters")

    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["data"]] == ["Starters"]
    assert r.json()["data"][0]["item_count"] == 0

    r = await client.patch(
        f"{V1}/vendor/menu/categories/{category_id}",
        json={"name": "Appetisers", "sort_order": 3},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"] == "Appetisers"
    assert r.json()["data"]["sort_order"] == 3


async def test_duplicate_category_name_is_a_conflict(client, vendor):
    await _make_category(client, vendor, "Biryani")
    r = await client.post(
        f"{V1}/vendor/menu/categories", json={"name": "Biryani"}, headers=vendor.headers
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_two_vendors_may_use_the_same_category_name(client, vendor, other_vendor):
    """Uniqueness is per restaurant, not global."""
    await _make_category(client, vendor, "Biryani")
    await _make_category(client, other_vendor, "Biryani")


async def test_empty_category_deletes_populated_one_does_not(client, vendor):
    empty_id = await _make_category(client, vendor, "Empty")
    r = await client.delete(f"{V1}/vendor/menu/categories/{empty_id}", headers=vendor.headers)
    assert r.status_code == 200, r.text

    full_id = await _make_category(client, vendor, "Full")
    await _make_item(client, vendor, full_id)
    r = await client.delete(f"{V1}/vendor/menu/categories/{full_id}", headers=vendor.headers)
    assert r.status_code == 409, r.text
    # The cascade would have taken the item with it; the message must say so.
    assert "is_active" in r.json()["error"]["message"]


async def test_a_vendor_cannot_touch_another_vendors_category(client, vendor, other_vendor):
    category_id = await _make_category(client, vendor)

    r = await client.patch(
        f"{V1}/vendor/menu/categories/{category_id}",
        json={"name": "Hijacked"},
        headers=other_vendor.headers,
    )
    # 404, not 403 — a vendor must not be able to confirm the record exists.
    assert r.status_code == 404, r.text

    r = await client.delete(
        f"{V1}/vendor/menu/categories/{category_id}", headers=other_vendor.headers
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Menu — items
# ---------------------------------------------------------------------------


async def test_item_is_created_with_its_variants_and_add_ons(client, vendor):
    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)

    assert item["base_price"] == 180
    assert [v["name"] for v in item["variants"]] == ["Half", "Full"]
    assert [v["is_default"] for v in item["variants"]] == [True, False]
    assert item["add_ons"][0]["price"] == 30
    assert item["restaurant_id"] == str(vendor.restaurant.id)


async def test_first_variant_becomes_default_when_none_is_marked(client, vendor):
    category_id = await _make_category(client, vendor)
    item = await _make_item(
        client,
        vendor,
        category_id,
        variants=[{"name": "Half", "price": 180}, {"name": "Full", "price": 320}],
    )
    assert [v["is_default"] for v in item["variants"]] == [True, False]


async def test_two_defaults_are_rejected(client, vendor):
    category_id = await _make_category(client, vendor)
    r = await client.post(
        f"{V1}/vendor/menu/items",
        json={
            "name": "Biryani",
            "category_id": category_id,
            "base_price": 180,
            "variants": [
                {"name": "Half", "price": 180, "is_default": True},
                {"name": "Full", "price": 320, "is_default": True},
            ],
        },
        headers=vendor.headers,
    )
    assert r.status_code == 400, r.text


async def test_item_cannot_be_created_under_another_vendors_category(
    client, vendor, other_vendor
):
    """The composite FK makes this structurally impossible; the check makes it legible."""
    category_id = await _make_category(client, vendor)
    r = await client.post(
        f"{V1}/vendor/menu/items",
        json={"name": "Smuggled", "category_id": category_id, "base_price": 100},
        headers=other_vendor.headers,
    )
    assert r.status_code == 404, r.text


async def test_item_update_preserves_variant_ids_when_they_are_sent(client, vendor):
    """A price edit must not empty every cart holding the item."""
    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)
    half_id = next(v["id"] for v in item["variants"] if v["name"] == "Half")

    r = await client.patch(
        f"{V1}/vendor/menu/items/{item['id']}",
        json={
            "base_price": 200,
            "variants": [
                {"id": half_id, "name": "Half", "price": 200, "is_default": True},
                {"name": "Family", "price": 550},
            ],
        },
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["base_price"] == 200
    names = {v["name"]: v for v in data["variants"]}
    assert set(names) == {"Half", "Family"}
    # Edited in place, not recreated.
    assert names["Half"]["id"] == half_id
    assert names["Half"]["price"] == 200
    # Omitted from the replace-set, so it is gone.
    assert "Full" not in names


async def test_item_update_leaves_options_alone_when_omitted(client, vendor):
    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)

    r = await client.patch(
        f"{V1}/vendor/menu/items/{item['id']}",
        json={"name": "Mutton Biryani"},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["name"] == "Mutton Biryani"
    assert len(data["variants"]) == 2
    assert len(data["add_ons"]) == 1


async def test_item_can_move_between_categories(client, vendor):
    first = await _make_category(client, vendor, "Biryani")
    second = await _make_category(client, vendor, "Rice")
    item = await _make_item(client, vendor, first)

    r = await client.patch(
        f"{V1}/vendor/menu/items/{item['id']}",
        json={"category_id": second},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["category_id"] == second


async def test_sold_out_toggle(client, vendor):
    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)

    r = await client.patch(
        f"{V1}/vendor/menu/items/{item['id']}/status",
        json={"is_available": False},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_available"] is False


async def test_deleted_item_disappears_but_the_row_survives(client, vendor):
    """Soft delete — analytics and order history point at these rows."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.menu import MenuItem

    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)

    r = await client.delete(f"{V1}/vendor/menu/items/{item['id']}", headers=vendor.headers)
    assert r.status_code == 200, r.text

    r = await client.get(f"{V1}/vendor/menu/items/{item['id']}", headers=vendor.headers)
    assert r.status_code == 404, r.text

    async with SessionLocal() as session:
        row = await session.scalar(select(MenuItem).where(MenuItem.id == uuid.UUID(item["id"])))
        assert row is not None
        assert row.deleted_at is not None


async def test_menu_tree_includes_sold_out_items(client, vendor):
    """The owner's view is unfiltered — otherwise a sold-out item is unrecoverable."""
    category_id = await _make_category(client, vendor)
    item = await _make_item(client, vendor, category_id)
    await client.patch(
        f"{V1}/vendor/menu/items/{item['id']}/status",
        json={"is_available": False},
        headers=vendor.headers,
    )

    r = await client.get(f"{V1}/vendor/menu", headers=vendor.headers)
    assert r.status_code == 200, r.text
    categories = r.json()["data"]["categories"]
    assert len(categories) == 1
    assert categories[0]["item_count"] == 1
    assert categories[0]["items"][0]["is_available"] is False


async def test_reorder_applies_or_changes_nothing(client, vendor):
    first = await _make_category(client, vendor, "Biryani")
    second = await _make_category(client, vendor, "Drinks")

    r = await client.patch(
        f"{V1}/vendor/menu/reorder",
        json={"categories": [{"id": second, "sort_order": 0}, {"id": first, "sort_order": 1}]},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["categories_updated"] == 2

    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert [c["name"] for c in r.json()["data"]] == ["Drinks", "Biryani"]

    # One foreign id in the payload must abort the whole thing.
    r = await client.patch(
        f"{V1}/vendor/menu/reorder",
        json={
            "categories": [
                {"id": first, "sort_order": 9},
                {"id": str(uuid.uuid4()), "sort_order": 0},
            ]
        },
        headers=vendor.headers,
    )
    assert r.status_code == 404, r.text

    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert [c["name"] for c in r.json()["data"]] == ["Drinks", "Biryani"]


# ---------------------------------------------------------------------------
# Order queue
# ---------------------------------------------------------------------------


async def test_queue_is_empty_for_a_new_restaurant(client, vendor):
    r = await client.get(f"{V1}/vendor/orders", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []
    assert r.json()["meta"]["total"] == 0


async def test_queue_lists_orders_and_counts_lines(client, vendor, order_customer):
    await _seed_order(vendor.restaurant.id, order_customer.id, with_items=True)

    r = await client.get(f"{V1}/vendor/orders", headers=vendor.headers)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["item_count"] == 1
    assert rows[0]["item_total"] == 1000
    assert rows[0]["vendor_payout"] == 850
    # Counts down only while the order is still pending.
    assert 0 < rows[0]["seconds_to_auto_decline"] <= 60


async def test_queue_status_filter(client, vendor, order_customer):
    await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")
    await _seed_order(vendor.restaurant.id, order_customer.id, status="PREPARING")

    r = await client.get(f"{V1}/vendor/orders?status=PENDING", headers=vendor.headers)
    assert [o["status"] for o in r.json()["data"]] == ["PENDING"]

    r = await client.get(f"{V1}/vendor/orders?status=ACTIVE", headers=vendor.headers)
    assert len(r.json()["data"]) == 2

    r = await client.get(f"{V1}/vendor/orders?status=NONSENSE", headers=vendor.headers)
    assert r.status_code == 400, r.text


async def test_queue_never_shows_another_vendors_orders(
    client, vendor, other_vendor, order_customer
):
    order = await _seed_order(vendor.restaurant.id, order_customer.id)

    r = await client.get(f"{V1}/vendor/orders", headers=other_vendor.headers)
    assert r.json()["data"] == []

    r = await client.get(f"{V1}/vendor/orders/{order.id}", headers=other_vendor.headers)
    assert r.status_code == 404, r.text


async def test_order_detail_carries_what_the_kitchen_needs(client, vendor, order_customer):
    order = await _seed_order(vendor.restaurant.id, order_customer.id, with_items=True)

    r = await client.get(f"{V1}/vendor/orders/{order.id}", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["items"][0]["item_name"] == "Chicken Biryani"
    assert data["items"][0]["variant_name"] == "Full"
    assert data["items"][0]["notes"] == "Extra spicy"
    assert data["delivery_address_text"].startswith("House 4")
    assert data["special_instructions"] == "Ring the bell twice"
    assert data["customer_phone"] == "+8801712345678"
    assert data["rider_pin_issued"] is False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_accept_clears_the_auto_decline_timer(client, vendor, order_customer):
    order = await _seed_order(vendor.restaurant.id, order_customer.id)

    r = await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "PREPARING"
    assert data["accepted_at"] is not None
    # The sweeper's partial index no longer matches this row.
    assert data["auto_decline_at"] is None
    assert data["seconds_to_auto_decline"] is None


async def test_illegal_transitions_are_refused(client, vendor, order_customer):
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")

    # PENDING cannot jump straight to READY.
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    assert r.status_code == 409, r.text
    assert "PREPARING" in " ".join(r.json()["error"]["details"])

    await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    r = await client.post(f"{V1}/vendor/orders/{order.id}/accept", headers=vendor.headers)
    assert r.status_code == 409, r.text


async def test_reject_cancels_and_records_the_reason(client, vendor, order_customer):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    order = await _seed_order(vendor.restaurant.id, order_customer.id)

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/reject",
        json={"reason": "Out of chicken"},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "CANCELLED"

    async with SessionLocal() as session:
        row = await session.scalar(select(Order).where(Order.id == order.id))
        assert row.cancelled_by == "VENDOR"
        assert row.cancellation_reason == "Out of chicken"
        assert row.cancelled_at is not None


async def test_reject_is_refused_once_the_food_has_left(client, vendor, order_customer, rider):
    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="READY", rider_id=rider.id
    )
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/reject", json={"reason": "too late"}, headers=vendor.headers
    )
    assert r.status_code == 409, r.text


async def test_reject_marks_a_paid_order_refunded(client, vendor, order_customer):
    from sqlalchemy import select, update

    from app.core.database import SessionLocal
    from app.models.order import Order

    order = await _seed_order(vendor.restaurant.id, order_customer.id)
    async with SessionLocal() as session:
        await session.execute(
            update(Order).where(Order.id == order.id).values(payment_status="PAID")
        )
        await session.commit()

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/reject", json={"reason": "closed"}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    async with SessionLocal() as session:
        row = await session.scalar(select(Order).where(Order.id == order.id))
        assert row.payment_status == "REFUNDED"


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


async def test_ready_issues_a_handoff_code_the_vendor_can_reread(
    client, vendor, order_customer, rider
):
    """D3 amended: the handoff screen shows the code to the vendor, and the
    detail endpoint re-displays it while READY so an app restart cannot
    strand a pickup. Gone once picked up."""
    from app.core.config import settings

    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="PREPARING", rider_id=rider.id
    )
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["status"] == "READY"
    assert data["ready_at"] is not None
    assert len(data["handoff_code"]) == settings.RIDER_PIN_LENGTH

    # The detail re-displays the same code while READY.
    r = await client.get(f"{V1}/vendor/orders/{order.id}", headers=vendor.headers)
    detail = r.json()["data"]
    assert detail["rider_pin_issued"] is True
    assert detail["handoff_code"] == data["handoff_code"]

    # After handoff the code is gone from the detail.
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff",
        json={"rider_pin": data["handoff_code"]},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{V1}/vendor/orders/{order.id}", headers=vendor.headers)
    assert r.json()["data"]["handoff_code"] is None


async def test_handoff_succeeds_with_the_right_pin(client, vendor, order_customer, rider):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="PREPARING", rider_id=rider.id
    )
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    pin = r.json()["data"]["handoff_code"]

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": pin}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PICKED_UP"

    async with SessionLocal() as session:
        row = await session.scalar(select(Order).where(Order.id == order.id))
        assert row.picked_up_at is not None
        # Burned on success — a used PIN must not stay replayable.
        assert row.rider_pin_hash is None


async def test_wrong_pin_counts_down_then_locks(client, vendor, order_customer, rider):
    from app.core.config import settings

    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="PREPARING", rider_id=rider.id
    )
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    real_pin = r.json()["data"]["handoff_code"]
    wrong = "0000" if real_pin != "0000" else "1111"

    for attempt in range(settings.HANDOFF_MAX_ATTEMPTS):
        r = await client.post(
            f"{V1}/vendor/orders/{order.id}/handoff",
            json={"rider_pin": wrong},
            headers=vendor.headers,
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "INVALID_RIDER_PIN"
        remaining = settings.HANDOFF_MAX_ATTEMPTS - attempt - 1
        assert f"{remaining} attempt" in " ".join(r.json()["error"]["details"])

    # Budget spent: even the correct PIN is now refused.
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff",
        json={"rider_pin": real_pin},
        headers=vendor.headers,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "INVALID_RIDER_PIN"


async def test_handoff_without_an_assigned_rider_explains_itself(
    client, vendor, order_customer
):
    """ck_orders_rider_required would reject the write; this beats a 500."""
    order = await _seed_order(vendor.restaurant.id, order_customer.id, status="PREPARING")
    r = await client.post(f"{V1}/vendor/orders/{order.id}/ready", headers=vendor.headers)
    pin = r.json()["data"]["handoff_code"]

    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": pin}, headers=vendor.headers
    )
    assert r.status_code == 409, r.text
    assert "rider" in r.json()["error"]["message"].lower()


async def test_handoff_requires_a_four_digit_pin(client, vendor, order_customer, rider):
    order = await _seed_order(
        vendor.restaurant.id, order_customer.id, status="READY", rider_id=rider.id
    )
    r = await client.post(
        f"{V1}/vendor/orders/{order.id}/handoff", json={"rider_pin": "abcd"}, headers=vendor.headers
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def test_analytics_counts_delivered_orders_only(client, vendor, order_customer, rider):
    now = datetime.now(UTC)
    await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        rider_id=rider.id,
        delivered_at=now,
        item_total=100_000,
        commission=15_000,
        with_items=True,
    )
    # Neither of these is revenue.
    await _seed_order(vendor.restaurant.id, order_customer.id, status="PENDING")

    r = await client.get(f"{V1}/vendor/analytics", headers=vendor.headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["totals"]["orders"] == 1
    assert data["totals"]["gross_sales"] == 1000
    assert data["totals"]["commission"] == 150
    assert data["totals"]["net_payout"] == 850
    assert data["daily"][0]["date"] == now.date().isoformat()
    assert data["top_items"][0]["name"] == "Chicken Biryani"
    # Cancellations and in-flight orders stay visible here.
    assert data["status_breakdown"]["PENDING"] == 1
    assert data["status_breakdown"]["DELIVERED"] == 1


async def test_analytics_window_excludes_older_orders(client, vendor, order_customer, rider):
    old = datetime.now(UTC) - timedelta(days=120)
    await _seed_order(
        vendor.restaurant.id,
        order_customer.id,
        status="DELIVERED",
        rider_id=rider.id,
        delivered_at=old,
    )

    # Default window is the last 30 days.
    r = await client.get(f"{V1}/vendor/analytics", headers=vendor.headers)
    assert r.json()["data"]["totals"]["orders"] == 0

    r = await client.get(
        f"{V1}/vendor/analytics?date_from={old.date()}&date_to={old.date()}",
        headers=vendor.headers,
    )
    assert r.json()["data"]["totals"]["orders"] == 1


async def test_analytics_rejects_a_backwards_window(client, vendor):
    r = await client.get(
        f"{V1}/vendor/analytics?date_from=2026-08-10&date_to=2026-08-01", headers=vendor.headers
    )
    assert r.status_code == 400, r.text


async def test_reviews_are_empty_for_a_new_restaurant(client, vendor):
    r = await client.get(f"{V1}/vendor/reviews", headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


async def test_presigned_url_reports_missing_configuration_as_503(client, vendor):
    """No bucket in the test environment. Not a fault — an unprovisioned feature."""
    r = await client.post(
        f"{V1}/uploads/presigned-url", json={"file_type": "image/jpeg"}, headers=vendor.headers
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "STORAGE_NOT_CONFIGURED"


async def test_presigned_url_rejects_a_disallowed_type(client, vendor):
    r = await client.post(
        f"{V1}/uploads/presigned-url", json={"file_type": "text/html"}, headers=vendor.headers
    )
    # Rejected before configuration is even consulted — the type check is the
    # point, and a bucket that will host arbitrary HTML is the thing being
    # prevented.
    assert r.status_code == 400, r.text


def test_presigned_url_is_a_well_formed_sigv4_url(monkeypatch):
    """Signing is ours rather than boto3's, so it gets its own test."""
    from urllib.parse import parse_qs, urlparse

    from app.core.config import settings
    from app.services import storage_service

    monkeypatch.setattr(settings, "S3_BUCKET", "cr-shop-media")
    monkeypatch.setattr(settings, "S3_REGION", "ap-south-1")
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", None)
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "s" * 40)

    result = storage_service.create_presigned_put(str(uuid.uuid4()), "image/jpeg")
    parsed = urlparse(result.upload_url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "cr-shop-media.s3.ap-south-1.amazonaws.com"
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-SignedHeaders"] == ["content-type;host"]
    assert query["X-Amz-Expires"] == [str(settings.PRESIGNED_URL_TTL_SECONDS)]
    assert len(query["X-Amz-Signature"][0]) == 64
    # The content type is signed, so an upload cannot substitute another one.
    assert result.headers == {"Content-Type": "image/jpeg"}
    assert result.public_url.endswith(".jpg")
    assert result.key.endswith(".jpg")
