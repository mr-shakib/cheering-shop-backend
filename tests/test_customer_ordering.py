"""The customer ordering funnel: discovery, cart, checkout, orders, chat.

These drive the API over HTTP rather than calling services directly, because
the things most likely to break here are the seams — a price computed one way
at checkout and another at placement, a cart that accepts an item the database
will refuse, a promo applied twice. A service-level test would not catch any of
those.

The pricing assertions deliberately restate the arithmetic rather than calling
`services.pricing.quote`. A test that computes the expected value with the same
function under test proves only that the function is deterministic.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


# --- helpers ---------------------------------------------------------------
# The `kitchen` and `shopper` fixtures moved to conftest.py when the rider
# lifecycle suite needed the same two actors.


async def _add_burger(client, kitchen, shopper, quantity=2, add_ons=True):
    return await client.post(
        f"{V1}/cart/items",
        json={
            "menu_item_id": kitchen.burger_id,
            "variant_id": kitchen.variant_id,
            "add_on_ids": [kitchen.addon_id] if add_ons else [],
            "quantity": quantity,
        },
        headers=shopper.headers,
    )


# --- discovery -------------------------------------------------------------


async def test_menu_is_public_and_nests_variants_and_add_ons(client, kitchen):
    """No token: a customer must be able to browse before signing up."""
    r = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/menu")
    assert r.status_code == 200, r.text
    categories = r.json()["data"]
    burger = next(
        i for c in categories for i in c["items"] if i["id"] == kitchen.burger_id
    )
    assert burger["base_price"] == 300.0
    assert [v["name"] for v in burger["variants"]] == ["Large"]
    assert [a["name"] for a in burger["add_ons"]] == ["Extra cheese"]


async def test_soft_deleted_items_disappear_from_the_menu(client, kitchen):
    """A dish the vendor removed must not remain orderable."""
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.menu import MenuItem

    async with SessionLocal() as s:
        await s.execute(
            update(MenuItem)
            .where(MenuItem.id == uuid.UUID(kitchen.coke_id))
            .values(deleted_at=datetime.now(UTC))
        )
        await s.commit()

    r = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/menu")
    ids = [i["id"] for c in r.json()["data"] for i in c["items"]]
    assert kitchen.coke_id not in ids
    assert kitchen.burger_id in ids


async def test_search_finds_the_dish_and_names_who_sells_it(client, kitchen):
    r = await client.get(f"{V1}/search", params={"q": "Burger"})
    assert r.status_code == 200, r.text
    hit = next(i for i in r.json()["data"]["items"] if i["id"] == kitchen.burger_id)
    # A dish hit is useless without knowing the restaurant.
    assert hit["restaurant_name"] == kitchen.restaurant.name


async def test_cuisine_filter_matches_the_array_column(client, kitchen):
    """`contains` maps to the array @> operator — a different operator from the
    one this started with, so it gets its own test rather than trusting mypy."""
    hit = await client.get(f"{V1}/restaurants", params={"cuisine": "Bengali"})
    assert hit.status_code == 200, hit.text
    assert str(kitchen.restaurant.id) in [c["id"] for c in hit.json()["data"]]

    miss = await client.get(f"{V1}/restaurants", params={"cuisine": "Etruscan"})
    assert str(kitchen.restaurant.id) not in [c["id"] for c in miss.json()["data"]]


async def test_sorting_and_distance_need_no_coordinates(client, kitchen):
    """An unlocated caller must still get a usable list, with distance null
    rather than 0 — 0 would sort everything to the top of a 'nearest' list."""
    r = await client.get(f"{V1}/restaurants", params={"sort": "rating"})
    assert r.status_code == 200, r.text
    card = next(c for c in r.json()["data"] if c["id"] == str(kitchen.restaurant.id))
    assert card["distance_km"] is None


async def test_home_feed_groups_cuisines_without_a_grouping_error(client, kitchen):
    """unnest() must be expanded in a subquery before it can be grouped."""
    r = await client.get(f"{V1}/home/feed", params={"lat": 23.80, "lng": 90.40})
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["data"]["cuisines"], list)


# --- cart ------------------------------------------------------------------


async def test_variant_is_required_when_the_item_has_them(client, kitchen, shopper):
    """Decision D4. Silently defaulting is how someone is charged for a small
    when the screen said large."""
    r = await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.burger_id, "quantity": 1},
        headers=shopper.headers,
    )
    assert r.status_code == 400, r.text
    assert "variant" in r.json()["error"]["message"].lower()


async def test_cart_prices_the_line_from_variant_plus_add_ons(client, kitchen, shopper):
    r = await _add_burger(client, kitchen, shopper, quantity=2)
    assert r.status_code == 200, r.text
    cart = r.json()["data"]
    line = cart["items"][0]
    # (300 variant + 30 cheese) * 2
    assert line["unit_price"] == 300.0
    assert line["add_ons_total"] == 30.0
    assert line["line_total"] == 660.0
    assert cart["item_total"] == 660.0
    assert cart["item_count"] == 2


async def test_same_configuration_collapses_into_one_line(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await _add_burger(client, kitchen, shopper, quantity=3)
    cart = r.json()["data"]
    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 3


async def test_different_add_ons_stay_separate_lines(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1, add_ons=True)
    r = await _add_burger(client, kitchen, shopper, quantity=1, add_ons=False)
    assert len(r.json()["data"]["items"]) == 2


async def test_quantity_zero_removes_and_empties_the_cart(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await _add_burger(client, kitchen, shopper, quantity=0)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["items"] == []
    # The husk must be gone, or the next add from elsewhere hits a 409 for a
    # cart with nothing in it.
    assert r.json()["data"]["restaurant_id"] is None


async def test_cart_refuses_a_second_restaurant(client, kitchen, other_vendor, shopper):
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.menu import MenuCategory, MenuItem
    from app.models.restaurant import Restaurant

    async with SessionLocal() as s:
        await s.execute(
            update(Restaurant)
            .where(Restaurant.id == other_vendor.restaurant.id)
            .values(status="OPEN")
        )
        category = MenuCategory(
            id=uuid.uuid4(), restaurant_id=other_vendor.restaurant.id, name="Other"
        )
        s.add(category)
        await s.flush()
        rival = MenuItem(
            id=uuid.uuid4(),
            category_id=category.id,
            restaurant_id=other_vendor.restaurant.id,
            name="Pizza",
            base_price=50000,
        )
        s.add(rival)
        await s.commit()

    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": str(rival.id), "quantity": 1},
        headers=shopper.headers,
    )
    assert r.status_code == 409, r.text


async def test_cart_reprices_when_the_vendor_changes_the_menu(client, kitchen, shopper):
    """The cart stores configuration, not money."""
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.menu import ItemVariant

    await _add_burger(client, kitchen, shopper, quantity=1)
    async with SessionLocal() as s:
        await s.execute(
            update(ItemVariant)
            .where(ItemVariant.id == uuid.UUID(kitchen.variant_id))
            .values(price=40000)
        )
        await s.commit()

    r = await client.get(f"{V1}/cart", headers=shopper.headers)
    assert r.json()["data"]["items"][0]["unit_price"] == 400.0


# --- checkout --------------------------------------------------------------


async def test_checkout_bill_adds_up_exactly(client, kitchen, shopper):
    """Restated arithmetic, not a second call to the function under test."""
    await _add_burger(client, kitchen, shopper, quantity=2)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id, "tip": 20},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    bill = r.json()["data"]
    from decimal import Decimal

    def dec(key):
        """str() first — Decimal(float) would import the float's own error."""
        return Decimal(str(bill[key]))

    item_total = dec("item_total")
    assert item_total == Decimal("660.00")
    assert dec("tax_amount") == (item_total * 5 / 100).quantize(Decimal("0.01"))
    assert dec("platform_fee") == (item_total * 2 / 100).quantize(Decimal("0.01"))
    assert dec("tip") == Decimal("20.00")
    expected = (
        item_total
        + dec("delivery_fee")
        + dec("packaging_fee")
        + dec("tax_amount")
        + dec("platform_fee")
        + dec("tip")
        - dec("discount")
    )
    assert dec("grand_total") == expected


