"""Add-on quantities, several lines of one item, and cart line controls.

The `kitchen` fixture: Beef Burger (Large variant ৳300, Extra cheese add-on
৳30) and Coke (৳60).
"""

import uuid

import pytest

V1 = "/api/v1"

pytestmark = pytest.mark.usefixtures("db_available")


def _burger(kitchen, *, quantity=1, add_ons=None, add_on_ids=None, mode="set"):
    body = {
        "menu_item_id": kitchen.burger_id,
        "variant_id": kitchen.variant_id,
        "quantity": quantity,
        "mode": mode,
    }
    if add_ons is not None:
        body["add_ons"] = add_ons
    if add_on_ids is not None:
        body["add_on_ids"] = add_on_ids
    return body


async def _allow_cheese(client, kitchen, up_to=3):
    r = await client.patch(
        f"{V1}/vendor/menu/items/{kitchen.burger_id}/add-ons/{kitchen.addon_id}",
        json={"max_quantity": up_to},
        headers=kitchen.headers,
    )
    assert r.status_code == 200, r.text
    cheese = next(a for a in r.json()["data"]["add_ons"] if a["id"] == kitchen.addon_id)
    assert cheese["max_quantity"] == up_to


async def test_an_add_on_can_be_ordered_more_than_once(client, kitchen, shopper):
    # By default an add-on is on/off: asking for two is refused, not a 500.
    r = await client.post(
        f"{V1}/cart/items",
        json=_burger(kitchen, add_on_ids=[kitchen.addon_id, kitchen.addon_id]),
        headers=shopper.headers,
    )
    assert r.status_code == 400, r.text

    await _allow_cheese(client, kitchen)
    menu = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/menu")
    burger = next(
        i for c in menu.json()["data"] for i in c["items"] if i["id"] == kitchen.burger_id
    )
    assert burger["add_ons"][0]["max_quantity"] == 3

    r = await client.post(
        f"{V1}/cart/items",
        json=_burger(kitchen, quantity=2, add_ons=[{"add_on_id": kitchen.addon_id, "quantity": 2}]),
        headers=shopper.headers,
    )
    assert r.status_code == 200, r.text
    [line] = r.json()["data"]["items"]
    assert line["add_ons"] == [
        {"id": kitchen.addon_id, "name": "Extra cheese", "unit_price": 30.0, "quantity": 2}
    ]
    assert line["add_on_names"] == ["Extra cheese ×2"]
    assert line["add_ons_total"] == 60.0  # per burger
    assert line["line_total"] == 720.0  # (300 + 2 × 30) × 2

    r = await client.post(
        f"{V1}/cart/items",
        json=_burger(kitchen, add_ons=[{"add_on_id": kitchen.addon_id, "quantity": 4}]),
        headers=shopper.headers,
    )
    assert r.status_code == 400
    assert "at most 3" in " ".join(r.json()["error"]["details"])


async def test_one_item_with_different_add_ons_makes_separate_lines(client, kitchen, shopper):
    await _allow_cheese(client, kitchen)
    plain = _burger(kitchen)
    one_cheese = _burger(kitchen, add_on_ids=[kitchen.addon_id])
    two_cheese = _burger(kitchen, add_ons=[{"add_on_id": kitchen.addon_id, "quantity": 2}])
    for body in (plain, one_cheese, two_cheese):
        r = await client.post(f"{V1}/cart/items", json=body, headers=shopper.headers)
        assert r.status_code == 200, r.text
    cart = r.json()["data"]
    assert len(cart["items"]) == 3
    assert cart["item_count"] == 3

    # The two ways of asking for one cheese are the same line.
    same = _burger(kitchen, add_ons=[{"add_on_id": kitchen.addon_id, "quantity": 1}], mode="add")
    r = await client.post(f"{V1}/cart/items", json=same, headers=shopper.headers)
    assert len(r.json()["data"]["items"]) == 3
    one = next(i for i in r.json()["data"]["items"] if i["add_on_names"] == ["Extra cheese"])
    assert one["quantity"] == 2


