"""Platform browse categories: what naming a menu section does on the customer end.

Vendors build the taxonomy by naming menu sections, customers browse it as
chips, administrators approve and curate it. These tests cross all three over
HTTP because the thing most likely to break is the seam: a section created on
the vendor side must be countable on the customer side, under one chip,
however it was spelled — but only once a person has approved that chip.

That approval step is the reason almost every test here takes `admin_token`.
A category a vendor's section name created starts hidden, so a test that
creates a section and expects a chip without approving one is asserting the
old, permissive behaviour.

Platform categories are global rows owned by no fixture's vendor, so every
test names its sections uniquely and removes the categories it caused to
exist — otherwise they would accumulate across runs and collide with the
taxonomy migration 0007 seeds ("Burger" exists in every database).
"""

import uuid

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"

# Dhanmondi, ~0 km from the fixture restaurants; Chittagong, ~215 km away.
NEAR = {"lat": 23.7936, "lng": 90.4064}
FAR = {"lat": 22.3569, "lng": 91.7832}


class _Names:
    """Unique section names for one test, plus the platform rows to drop."""

    def __init__(self) -> None:
        self.made: list[str] = []
        self.ids: list[uuid.UUID] = []

    def __call__(self, base: str) -> str:
        name = f"{base} {uuid.uuid4().hex[:6]}"
        self.made.append(name)
        return name

    def track(self, category_id: str) -> None:
        self.ids.append(uuid.UUID(category_id))


@pytest.fixture
async def names():
    from sqlalchemy import delete, or_

    from app.core.database import SessionLocal
    from app.models.category import Category
    from app.services.category_service import slug_for

    registry = _Names()
    yield registry

    # menu_categories.category_id is ON DELETE SET NULL, so this is safe
    # whether or not the vendor fixtures have unwound yet.
    async with SessionLocal() as s:
        slugs = [slug_for(n) for n in registry.made]
        await s.execute(
            delete(Category).where(or_(Category.slug.in_(slugs), Category.id.in_(registry.ids)))
        )
        await s.commit()