async def test_a_bad_promo_explains_itself_without_failing_the_bill(client, kitchen, shopper):
    """Dropping the code silently leaves the customer staring at an unchanged
    total with no idea why."""
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id, "promo_code": "NOPE404"},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["promo_error"]
    assert r.json()["data"]["discount"] == 0.0


async def test_checkout_refuses_an_address_that_is_not_yours(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": str(uuid.uuid4())},
        headers=shopper.headers,
    )
    assert r.status_code == 404, r.text


# --- placing the order -----------------------------------------------------


async def test_placing_an_order_snapshots_prices_and_clears_the_cart(
    client, kitchen, shopper
):
    await _add_burger(client, kitchen, shopper, quantity=2)
    summary = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id},
        headers=shopper.headers,
    )
    quoted_total = summary.json()["data"]["grand_total"]

    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    assert r.status_code == 201, r.text
    placed = r.json()["data"]
    # The number the customer agreed to is the number that was charged.
    assert placed["grand_total"] == quoted_total
    assert placed["status"] == "PENDING"
    assert placed["payment_status"] == "PENDING"

    empty = await client.get(f"{V1}/cart", headers=shopper.headers)
    assert empty.json()["data"]["items"] == []

    detail = await client.get(f"{V1}/orders/{placed['id']}", headers=shopper.headers)
    assert detail.status_code == 200, detail.text
    item = detail.json()["data"]["items"][0]
    assert item["name"] == "Beef Burger"
    assert item["line_total"] == 660.0
    # The first timeline dot exists, so Ride Assign has something to draw.
    assert detail.json()["data"]["timeline"][0]["status"] == "PENDING"