async def test_add_mode_adds_and_set_mode_replaces(client, kitchen, shopper):
    coke = {"menu_item_id": kitchen.coke_id, "quantity": 2, "mode": "add"}
    await client.post(f"{V1}/cart/items", json=coke, headers=shopper.headers)
    r = await client.post(f"{V1}/cart/items", json=coke, headers=shopper.headers)
    assert r.json()["data"]["items"][0]["quantity"] == 4

    r = await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 1},
        headers=shopper.headers,
    )
    assert r.json()["data"]["items"][0]["quantity"] == 1

    r = await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 0, "mode": "add"},
        headers=shopper.headers,
    )
    assert r.status_code == 400


async def test_cart_lines_are_changed_and_removed_by_id(client, kitchen, shopper, customer_user):
    await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 1},
        headers=shopper.headers,
    )
    r = await client.post(
        f"{V1}/cart/items",
        json=_burger(kitchen, add_on_ids=[kitchen.addon_id]),
        headers=shopper.headers,
    )
    lines = {i["name"]: i["id"] for i in r.json()["data"]["items"]}

    r = await client.patch(
        f"{V1}/cart/items/{lines['Beef Burger']}", json={"quantity": 3}, headers=shopper.headers
    )
    assert r.status_code == 200, r.text
    burger = next(i for i in r.json()["data"]["items"] if i["name"] == "Beef Burger")
    assert burger["quantity"] == 3
    assert burger["add_on_names"] == ["Extra cheese"]  # configuration untouched

    # Someone else's cart cannot be touched through a line id.
    from app.core.security import create_access_token

    other = {"Authorization": f"Bearer {create_access_token(str(customer_user.id), 'CUSTOMER')}"}
    r = await client.patch(f"{V1}/cart/items/{lines['Coke']}", json={"quantity": 5}, headers=other)
    assert r.status_code == 404

    r = await client.delete(f"{V1}/cart/items/{lines['Coke']}", headers=shopper.headers)
    assert [i["name"] for i in r.json()["data"]["items"]] == ["Beef Burger"]
    r = await client.patch(
        f"{V1}/cart/items/{lines['Beef Burger']}", json={"quantity": 0}, headers=shopper.headers
    )
    assert r.json()["data"]["items"] == []
    r = await client.delete(f"{V1}/cart/items/{uuid.uuid4()}", headers=shopper.headers)
    assert r.status_code == 404


async def test_orders_keep_add_on_prices_and_quantities(client, kitchen, shopper):
    await _allow_cheese(client, kitchen)
    await client.post(
        f"{V1}/cart/items",
        json=_burger(kitchen, quantity=2, add_ons=[{"add_on_id": kitchen.addon_id, "quantity": 2}]),
        headers=shopper.headers,
    )
    await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 3},
        headers=shopper.headers,
    )
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers={"Idempotency-Key": uuid.uuid4().hex, **shopper.headers},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["data"]["id"]

    r = await client.get(f"{V1}/orders/{order_id}", headers=shopper.headers)
    detail = r.json()["data"]
    assert detail["item_total"] == 900.0  # (300 + 60) × 2 + 60 × 3
    burger = next(i for i in detail["items"] if i["name"] == "Beef Burger")
    assert burger["add_ons"] == [{"name": "Extra cheese", "unit_price": 30.0, "quantity": 2}]
    assert burger["add_on_names"] == ["Extra cheese ×2"]

    # The kitchen sees how many to cook, at the price charged.
    r = await client.get(f"{V1}/vendor/orders/{order_id}", headers=kitchen.headers)
    line = next(i for i in r.json()["data"]["items"] if i["item_name"] == "Beef Burger")
    assert line["add_ons"] == [{"name": "Extra cheese", "price": 30.0, "quantity": 2}]

    # A later price change does not rewrite the receipt.
    await client.patch(
        f"{V1}/vendor/menu/items/{kitchen.burger_id}/add-ons/{kitchen.addon_id}",
        json={"price": 99},
        headers=kitchen.headers,
    )
    r = await client.get(f"{V1}/orders/{order_id}", headers=shopper.headers)
    burger = next(i for i in r.json()["data"]["items"] if i["name"] == "Beef Burger")
    assert burger["add_ons"][0]["unit_price"] == 30.0
