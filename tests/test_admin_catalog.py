"""Admin catalog: products, commission at every level, categories, Mark Unpaid.

The `kitchen` fixture's menu: a Burger (Large variant ৳300, cheese add-on ৳30)
and a Coke (৳60), both in a "Mains" section with no browse category, at a
restaurant charging 15%.
"""

import uuid

import pytest

V1 = "/api/v1"

pytestmark = pytest.mark.usefixtures("db_available")


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def categories():
    """Browse categories a test creates, removed afterwards. Sections link with
    ON DELETE SET NULL, so this is safe whichever fixture unwinds first."""
    made: list[str] = []
    yield made

    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.category import Category

    async with SessionLocal() as s:
        await s.execute(delete(Category).where(Category.id.in_([uuid.UUID(i) for i in made])))
        await s.commit()


async def _category(client, admin, categories, **body) -> dict:
    body.setdefault("name", f"Test {uuid.uuid4().hex[:8]}")
    r = await client.post(f"{V1}/admin/categories", json=body, headers=admin)
    assert r.status_code == 201, r.text
    categories.append(r.json()["data"]["id"])
    return r.json()["data"]


async def _place_order(client, kitchen, shopper, *, cokes: int = 2) -> str:
    for body in (
        {
            "menu_item_id": kitchen.burger_id,
            "variant_id": kitchen.variant_id,
            "add_on_ids": [kitchen.addon_id],
            "quantity": 1,
        },
        {"menu_item_id": kitchen.coke_id, "quantity": cokes},
    ):
        r = await client.post(f"{V1}/cart/items", json=body, headers=shopper.headers)
        assert r.status_code == 200, r.text
    r = await client.post(
        f"{V1}/orders",
        json={"payment_method": "COD", "address_id": shopper.address_id},
        headers={"Idempotency-Key": uuid.uuid4().hex, **shopper.headers},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


async def test_product_list_and_drawer(client, admin, kitchen):
    r = await client.get(
        f"{V1}/admin/products?restaurant_id={kitchen.restaurant.id}", headers=admin
    )
    assert r.status_code == 200, r.text
    assert {p["name"] for p in r.json()["data"]} == {"Beef Burger", "Coke"}

    r = await client.get(f"{V1}/admin/products/{kitchen.burger_id}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["section_name"] == "Mains"
    assert d["status"] == "ACTIVE"
    assert d["commission"] == {
        "rate": 0.15,
        "source": "RESTAURANT",
        "product_rate": None,
        "category_rate": None,
        "restaurant_rate": 0.15,
    }
    assert d["commission_amount"] == 45.0
    assert d["net_amount"] == 255.0
    assert [v["name"] for v in d["variants"]] == ["Large"]

    r = await client.get(f"{V1}/admin/products/{uuid.uuid4()}", headers=admin)
    assert r.status_code == 404


async def test_vendors_cannot_reach_the_product_console(client, kitchen):
    r = await client.get(f"{V1}/admin/products", headers=kitchen.headers)
    assert r.status_code == 403


async def test_commission_is_charged_at_the_most_specific_level(
    client, admin, kitchen, shopper, categories
):
    """Burger ৳330 a line, Coke ৳60 each. Every level stays settable."""
    # Restaurant only: 15% of 330 + 15% of 120.
    first = await _place_order(client, kitchen, shopper)
    r = await client.get(f"{V1}/admin/orders/{first}", headers=admin)
    assert r.json()["data"]["money"]["commission_amount"] == 67.5

    # Coke gets its own 5%; the burger moves under a 10% browse category.
    r = await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}", json={"commission_rate": 0.05}, headers=admin
    )
    assert r.json()["data"]["commission"]["source"] == "PRODUCT"
    snacks = await _category(client, admin, categories, commission_rate=0.10)
    r = await client.patch(
        f"{V1}/admin/products/{kitchen.burger_id}",
        json={"platform_category_id": snacks["id"]},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    burger = r.json()["data"]
    assert burger["platform_category"]["id"] == snacks["id"]
    assert burger["section_name"] == snacks["name"]  # a section was made for it
    assert burger["commission"]["source"] == "CATEGORY"

    second = await _place_order(client, kitchen, shopper)
    r = await client.get(f"{V1}/admin/orders/{second}", headers=admin)
    assert r.json()["data"]["money"]["commission_amount"] == 39.0  # 33 + 6

    # The first order kept its snapshot.
    r = await client.get(f"{V1}/admin/orders/{first}", headers=admin)
    assert r.json()["data"]["money"]["commission_amount"] == 67.5

    # Clearing the product rate hands the coke back to the restaurant's.
    r = await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}", json={"commission_rate": None}, headers=admin
    )
    assert r.json()["data"]["commission"]["source"] == "RESTAURANT"


async def test_a_hidden_product_is_gone_for_customers_only(client, admin, kitchen, shopper):
    r = await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}", json={"is_hidden": True}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "HIDDEN"

    menu = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/menu")
    names = {i["name"] for c in menu.json()["data"] for i in c["items"]}
    assert "Coke" not in names and "Beef Burger" in names

    r = await client.post(
        f"{V1}/cart/items",
        json={"menu_item_id": kitchen.coke_id, "quantity": 1},
        headers=shopper.headers,
    )
    assert r.status_code == 404

    # The vendor still sees it, flagged, and cannot flip the flag back.
    vendor_menu = await client.get(f"{V1}/vendor/menu", headers=kitchen.headers)
    coke = next(
        i
        for c in vendor_menu.json()["data"]["categories"]
        for i in c["items"]
        if i["name"] == "Coke"
    )
    assert coke["is_hidden"] is True
    r = await client.patch(
        f"{V1}/vendor/menu/items/{kitchen.coke_id}",
        json={"is_hidden": False},
        headers=kitchen.headers,
    )
    assert r.status_code == 400

    r = await client.get(
        f"{V1}/admin/products?restaurant_id={kitchen.restaurant.id}&status=HIDDEN", headers=admin
    )
    assert [p["name"] for p in r.json()["data"]] == ["Coke"]