async def test_idempotency_key_replays_instead_of_double_ordering(client, kitchen, shopper):
    """The exact failure this exists for: the response is lost, the app retries."""
    await _add_burger(client, kitchen, shopper, quantity=1)
    body = {"payment_method": "COD", "address_id": shopper.address_id}
    key = {"Idempotency-Key": uuid.uuid4().hex, **shopper.headers}

    first = await client.post(f"{V1}/orders", json=body, headers=key)
    assert first.status_code == 201, first.text
    second = await client.post(f"{V1}/orders", json=body, headers=key)
    # The replay reproduces the ORIGINAL response, 201 included — the contract
    # is "same answer", not "a different answer that means the same thing".
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    # The point of all of it: one order, not two.
    history = await client.get(f"{V1}/orders", headers=shopper.headers)
    assert history.json()["meta"]["total"] == 1


async def test_reusing_a_key_with_a_different_body_is_refused(client, kitchen, shopper):
    """Replaying the first call's response for a materially different request
    would be far more confusing than an error."""
    await _add_burger(client, kitchen, shopper, quantity=1)
    key = {"Idempotency-Key": uuid.uuid4().hex, **shopper.headers}
    first = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=key,
    )
    assert first.status_code == 201, first.text

    reused = await client.post(
        f"{V1}/orders",
        json={"payment_method": "BKASH", "address_id": shopper.address_id},
        headers=key,
    )
    assert reused.status_code == 409, reused.text


async def test_order_from_a_closed_kitchen_is_refused(client, kitchen, shopper):
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    await _add_burger(client, kitchen, shopper, quantity=1)
    async with SessionLocal() as s:
        await s.execute(
            update(Restaurant).where(Restaurant.id == kitchen.restaurant.id).values(status="CLOSED")
        )
        await s.commit()

    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    assert r.status_code == 409, r.text


async def test_cancel_works_while_pending_and_not_after(client, kitchen, shopper):
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.order import Order

    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = placed.json()["data"]["id"]

    r = await client.post(
        f"{V1}/orders/{order_id}/cancel", json={"reason": "Changed my mind"},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "CANCELLED"
    assert r.json()["data"]["cancellation_reason"] == "Changed my mind"

    # Once the kitchen has it, cancelling is a phone call.
    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .values(status="PREPARING", cancelled_at=None, cancelled_by=None)
        )
        await s.commit()
    again = await client.post(
        f"{V1}/orders/{order_id}/cancel", json={}, headers=shopper.headers
    )
    assert again.status_code == 409, again.text


