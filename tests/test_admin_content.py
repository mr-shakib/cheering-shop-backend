"""Admin-added and admin-edited vendors, reels, app banners, and the discovery
radius. Driven over HTTP, like the rest of the admin suites."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


@pytest.fixture
def admin(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _vendor_body(email: str, phone: str, **extra) -> dict:
    return {
        "name": f"Admin Kitchen {uuid.uuid4().hex[:6]}",
        "address_line": "House 7, Road 3, Banani, Dhaka",
        "latitude": 23.7940,
        "longitude": 90.4043,
        "owner_full_name": "Rahim Uddin",
        "owner_email": email,
        "owner_phone": phone,
        **extra,
    }


def _phone() -> str:
    return f"+88017{uuid.uuid4().int % 10**8:08d}"


def _ids(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [c["id"] for c in r.json()["data"]]


# ---------------------------------------------------------------------------
# Add a vendor
# ---------------------------------------------------------------------------


async def test_an_added_vendor_is_listed_at_once_and_can_sign_in(
    client, admin, cleanup_users
):
    email = cleanup_users(f"added-{uuid.uuid4().hex[:8]}@example.com")
    body = _vendor_body(
        email,
        _phone(),
        owner_password="VendorPassword1!",
        business_type="GROCERY",
        business_category="Supermarket",
        national_id="1990123456",
        documents={"shop_image": "https://cdn.example.com/shop.jpg"},
        payout={"method": "BKASH", "account_name": "Rahim", "account_number": "01712345678"},
        min_order_amount=150,
    )
    r = await client.post(f"{V1}/admin/vendors", json=body, headers=admin)
    assert r.status_code == 201, r.text
    detail = r.json()["data"]
    assert detail["is_verified"] is True
    assert detail["status"] == "CLOSED"
    assert detail["onboarding_source"] == "ADMIN"
    assert detail["application_no"].startswith("PTN-")
    assert detail["business_type"] == "GROCERY"
    assert detail["owner"]["national_id"] == "1990123456"
    assert detail["documents"] == {"shop_image": "https://cdn.example.com/shop.jpg"}
    assert detail["payout"]["method"] == "BKASH"
    assert detail["min_order_amount"] == 150
    # The Settings screen's grocery rate, 15% by default.
    assert detail["commission_rate"] == 0.15

    # Customers can find it straight away — no approval step.
    assert detail["id"] in _ids(await client.get(f"{V1}/restaurants", params={"limit": 100}))

    login = await client.post(
        f"{V1}/auth/login", json={"email": email, "password": "VendorPassword1!"}
    )
    assert login.status_code == 200, login.text


async def test_an_unverified_add_waits_in_the_application_queue(client, admin, cleanup_users):
    email = cleanup_users(f"queued-{uuid.uuid4().hex[:8]}@example.com")
    r = await client.post(
        f"{V1}/admin/vendors", json=_vendor_body(email, _phone(), is_verified=False), headers=admin
    )
    assert r.status_code == 201, r.text
    detail = r.json()["data"]
    assert detail["id"] not in _ids(await client.get(f"{V1}/restaurants", params={"limit": 100}))

    queue = await client.get(
        f"{V1}/admin/vendor-applications", params={"q": detail["application_no"]}, headers=admin
    )
    [application] = queue.json()["data"]
    assert application["status"] == "PENDING"
    assert application["source"] == "ADMIN"

    # Approving from the edit form settles the application too.
    r = await client.patch(
        f"{V1}/admin/vendors/{detail['id']}", json={"is_verified": True}, headers=admin
    )
    assert r.status_code == 200, r.text
    after = await client.get(
        f"{V1}/admin/vendor-applications/{application['id']}", headers=admin
    )
    assert after.json()["data"]["status"] == "APPROVED"
    assert detail["id"] in _ids(await client.get(f"{V1}/restaurants", params={"limit": 100}))


async def test_adding_a_vendor_with_a_taken_email_is_a_conflict(client, admin, vendor):
    r = await client.post(
        f"{V1}/admin/vendors", json=_vendor_body(vendor.user.email, _phone()), headers=admin
    )
    assert r.status_code == 409, r.text


async def test_only_an_admin_can_add_a_vendor(client, vendor):
    r = await client.post(
        f"{V1}/admin/vendors",
        json=_vendor_body("x@example.com", _phone()),
        headers=vendor.headers,
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Edit a vendor
# ---------------------------------------------------------------------------


async def test_edit_changes_store_owner_and_business_details(client, admin, vendor):
    """The `vendor` fixture has no partner record, like a fast-path vendor:
    the first business-field edit creates one."""
    phone = _phone()
    r = await client.patch(
        f"{V1}/admin/vendors/{vendor.restaurant.id}",
        json={
            "name": "Renamed Kitchen",
            "latitude": 23.8103,
            "longitude": 90.4125,
            "min_order_amount": 99,
            "owner_full_name": "Karim Hossain",
            "owner_phone": phone,
            "business_category": "Street Food",
            "national_id": "1987654321",
            "documents": {"owner_nid": "https://cdn.example.com/nid.pdf"},
            "business_hours": {
                day: {"is_open": True, "opens_at": "09:00", "closes_at": "21:00"}
                for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            },
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["name"] == "Renamed Kitchen"
    assert (d["latitude"], d["longitude"]) == (23.8103, 90.4125)
    assert d["min_order_amount"] == 99
    assert d["owner"]["full_name"] == "Karim Hossain"
    assert d["owner"]["phone"] == phone
    assert d["owner"]["national_id"] == "1987654321"
    assert d["business_category"] == "Street Food"
    assert d["onboarding_source"] == "ADMIN"
    assert d["documents"] == {"owner_nid": "https://cdn.example.com/nid.pdf"}
    assert d["business_hours"]["mon"]["opens_at"] == "09:00"

    # Documents merge: add one, remove another.
    r = await client.patch(
        f"{V1}/admin/vendors/{vendor.restaurant.id}",
        json={"documents": {"owner_nid": None, "menu_list": "https://cdn.example.com/m.pdf"}},
        headers=admin,
    )
    assert r.json()["data"]["documents"] == {"menu_list": "https://cdn.example.com/m.pdf"}


async def test_edit_refuses_half_a_location_and_a_taken_email(client, admin, vendor, other_vendor):
    url = f"{V1}/admin/vendors/{vendor.restaurant.id}"
    r = await client.patch(url, json={"latitude": 23.9}, headers=admin)
    assert r.status_code == 400, r.text
    r = await client.patch(url, json={"owner_email": other_vendor.user.email}, headers=admin)
    assert r.status_code == 409, r.text
    r = await client.patch(url, json={}, headers=admin)
    assert r.status_code == 400, r.text


async def test_suspending_from_the_edit_form_hides_and_closes(client, admin, vendor):
    r = await client.patch(
        f"{V1}/admin/vendors/{vendor.restaurant.id}",
        json={"is_verified": False},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "CLOSED"
    listed = _ids(await client.get(f"{V1}/restaurants", params={"limit": 100}))
    assert str(vendor.restaurant.id) not in listed


async def test_an_admin_can_reset_the_owners_password(client, admin, vendor):
    r = await client.patch(
        f"{V1}/admin/vendors/{vendor.restaurant.id}",
        json={"owner_password": "BrandNewPass1!"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    login = await client.post(
        f"{V1}/auth/login", json={"email": vendor.user.email, "password": "BrandNewPass1!"}
    )
    assert login.status_code == 200, login.text


# ---------------------------------------------------------------------------
# Reels
# ---------------------------------------------------------------------------


def _reel(**extra) -> dict:
    return {
        "video_url": "https://cdn.example.com/reel.mp4",
        "thumbnail_url": "https://cdn.example.com/reel.jpg",
        "caption": "Fresh off the grill",
        "duration_seconds": 18,
        **extra,
    }


async def test_a_vendor_reel_reaches_the_feed_with_its_restaurant_card(client, kitchen):
    r = await client.post(
        f"{V1}/vendor/reels", json=_reel(menu_item_id=kitchen.burger_id), headers=kitchen.headers
    )
    assert r.status_code == 201, r.text
    reel_id = r.json()["data"]["id"]
    assert r.json()["data"]["menu_item_name"] == "Beef Burger"

    feed = await client.get(
        f"{V1}/reels",
        params={"restaurant_id": str(kitchen.restaurant.id), "lat": 23.8080, "lng": 90.4064},
    )
    assert feed.status_code == 200, feed.text
    [item] = feed.json()["data"]
    assert item["id"] == reel_id
    assert item["restaurant"]["id"] == str(kitchen.restaurant.id)
    assert 1.0 < item["restaurant"]["distance_km"] < 2.0
    assert item["menu_item"]["name"] == "Beef Burger"
    assert item["menu_item"]["price"] == 300

    mine = await client.get(f"{V1}/vendor/reels", headers=kitchen.headers)
    assert [x["id"] for x in mine.json()["data"]] == [reel_id]

    r = await client.delete(f"{V1}/vendor/reels/{reel_id}", headers=kitchen.headers)
    assert r.status_code == 200, r.text
    feed = await client.get(f"{V1}/reels", params={"restaurant_id": str(kitchen.restaurant.id)})
    assert feed.json()["data"] == []


async def test_a_reel_cannot_tag_another_restaurants_dish(client, kitchen, other_vendor):
    r = await client.post(
        f"{V1}/vendor/reels",
        json=_reel(menu_item_id=kitchen.burger_id),
        headers=other_vendor.headers,
    )
    assert r.status_code == 400, r.text


async def test_a_vendor_cannot_delete_another_vendors_reel(client, vendor, other_vendor):
    r = await client.post(f"{V1}/vendor/reels", json=_reel(), headers=vendor.headers)
    reel_id = r.json()["data"]["id"]
    r = await client.delete(f"{V1}/vendor/reels/{reel_id}", headers=other_vendor.headers)
    assert r.status_code == 404


async def test_hidden_reels_and_hidden_restaurants_stay_out_of_the_feed(
    client, admin, vendor, pending_vendor
):
    r = await client.post(
        f"{V1}/admin/reels",
        json=_reel(restaurant_id=str(vendor.restaurant.id)),
        headers=admin,
    )
    assert r.status_code == 201, r.text
    reel_id = r.json()["data"]["id"]
    await client.post(f"{V1}/vendor/reels", json=_reel(), headers=pending_vendor.headers)

    feed = await client.get(f"{V1}/reels", params={"limit": 100})
    ids = [x["id"] for x in feed.json()["data"]]
    restaurants = {x["restaurant"]["id"] for x in feed.json()["data"]}
    assert reel_id in ids
    # An unapproved restaurant's reel is not shown.
    assert str(pending_vendor.restaurant.id) not in restaurants

    r = await client.patch(
        f"{V1}/admin/reels/{reel_id}",
        json={"is_hidden": True, "hidden_reason": "Blurry"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    feed = await client.get(f"{V1}/reels", params={"limit": 100})
    assert reel_id not in [x["id"] for x in feed.json()["data"]]

    # The vendor still sees it, with the reason.
    [own] = (await client.get(f"{V1}/vendor/reels", headers=vendor.headers)).json()["data"]
    assert own["is_hidden"] is True
    assert own["hidden_reason"] == "Blurry"

    hidden = await client.get(f"{V1}/admin/reels", params={"status": "HIDDEN"}, headers=admin)
    assert reel_id in [x["id"] for x in hidden.json()["data"]]

    r = await client.delete(f"{V1}/admin/reels/{reel_id}", headers=admin)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


async def test_upload_types_are_scoped_to_the_purpose(client, admin, vendor, monkeypatch):
    from tests.test_vendor_api import _configure_r2

    _configure_r2(monkeypatch)

    async def presign(path, file_type, headers):
        return await client.post(path, json={"file_type": file_type}, headers=headers)

    general = f"{V1}/uploads/presigned-url"
    reels = f"{V1}/vendor/reels/uploads"
    console = f"{V1}/admin/uploads/presigned-url"

    assert (await presign(general, "video/mp4", vendor.headers)).status_code == 400
    r = await presign(reels, "video/mp4", vendor.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["public_url"].endswith(".mp4")
    assert (await presign(reels, "image/jpeg", vendor.headers)).status_code == 200
    assert (await presign(reels, "application/pdf", vendor.headers)).status_code == 400

    for file_type, extension in [
        ("application/json", ".json"),
        ("image/gif", ".gif"),
        ("application/pdf", ".pdf"),
        ("video/webm", ".webm"),
    ]:
        r = await presign(console, file_type, admin)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["public_url"].endswith(extension)
    assert (await presign(console, "text/html", admin)).status_code == 400
    assert (await presign(console, "image/png", vendor.headers)).status_code == 403


# ---------------------------------------------------------------------------
# App banners
# ---------------------------------------------------------------------------


@pytest.fixture
async def banner_ids():
    """Banners created during a test, deleted afterwards."""
    ids: list[str] = []
    yield ids

    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.content import AppBanner

    async with SessionLocal() as s:
        await s.execute(delete(AppBanner).where(AppBanner.id.in_([uuid.UUID(i) for i in ids])))
        await s.commit()


async def _banner(client, admin, banner_ids, **fields):
    r = await client.post(
        f"{V1}/admin/banners",
        json={"title": "Weekend deals", "media_url": "https://cdn.example.com/b.png", **fields},
        headers=admin,
    )
    if r.status_code == 201:
        banner_ids.append(r.json()["data"]["id"])
    return r


async def test_banners_show_in_the_app_by_placement_and_order(
    client, admin, banner_ids, vendor
):
    placement = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    lottie = await _banner(
        client,
        admin,
        banner_ids,
        media_url="https://cdn.example.com/anim.json",
        placement=placement,
        sort_order=2,
        action_type="RESTAURANT",
        action_value=str(vendor.restaurant.id),
    )
    assert lottie.status_code == 201, lottie.text
    assert lottie.json()["data"]["media_type"] == "LOTTIE"
    assert lottie.json()["data"]["status"] == "LIVE"
    gif = await _banner(
        client, admin, banner_ids, media_url="https://cdn.example.com/a.GIF", placement=placement,
        sort_order=1,
    )
    assert gif.json()["data"]["media_type"] == "GIF"

    r = await client.get(f"{V1}/banners", params={"placement": placement})
    assert r.status_code == 200, r.text
    assert [b["media_type"] for b in r.json()["data"]] == ["GIF", "LOTTIE"]
    assert r.json()["data"][1]["action_value"] == str(vendor.restaurant.id)

    # Taken down: gone from the app, still in the console.
    r = await client.patch(
        f"{V1}/admin/banners/{gif.json()['data']['id']}", json={"is_active": False}, headers=admin
    )
    assert r.json()["data"]["status"] == "INACTIVE"
    r = await client.get(f"{V1}/banners", params={"placement": placement})
    assert [b["media_type"] for b in r.json()["data"]] == ["LOTTIE"]


async def test_home_banners_ride_along_with_the_home_feed(client, admin, banner_ids):
    r = await _banner(client, admin, banner_ids, placement="HOME")
    assert r.status_code == 201, r.text
    feed = await client.get(f"{V1}/home/feed")
    assert r.json()["data"]["id"] in [b["id"] for b in feed.json()["data"]["banners"]]


async def test_a_scheduled_banner_waits_for_its_window(client, admin, banner_ids):
    placement = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    start = datetime.now(UTC) + timedelta(days=1)
    r = await _banner(
        client, admin, banner_ids, placement=placement, starts_at=start.isoformat()
    )
    assert r.json()["data"]["status"] == "SCHEDULED"
    assert (await client.get(f"{V1}/banners", params={"placement": placement})).json()[
        "data"
    ] == []

    past = datetime.now(UTC) - timedelta(days=2)
    r = await client.patch(
        f"{V1}/admin/banners/{r.json()['data']['id']}",
        json={"starts_at": past.isoformat(), "ends_at": (past + timedelta(days=1)).isoformat()},
        headers=admin,
    )
    assert r.json()["data"]["status"] == "EXPIRED"

    expired = await client.get(
        f"{V1}/admin/banners", params={"status": "EXPIRED", "placement": placement}, headers=admin
    )
    assert len(expired.json()["data"]) == 1


async def test_banner_actions_are_checked(client, admin, banner_ids):
    r = await _banner(
        client, admin, banner_ids, action_type="URL", action_value="javascript:alert(1)"
    )
    assert r.status_code == 400, r.text
    r = await _banner(
        client, admin, banner_ids, action_type="RESTAURANT", action_value=str(uuid.uuid4())
    )
    assert r.status_code == 404, r.text
    r = await _banner(client, admin, banner_ids, action_type="CATEGORY")
    assert r.status_code == 400, r.text
    now = datetime.now(UTC)
    r = await _banner(
        client,
        admin,
        banner_ids,
        starts_at=now.isoformat(),
        ends_at=(now - timedelta(hours=1)).isoformat(),
    )
    assert r.status_code == 400, r.text
    r = await _banner(
        client, admin, banner_ids, action_type="URL", action_value="https://cheeringshop.online"
    )
    assert r.status_code == 201, r.text

    r = await client.delete(f"{V1}/admin/banners/{r.json()['data']['id']}", headers=admin)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Discovery radius
# ---------------------------------------------------------------------------


async def test_a_restaurant_within_delivery_range_is_listed(client, kitchen):
    """~8 km from the kitchen: deliverable (the limit is 15 km), and so it
    must be listed. The old 5 km default hid it."""
    r = await client.get(
        f"{V1}/restaurants", params={"lat": 23.8656, "lng": 90.4064, "limit": 100}
    )
    card = next(
        (c for c in r.json()["data"] if c["id"] == str(kitchen.restaurant.id)), None
    )
    assert card is not None, "a restaurant 8 km away was hidden from the list"
    assert 7.0 < card["distance_km"] < 9.0