def _admin(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _section(client, vendor, name: str, **extra) -> dict:
    r = await client.post(
        f"{V1}/vendor/menu/categories", json={"name": name, **extra}, headers=vendor.headers
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _dish(client, vendor, section_id: str, name: str = "Something tasty") -> dict:
    r = await client.post(
        f"{V1}/vendor/menu/items",
        json={"name": name, "category_id": section_id, "base_price": 250},
        headers=vendor.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _approve(client, admin_token, category_id: str) -> dict:
    """What an administrator does in the Categories tab before customers see it."""
    r = await client.patch(
        f"{V1}/admin/categories/{category_id}",
        json={"is_active": True},
        headers=_admin(admin_token),
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _live_section(client, vendor, admin_token, names, base: str) -> tuple[dict, str]:
    """The whole chain: section, dish, approved chip. Returns (section, slug)."""
    name = names(base)
    section = await _section(client, vendor, name)
    await _dish(client, vendor, section["id"])
    await _approve(client, admin_token, section["platform_category"]["id"])
    return section, section["platform_category"]["slug"]


async def _chip_slugs(client) -> list[str]:
    r = await client.get(f"{V1}/categories")
    assert r.status_code == 200, r.text
    return [c["slug"] for c in r.json()["data"]]


# ---------------------------------------------------------------------------
# Vendor side — a section name is all it takes
# ---------------------------------------------------------------------------


async def test_a_new_section_lists_under_a_platform_category(client, vendor, names):
    """The vendor never sees the taxonomy; naming the section is enough."""
    from app.services.category_service import display_name, slug_for

    name = names("Tacos")
    section = await _section(client, vendor, name.lower())

    platform = section["platform_category"]
    assert platform["slug"] == slug_for(name)
    assert platform["name"] == display_name(name.lower())

    # And the same link is reported wherever the section appears.
    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert r.json()["data"][0]["platform_category"]["id"] == platform["id"]
    r = await client.get(f"{V1}/vendor/menu", headers=vendor.headers)
    assert r.json()["data"]["categories"][0]["platform_category"]["id"] == platform["id"]


async def test_two_vendors_spelling_it_differently_share_one_category(
    client, vendor, other_vendor, names
):
    """ "Tacos", "TACOS " and "tacos" are one chip, not three."""
    name = names("Tacos")
    a = await _section(client, vendor, name)
    b = await _section(client, other_vendor, f"  {name.upper()} ")
    assert a["platform_category"]["id"] == b["platform_category"]["id"]


async def test_a_section_can_be_pinned_to_a_chosen_category(client, vendor, admin_token, names):
    """ "Chef's picks" belongs nowhere by name; the vendor files it explicitly."""
    wraps = await _section(client, vendor, names("Wraps"))
    target = wraps["platform_category"]["id"]
    # Only an approved category is offered in the picker, so only one can be
    # pinned to — a vendor cannot reach into the review queue.
    r = await client.post(
        f"{V1}/vendor/menu/categories",
        json={"name": names("Too soon"), "platform_category_id": target},
        headers=vendor.headers,
    )
    assert r.status_code == 404, r.text
    await _approve(client, admin_token, target)

    picks = await _section(client, vendor, names("Chef's picks"), platform_category_id=target)
    assert picks["platform_category"]["id"] == target

    r = await client.post(
        f"{V1}/vendor/menu/categories",
        json={"name": names("Nowhere"), "platform_category_id": str(uuid.uuid4())},
        headers=vendor.headers,
    )
    assert r.status_code == 404, r.text
    r = await client.post(
        f"{V1}/vendor/menu/categories",
        json={"name": names("Nowhere"), "platform_category_id": "not-an-id"},
        headers=vendor.headers,
    )
    assert r.status_code == 400, r.text


async def test_rename_rematches_only_when_the_new_name_matches_something(
    client, vendor, admin_token, names
):
    """A typo must not spawn a chip; an unlinked section must still get one."""
    from app.services.category_service import slug_for

    tacos = await _section(client, vendor, names("Tacos"))
    wraps = await _section(client, vendor, names("Wraps"))
    wraps_id = wraps["platform_category"]["id"]
    await _approve(client, admin_token, wraps_id)
    path = f"{V1}/vendor/menu/categories/{tacos['id']}"

    # Renamed to the other section's spelling: re-linked by name.
    r = await client.patch(path, json={"name": wraps["name"].upper()}, headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["platform_category"]["id"] == wraps_id

    # Renamed to something nothing matches: the link is kept, not replaced.
    r = await client.patch(path, json={"name": names("Mystery")}, headers=vendor.headers)
    assert r.json()["data"]["platform_category"]["id"] == wraps_id

    # An explicit null unlinks.
    r = await client.patch(path, json={"platform_category_id": None}, headers=vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["platform_category"] is None

    # An unlinked section renamed to a fresh name gets a category of its own.
    fresh = names("Brand new")
    r = await client.patch(path, json={"name": fresh}, headers=vendor.headers)
    assert r.json()["data"]["platform_category"]["slug"] == slug_for(fresh)

    # Pinning by id, and a reorder that says nothing about the link, leave it.
    r = await client.patch(
        path, json={"platform_category_id": wraps_id, "sort_order": 4}, headers=vendor.headers
    )
    assert r.json()["data"]["platform_category"]["id"] == wraps_id
    r = await client.patch(path, json={"sort_order": 5}, headers=vendor.headers)
    assert r.json()["data"]["platform_category"]["id"] == wraps_id


# ---------------------------------------------------------------------------
# The approval gate — a vendor cannot write to the home screen
# ---------------------------------------------------------------------------


async def test_a_vendor_created_category_is_hidden_until_approved(
    client, vendor, admin_token, names
):
    """The whole point of the gate, in one test.

    The vendor's own menu works the entire time; only the chip waits.
    """
    from app.services.category_service import slug_for

    h = _admin(admin_token)
    name = names("Tehari")
    slug = slug_for(name)
    section = await _section(client, vendor, name)
    await _dish(client, vendor, section["id"])
    platform_id = section["platform_category"]["id"]

    # Invisible to customers, despite a verified restaurant with a live dish.
    assert slug not in await _chip_slugs(client)
    assert (await client.get(f"{V1}/categories/{slug}")).status_code == 404
    r = await client.get(f"{V1}/restaurants", params={"category": slug})
    assert r.json()["meta"]["total"] == 0

    # The vendor is not blocked: their section and dish are live on their page.
    r = await client.get(f"{V1}/restaurants/{vendor.restaurant.id}/menu")
    assert [c["name"] for c in r.json()["data"]] == [name]

    # It is sitting in the administrator's review queue, with its impact shown.
    r = await client.get(f"{V1}/admin/categories", params={"pending": True}, headers=h)
    assert r.status_code == 200, r.text
    row = next(c for c in r.json()["data"] if c["id"] == platform_id)
    assert row["is_pending"] is True
    assert row["is_active"] is False
    assert row["reviewed_at"] is None
    assert row["restaurant_count"] == 1

    # Approving it publishes the chip, with the restaurant already under it.
    approved = await _approve(client, admin_token, platform_id)
    assert approved["is_pending"] is False and approved["is_active"] is True
    assert approved["reviewed_at"] is not None
    assert slug in await _chip_slugs(client)
    r = await client.get(f"{V1}/restaurants", params={"category": slug})
    assert [c["id"] for c in r.json()["data"]] == [str(vendor.restaurant.id)]

    # And it has left the queue.
    r = await client.get(f"{V1}/admin/categories", params={"pending": True}, headers=h)
    assert platform_id not in [c["id"] for c in r.json()["data"]]


async def test_keeping_one_hidden_takes_it_out_of_the_queue_for_good(
    client, vendor, admin_token, names
):
    """ "I looked at this and no" must be a decision, not a thing that
    reappears on every refresh."""
    from app.services.category_service import slug_for

    h = _admin(admin_token)
    name = names("Combo deals")
    slug = slug_for(name)
    section = await _section(client, vendor, name)
    await _dish(client, vendor, section["id"])
    platform_id = section["platform_category"]["id"]

    r = await client.patch(
        f"{V1}/admin/categories/{platform_id}", json={"is_active": False}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_pending"] is False
    assert r.json()["data"]["is_active"] is False

    # Gone from the queue, still not a chip, still linked to the vendor.
    r = await client.get(f"{V1}/admin/categories", params={"pending": True}, headers=h)
    assert platform_id not in [c["id"] for c in r.json()["data"]]
    assert slug not in await _chip_slugs(client)
    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert r.json()["data"][0]["platform_category"]["id"] == platform_id


async def test_a_second_vendor_joins_the_pending_category_rather_than_making_another(
    client, vendor, other_vendor, admin_token, names
):
    """Approval is one decision however many vendors are waiting on it."""
    name = names("Tehari")
    a = await _section(client, vendor, name)
    await _dish(client, vendor, a["id"])
    b = await _section(client, other_vendor, name.upper())
    await _dish(client, other_vendor, b["id"])
    assert a["platform_category"]["id"] == b["platform_category"]["id"]

    approved = await _approve(client, admin_token, a["platform_category"]["id"])
    assert approved["restaurant_count"] == 2
    r = await client.get(f"{V1}/restaurants", params={"category": approved["slug"]})
    assert r.json()["meta"]["total"] == 2


# ---------------------------------------------------------------------------
# Customer side — the chip row and what a tap opens
# ---------------------------------------------------------------------------


async def test_a_chip_appears_once_a_visible_restaurant_sells_under_it(
    client, vendor, admin_token, names
):
    from app.services.category_service import slug_for

    name = names("Tacos")
    slug = slug_for(name)
    section = await _section(client, vendor, name)
    await _approve(client, admin_token, section["platform_category"]["id"])

    # Approved, but no dish yet: the chip would open onto nothing.
    assert slug not in await _chip_slugs(client)

    await _dish(client, vendor, section["id"])
    r = await client.get(f"{V1}/categories")
    chip = next(c for c in r.json()["data"] if c["slug"] == slug)
    assert chip["restaurant_count"] == 1

    feed = await client.get(f"{V1}/home/feed")
    assert feed.status_code == 200, feed.text
    assert slug in [c["slug"] for c in feed.json()["data"]["categories"]]


async def test_unverified_and_deactivated_sections_do_not_count(
    client, vendor, pending_vendor, admin_token, names
):
    from app.services.category_service import slug_for

    name = names("Tacos")
    slug = slug_for(name)

    # An unapproved restaurant is invisible, so its section counts for nothing.
    hidden = await _section(client, pending_vendor, name)
    await _dish(client, pending_vendor, hidden["id"])
    await _approve(client, admin_token, hidden["platform_category"]["id"])
    assert slug not in await _chip_slugs(client)

    # A visible one counts — until it deactivates the section.
    mine = await _section(client, vendor, name)
    await _dish(client, vendor, mine["id"])
    assert slug in await _chip_slugs(client)

    r = await client.patch(
        f"{V1}/vendor/menu/categories/{mine['id']}",
        json={"is_active": False},
        headers=vendor.headers,
    )
    assert r.status_code == 200, r.text
    assert slug not in await _chip_slugs(client)

    # A deep link to an empty category still resolves, with a count of zero.
    r = await client.get(f"{V1}/categories/{slug}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["restaurant_count"] == 0


async def test_restaurants_and_dishes_can_be_browsed_by_category(
    client, vendor, other_vendor, admin_token, names
):
    """The two things a chip opens: the restaurants, and "all tacos near me"."""
    from app.services.category_service import slug_for

    name = names("Tacos")
    slug = slug_for(name)
    a = await _section(client, vendor, name)
    await _dish(client, vendor, a["id"], "Beef Taco")
    b = await _section(client, other_vendor, name.lower())
    await _dish(client, other_vendor, b["id"], "Fish Taco")
    await _approve(client, admin_token, a["platform_category"]["id"])
    soup = await _section(client, other_vendor, names("Soup"))
    await _dish(client, other_vendor, soup["id"], "Tom Yum")

    r = await client.get(f"{V1}/restaurants", params={"category": slug})
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()["data"]} == {
        str(vendor.restaurant.id),
        str(other_vendor.restaurant.id),
    }
    assert r.json()["meta"]["total"] == 2

    r = await client.get(f"{V1}/categories/{slug}/items")
    assert r.status_code == 200, r.text
    dishes = r.json()["data"]
    assert {d["name"] for d in dishes} == {"Beef Taco", "Fish Taco"}
    assert r.json()["meta"]["total"] == 2
    taco = next(d for d in dishes if d["name"] == "Beef Taco")
    assert taco["restaurant_name"] == vendor.restaurant.name
    assert taco["restaurant_id"] == str(vendor.restaurant.id)
    assert taco["base_price"] == 250.0
    assert taco["distance_km"] is None

    # Coordinates fill in distance and bound the radius.
    r = await client.get(f"{V1}/categories/{slug}/items", params=NEAR)
    assert all(d["distance_km"] is not None for d in r.json()["data"])
    far = await client.get(f"{V1}/categories/{slug}/items", params={**FAR, "radius": 1000})
    assert far.json()["meta"]["total"] == 0

    # The chip's count is the number of restaurants the list will show.
    r = await client.get(f"{V1}/categories/{slug}")
    assert r.json()["data"]["restaurant_count"] == 2

    assert (await client.get(f"{V1}/categories/no-such-chip-xyz")).status_code == 404
    assert (await client.get(f"{V1}/categories/no-such-chip-xyz/items")).status_code == 404


async def test_search_offers_the_chip(client, vendor, admin_token, names):
    _, slug = await _live_section(client, vendor, admin_token, names, "Tacos")
    word = slug.split("-")[0]

    r = await client.get(f"{V1}/search", params={"q": word})
    assert r.status_code == 200, r.text
    assert slug in [c["slug"] for c in r.json()["data"]["categories"]]


# ---------------------------------------------------------------------------
# Administrator side — curation
# ---------------------------------------------------------------------------


async def test_only_administrators_curate(client, vendor, customer_token):
    r = await client.get(f"{V1}/admin/categories", headers=vendor.headers)
    assert r.status_code == 403, r.text
    r = await client.post(
        f"{V1}/admin/categories", json={"name": "X"}, headers=_admin(customer_token)
    )
    assert r.status_code == 403, r.text
    r = await client.get(f"{V1}/admin/categories")
    assert r.status_code == 401, r.text


async def test_admin_creates_curates_and_hides(client, admin_token, vendor, names):
    h = _admin(admin_token)
    name, alias = names("Wraps"), names("Rolls")

    r = await client.post(
        f"{V1}/admin/categories", json={"name": name, "aliases": [alias]}, headers=h
    )
    assert r.status_code == 201, r.text
    created = r.json()["data"]
    names.track(created["id"])
    assert created["aliases"] == [alias.lower()]
    assert created["restaurant_count"] == 0 and created["section_count"] == 0
    # An administrator typing it IS the review, so it never enters the queue.
    assert created["is_pending"] is False and created["is_active"] is True

    # The name, or any alias, is now taken.
    r = await client.post(f"{V1}/admin/categories", json={"name": name.upper()}, headers=h)
    assert r.status_code == 409, r.text
    r = await client.post(f"{V1}/admin/categories", json={"name": alias}, headers=h)
    assert r.status_code == 409, r.text

    # A vendor section named with the alias lands here, and is counted — with
    # no approval step, because this category was already approved on create.
    section = await _section(client, vendor, alias.title())
    assert section["platform_category"]["id"] == created["id"]
    await _dish(client, vendor, section["id"])
    r = await client.get(f"{V1}/admin/categories", params={"limit": 100}, headers=h)
    assert r.status_code == 200, r.text
    row = next(c for c in r.json()["data"] if c["id"] == created["id"])
    assert row["restaurant_count"] == 1 and row["section_count"] == 1

    # Image and pin: first in the customer list, with the picture.
    path = f"{V1}/admin/categories/{created['id']}"
    r = await client.patch(
        path, json={"image_url": "https://cdn.example/wraps.png", "sort_order": 0}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sort_order"] == 0
    chips = (await client.get(f"{V1}/categories")).json()["data"]
    assert chips[0]["id"] == created["id"]
    assert chips[0]["image_url"] == "https://cdn.example/wraps.png"

    # Rename keeps the slug and remembers the old name.
    r = await client.patch(path, json={"name": names("Wrapz")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["slug"] == created["slug"]
    assert name.lower() in r.json()["data"]["aliases"]

    # Hide: gone from every customer surface, still linked for the vendor.
    r = await client.patch(path, json={"is_active": False}, headers=h)
    assert r.status_code == 200, r.text
    assert created["slug"] not in await _chip_slugs(client)
    assert (await client.get(f"{V1}/categories/{created['slug']}")).status_code == 404
    r = await client.get(f"{V1}/restaurants", params={"category": created["slug"]})
    assert r.json()["meta"]["total"] == 0
    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert r.json()["data"][0]["platform_category"]["id"] == created["id"]

    # Un-pin, and refuse to delete while a section still links to it.
    r = await client.patch(path, json={"sort_order": None}, headers=h)
    assert r.json()["data"]["sort_order"] is None
    r = await client.delete(path, headers=h)
    assert r.status_code == 409, r.text
    assert "Merge" in r.json()["error"]["message"]


async def test_merge_moves_sections_and_learns_the_spelling(
    client, admin_token, vendor, other_vendor, names
):
    """Two vendors, two spellings, two chips — until an operator merges them."""
    h = _admin(admin_token)
    singular = names("Burger")
    plural = f"{singular}s"

    a = await _section(client, vendor, plural)
    b = await _section(client, other_vendor, singular)
    loser, survivor = a["platform_category"], b["platform_category"]
    assert loser["id"] != survivor["id"]
    names.track(loser["id"])
    await _dish(client, vendor, a["id"])
    await _dish(client, other_vendor, b["id"])
    await _approve(client, admin_token, loser["id"])
    await _approve(client, admin_token, survivor["id"])
    assert loser["slug"] in await _chip_slugs(client)

    merge = f"{V1}/admin/categories/{loser['id']}/merge"
    r = await client.post(merge, json={"into_id": loser["id"]}, headers=h)
    assert r.status_code == 400, r.text
    r = await client.post(merge, json={"into_id": str(uuid.uuid4())}, headers=h)
    assert r.status_code == 404, r.text

    r = await client.post(merge, json={"into_id": survivor["id"]}, headers=h)
    assert r.status_code == 200, r.text
    merged = r.json()["data"]
    assert merged["id"] == survivor["id"]
    assert merged["restaurant_count"] == 2 and merged["section_count"] == 2
    assert plural.lower() in merged["aliases"]

    # The loser is gone; the vendor's section now reports the survivor.
    r = await client.patch(
        f"{V1}/admin/categories/{loser['id']}", json={"sort_order": 1}, headers=h
    )
    assert r.status_code == 404, r.text
    r = await client.get(f"{V1}/vendor/menu/categories", headers=vendor.headers)
    assert r.json()["data"][0]["platform_category"]["id"] == survivor["id"]

    # The old spelling resolves to the survivor from now on …
    again = await _section(client, vendor, plural.upper())
    assert again["platform_category"]["id"] == survivor["id"]

    # … one chip counts both restaurants …
    chips = await _chip_slugs(client)
    assert survivor["slug"] in chips and loser["slug"] not in chips
    r = await client.get(f"{V1}/categories/{survivor['slug']}")
    assert r.json()["data"]["restaurant_count"] == 2

    # … and a link to the old slug still opens it.
    r = await client.get(f"{V1}/categories/{loser['slug']}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == survivor["id"]
    r = await client.get(f"{V1}/restaurants", params={"category": loser["slug"]})
    assert r.json()["meta"]["total"] == 2


async def test_delete_removes_an_unused_category_and_hidden_ones_stay_listed(
    client, admin_token, names
):
    h = _admin(admin_token)

    r = await client.post(f"{V1}/admin/categories", json={"name": names("Fondue")}, headers=h)
    assert r.status_code == 201, r.text
    fondue = r.json()["data"]["id"]
    names.track(fondue)
    r = await client.delete(f"{V1}/admin/categories/{fondue}", headers=h)
    assert r.status_code == 200, r.text
    r = await client.delete(f"{V1}/admin/categories/{fondue}", headers=h)
    assert r.status_code == 404, r.text

    r = await client.post(
        f"{V1}/admin/categories", json={"name": names("Hidden"), "is_active": False}, headers=h
    )
    assert r.status_code == 201, r.text
    hidden = r.json()["data"]
    names.track(hidden["id"])

    # The curation list shows it (hidden, empty); the customer list never does.
    r = await client.get(f"{V1}/admin/categories", params={"limit": 100}, headers=h)
    assert hidden["id"] in [c["id"] for c in r.json()["data"]]
    assert hidden["slug"] not in await _chip_slugs(client)