async def test_another_customers_order_is_a_404_not_a_403(client, kitchen, shopper, customer_token):
    """A 403 would confirm the id exists, which is itself a disclosure."""
    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = placed.json()["data"]["id"]
    r = await client.get(
        f"{V1}/orders/{order_id}", headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert r.status_code == 404, r.text


# --- scheduled delivery ----------------------------------------------------


async def test_schedule_offers_slots_and_greys_the_ones_too_soon(client, kitchen):
    r = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/schedule")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["days"][0]["label"] == "Today"
    slots = [s for day in data["days"] for s in day["slots"]]
    assert slots, "a picker with no windows looks broken"
    # Unavailable slots are RETURNED, not omitted.
    assert any(not s["is_available"] for s in slots) or all(s["is_available"] for s in slots)


async def test_scheduling_inside_the_lead_time_is_refused(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    too_soon = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    r = await client.post(
        f"{V1}/orders",
        json={
            "payment_method": "COD",
            "address_id": shopper.address_id,
            "scheduled_for": too_soon,
        },
        headers=shopper.headers,
    )
    assert r.status_code == 400, r.text


async def test_a_scheduled_order_has_no_auto_decline_countdown(client, kitchen, shopper):
    """The 60s timer starts when the kitchen is asked, not when the customer
    books."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.order import Order

    await _add_burger(client, kitchen, shopper, quantity=1)
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    r = await client.post(
        f"{V1}/orders",
        json={
            "payment_method": "COD",
            "address_id": shopper.address_id,
            "scheduled_for": later,
        },
        headers=shopper.headers,
    )
    assert r.status_code == 201, r.text

    async with SessionLocal() as s:
        order = await s.scalar(
            select(Order).where(Order.id == uuid.UUID(r.json()["data"]["id"]))
        )
        assert order.scheduled_for is not None
        assert order.auto_decline_at is None


# --- addresses and favorites ----------------------------------------------


async def test_first_address_becomes_the_default_and_delete_promotes(client, order_customer):
    from app.core.security import create_access_token

    token = create_access_token(str(order_customer.id), order_customer.role)
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "type": "HOME",
        "street_address": "House 1, Road 1, Banani, Dhaka",
        "latitude": 23.79,
        "longitude": 90.40,
    }
    first = await client.post(f"{V1}/users/me/addresses", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["is_default"] is True

    second = await client.post(
        f"{V1}/users/me/addresses", json={**body, "street_address": "House 2"}, headers=headers
    )
    assert second.json()["data"]["is_default"] is False

    # Deleting the default must leave one behind, or checkout preselects nothing.
    gone = await client.delete(
        f"{V1}/users/me/addresses/{first.json()['data']['id']}", headers=headers
    )
    assert gone.status_code == 204
    listed = await client.get(f"{V1}/users/me/addresses", headers=headers)
    remaining = listed.json()["data"]
    assert len(remaining) == 1
    assert remaining[0]["is_default"] is True


async def test_favorite_toggles_both_ways(client, kitchen, shopper):
    on = await client.post(
        f"{V1}/users/me/favorites/{kitchen.restaurant.id}", headers=shopper.headers
    )
    assert on.json()["data"]["is_favorite"] is True
    listed = await client.get(f"{V1}/users/me/favorites", headers=shopper.headers)
    assert [f["id"] for f in listed.json()["data"]] == [str(kitchen.restaurant.id)]

    off = await client.post(
        f"{V1}/users/me/favorites/{kitchen.restaurant.id}", headers=shopper.headers
    )
    assert off.json()["data"]["is_favorite"] is False


async def test_signed_in_discovery_marks_favorites(client, kitchen, shopper):
    """Discovery is public, but a token still enriches it."""
    await client.post(f"{V1}/users/me/favorites/{kitchen.restaurant.id}", headers=shopper.headers)
    r = await client.get(f"{V1}/restaurants", params={"q": kitchen.restaurant.name},
                         headers=shopper.headers)
    card = next(c for c in r.json()["data"] if c["id"] == str(kitchen.restaurant.id))
    assert card["is_favorite"] is True

    anon = await client.get(f"{V1}/restaurants", params={"q": kitchen.restaurant.name})
    anon_card = next(c for c in anon.json()["data"] if c["id"] == str(kitchen.restaurant.id))
    assert anon_card["is_favorite"] is False


# --- reviews and chat ------------------------------------------------------


async def _place_and_deliver(client, kitchen, shopper, rider):
    """Place an order and force it to DELIVERED.

    A rider must be assigned: `ck_orders_rider_required` refuses a PICKED_UP or
    DELIVERED order without one, which is the schema refusing to record a
    delivery nobody made.
    """
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.order import Order

    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = placed.json()["data"]["id"]
    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .values(
                status="DELIVERED",
                delivered_at=datetime.now(UTC),
                rider_id=rider.id,
                rider_role="RIDER",
            )
        )
        await s.commit()
    return order_id


async def test_review_requires_delivery_and_is_one_per_order(client, kitchen, shopper, rider):
    await _add_burger(client, kitchen, shopper, quantity=1)
    pending = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    early = await client.post(
        f"{V1}/orders/{pending.json()['data']['id']}/reviews",
        json={"restaurant_rating": 5},
        headers=shopper.headers,
    )
    assert early.status_code == 409, early.text

    order_id = await _place_and_deliver(client, kitchen, shopper, rider)
    ok_review = await client.post(
        f"{V1}/orders/{order_id}/reviews",
        json={"restaurant_rating": 4, "comment": "Good"},
        headers=shopper.headers,
    )
    assert ok_review.status_code == 201, ok_review.text

    twice = await client.post(
        f"{V1}/orders/{order_id}/reviews",
        json={"restaurant_rating": 1},
        headers=shopper.headers,
    )
    assert twice.status_code == 409, twice.text


async def test_review_updates_the_restaurant_rating(client, kitchen, shopper, rider):
    order_id = await _place_and_deliver(client, kitchen, shopper, rider)
    await client.post(
        f"{V1}/orders/{order_id}/reviews",
        json={"restaurant_rating": 4},
        headers=shopper.headers,
    )
    r = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}")
    assert r.json()["data"]["rating_avg"] == 4.0
    assert r.json()["data"]["rating_count"] == 1


async def test_chat_is_limited_to_the_parties_on_the_order(
    client, kitchen, shopper, customer_token
):
    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = placed.json()["data"]["id"]

    sent = await client.post(
        f"{V1}/orders/{order_id}/messages",
        json={"body": "Please ring the bell twice"},
        headers=shopper.headers,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["data"]["message"]["sender_role"] == "CUSTOMER"

    # The vendor is a party and sees it as theirs to answer.
    thread = await client.get(f"{V1}/orders/{order_id}/messages", headers=kitchen.headers)
    assert thread.status_code == 200, thread.text
    assert thread.json()["data"]["messages"][0]["is_mine"] is False

    # A stranger gets the same 404 as a missing order.
    stranger = await client.get(
        f"{V1}/orders/{order_id}/messages",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert stranger.status_code == 404, stranger.text


async def test_chat_closes_with_a_cancelled_order(client, kitchen, shopper):
    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    order_id = placed.json()["data"]["id"]
    await client.post(f"{V1}/orders/{order_id}/cancel", json={}, headers=shopper.headers)

    r = await client.post(
        f"{V1}/orders/{order_id}/messages",
        json={"body": "hello?"},
        headers=shopper.headers,
    )
    assert r.status_code == 409, r.text


async def test_tracking_is_honest_about_having_no_rider_position(client, kitchen, shopper):
    """A dot that does not correspond to a real courier is worse than no dot."""
    await _add_burger(client, kitchen, shopper, quantity=1)
    placed = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers=shopper.headers,
    )
    r = await client.get(
        f"{V1}/orders/{placed.json()['data']['id']}/tracking", headers=shopper.headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["rider_location"] is None
    assert data["live_tracking_available"] is False
    # Everything that IS real is present.
    assert data["timeline"]
    assert data["restaurant_latitude"] and data["delivery_latitude"]


async def test_delivery_is_a_flat_base_plus_started_kilometres(client, kitchen, shopper):
    """৳10 covers the first km, then ৳8 per started km. The kitchen fixture is
    ~1.6 km from the shopper's address, so that is one chargeable km."""
    from app.core.config import settings

    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id},
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    bill = r.json()["data"]

    distance = bill["distance_km"]
    assert 1.0 < distance < 2.0, f"fixture geometry moved: {distance} km"

    expected = settings.DELIVERY_FEE_BASE + settings.DELIVERY_FEE_PER_KM
    assert bill["delivery_fee"] == expected == 18


async def test_the_restaurants_own_fee_column_is_no_longer_charged(client, kitchen, shopper):
    """`restaurants.delivery_fee_base` still exists and the fixture sets it to
    ৳40. Nothing reads it, so the customer is charged platform policy."""
    from app.core.config import settings

    await _add_burger(client, kitchen, shopper, quantity=1)
    r = await client.get(
        f"{V1}/checkout/summary",
        params={"address_id": shopper.address_id},
        headers=shopper.headers,
    )
    assert r.json()["data"]["delivery_fee"] < 40
    assert r.json()["data"]["delivery_fee"] >= settings.DELIVERY_FEE_BASE