async def test_featured_products_lead_the_list(client, admin, kitchen):
    await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}", json={"is_featured": True}, headers=admin
    )
    r = await client.get(
        f"{V1}/admin/products?restaurant_id={kitchen.restaurant.id}", headers=admin
    )
    assert [p["name"] for p in r.json()["data"]] == ["Coke", "Beef Burger"]

    menu = await client.get(f"{V1}/restaurants/{kitchen.restaurant.id}/menu")
    coke = next(i for c in menu.json()["data"] for i in c["items"] if i["name"] == "Coke")
    assert coke["is_featured"] is True


async def test_admin_edits_follow_the_vendor_rules(client, admin, kitchen):
    r = await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}",
        json={"name": "Coca-Cola", "base_price": 70},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"] == "Coca-Cola"
    assert r.json()["data"]["base_price"] == 70.0

    for bad in ({"commission_rate": 15}, {"base_price": -1}, {"is_hidden": True, "surprise": 1}):
        r = await client.patch(f"{V1}/admin/products/{kitchen.coke_id}", json=bad, headers=admin)
        assert r.status_code == 400, (bad, r.text)


async def test_add_a_product_by_category_then_delete_it(client, admin, kitchen, categories):
    drinks = await _category(client, admin, categories, kind="STORE")
    r = await client.post(
        f"{V1}/admin/vendors/{kitchen.restaurant.id}/products",
        json={
            "name": "Mineral Water",
            "base_price": 25,
            "platform_category_id": drinks["id"],
            "commission_rate": 0.2,
            "is_featured": True,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    water = r.json()["data"]
    assert water["platform_category"]["id"] == drinks["id"]
    assert water["commission"]["rate"] == 0.2
    assert water["is_featured"] is True

    r = await client.post(
        f"{V1}/admin/vendors/{kitchen.restaurant.id}/products",
        json={"name": "Nowhere", "base_price": 10},
        headers=admin,
    )
    assert r.status_code == 400  # neither a section nor a category

    r = await client.delete(f"{V1}/admin/products/{water['id']}", headers=admin)
    assert r.status_code == 200
    r = await client.get(f"{V1}/admin/products/{water['id']}", headers=admin)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


async def test_category_commission_kind_and_product_count(client, admin, kitchen, categories):
    grocery = await _category(client, admin, categories, kind="STORE", commission_rate=0.12)
    assert grocery["kind"] == "STORE"
    assert grocery["commission_rate"] == 0.12

    await client.patch(
        f"{V1}/admin/products/{kitchen.coke_id}",
        json={"platform_category_id": grocery["id"]},
        headers=admin,
    )
    r = await client.get(f"{V1}/admin/categories?kind=STORE&q={grocery['name']}", headers=admin)
    [row] = r.json()["data"]
    assert row["product_count"] == 1

    r = await client.get(f"{V1}/admin/products?category_id={grocery['id']}", headers=admin)
    assert [p["name"] for p in r.json()["data"]] == ["Coke"]

    r = await client.patch(
        f"{V1}/admin/categories/{grocery['id']}", json={"commission_rate": None}, headers=admin
    )
    assert r.json()["data"]["commission_rate"] is None

    r = await client.get(f"{V1}/admin/categories?sort=name&limit=100", headers=admin)
    names = [c["name"] for c in r.json()["data"]]
    assert names == sorted(names)

    r = await client.get(f"{V1}/admin/categories?kind=BAKERY", headers=admin)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Mark Unpaid
# ---------------------------------------------------------------------------


async def test_mark_unpaid_reopens_without_moving_the_balance(client, admin, vendor):
    from app.core.database import SessionLocal
    from app.models.payout import VendorPayout

    payout = VendorPayout(
        restaurant_id=vendor.restaurant.id,
        reference=f"CHR{uuid.uuid4().int % 10**9:09d}",
        amount=50_000,
        method="BKASH",
        account_number="01712345678",
        account_name="Karim Ahmed",
    )
    async with SessionLocal() as s:
        s.add(payout)
        await s.commit()

    async def balance():
        r = await client.get(f"{V1}/admin/vendors/{vendor.restaurant.id}/finance", headers=admin)
        return r.json()["data"]["available_balance"]

    r = await client.post(
        f"{V1}/admin/payouts/{payout.id}/reopen", json={"reason": "Oops"}, headers=admin
    )
    assert r.status_code == 400  # still PROCESSING: nothing to take back

    await client.post(f"{V1}/admin/payouts/{payout.id}/complete", headers=admin)
    before = await balance()

    r = await client.post(
        f"{V1}/admin/payouts/{payout.id}/reopen",
        json={"reason": "bKash transfer bounced"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    row = r.json()["data"]["payout"]
    assert row["status"] == "PROCESSING"
    assert row["reopen_reason"] == "bKash transfer bounced"
    assert row["reopened_at"] is not None
    assert row["processed_at"] is None
    assert await balance() == before

    # Back in the queue, and payable again.
    r = await client.get(f"{V1}/admin/payouts?restaurant_id={vendor.restaurant.id}", headers=admin)
    assert [p["id"] for p in r.json()["data"]] == [str(payout.id)]
    r = await client.post(f"{V1}/admin/payouts/{payout.id}/complete", headers=admin)
    assert r.status_code == 200
