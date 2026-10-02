"""Business hours open and close the store, on the Dhaka clock.

The bug these pin down: hours were saved but nothing read them, so a store
with 12:00–22:00 hours sat CLOSED all day. And anything that did read a time
read it as UTC, six hours behind Dhaka.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import LOCAL_TZ
from app.services import business_hours

V1 = "/api/v1"
DAYS = business_hours.DAY_KEYS


def _week(opens="12:00", closes="22:00", **overrides) -> dict:
    week = {d: {"is_open": True, "opens_at": opens, "closes_at": closes} for d in DAYS}
    week.update(overrides)
    return week


def dhaka(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=LOCAL_TZ)


# 2026-10-05 is a Monday.
MON = (2026, 10, 5)


# ---------------------------------------------------------------------------
# The schedule itself — no database
# ---------------------------------------------------------------------------


def test_hours_are_read_on_the_dhaka_clock_not_utc():
    """12:00–22:00 in Dhaka is 06:00–16:00 UTC. Read as UTC, the store would
    open at 6 PM local and stay open until 4 AM."""
    hours = _week()
    assert business_hours.is_open_at(hours, dhaka(*MON, 12, 0))
    assert business_hours.is_open_at(hours, dhaka(*MON, 21, 59))
    assert not business_hours.is_open_at(hours, dhaka(*MON, 22, 0))
    assert not business_hours.is_open_at(hours, dhaka(*MON, 11, 59))
    # The same instants given in UTC answer the same.
    assert business_hours.is_open_at(hours, datetime(2026, 10, 5, 6, 30, tzinfo=UTC))
    assert not business_hours.is_open_at(hours, datetime(2026, 10, 5, 17, 0, tzinfo=UTC))


def test_hours_past_midnight_carry_into_the_next_morning():
    hours = _week(opens="18:00", closes="02:00")
    assert business_hours.is_open_at(hours, dhaka(*MON, 23, 30))
    assert business_hours.is_open_at(hours, dhaka(2026, 10, 6, 1, 59))
    assert not business_hours.is_open_at(hours, dhaka(2026, 10, 6, 2, 0))
    # "Until midnight" is 00:00, not a zero-length day.
    hours = _week(opens="10:00", closes="00:00")
    assert business_hours.is_open_at(hours, dhaka(*MON, 23, 59))
    assert not business_hours.is_open_at(hours, dhaka(2026, 10, 6, 0, 0))


def test_a_closed_day_is_closed_but_last_nights_hours_still_finish():
    hours = _week(opens="18:00", closes="02:00", tue={"is_open": False})
    # Monday night runs into Tuesday morning even though Tuesday is closed.
    assert business_hours.is_open_at(hours, dhaka(2026, 10, 6, 1, 0))
    assert not business_hours.is_open_at(hours, dhaka(2026, 10, 6, 19, 0))


def test_next_change_finds_the_next_opening_or_closing():
    hours = _week(sat={"is_open": False}, sun={"is_open": False})
    assert business_hours.next_change(hours, dhaka(*MON, 9, 0)) == dhaka(*MON, 12, 0)
    assert business_hours.next_change(hours, dhaka(*MON, 13, 0)) == dhaka(*MON, 22, 0)
    # Friday night's closing skips the weekend to Monday's opening.
    friday_night = dhaka(2026, 10, 9, 23, 0)
    assert business_hours.next_change(hours, friday_night) == dhaka(2026, 10, 12, 12, 0)
    closed_all_week = {d: {"is_open": False} for d in DAYS}
    assert business_hours.next_change(closed_all_week, dhaka(*MON, 9, 0)) is None


# ---------------------------------------------------------------------------
# The worker's minute
# ---------------------------------------------------------------------------


async def _restaurant(restaurant_id):
    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    async with SessionLocal() as s:
        return await s.get(Restaurant, restaurant_id)


async def _sync(at: datetime) -> None:
    from app.core.database import SessionLocal

    async with SessionLocal() as s:
        await business_hours.sync_all(s, at)
        await s.commit()


async def _set(restaurant_id, **values) -> None:
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models.restaurant import Restaurant

    async with SessionLocal() as s:
        await s.execute(update(Restaurant).where(Restaurant.id == restaurant_id).values(**values))
        await s.commit()


@pytest.mark.usefixtures("db_available")
async def test_the_worker_opens_and_closes_the_store_at_its_hours(vendor):
    """Hours set but never applied (scheduled_open NULL): the first pass opens
    a store whose hours say open. This is what fixes stores already stuck
    CLOSED in production when the migration ships."""
    rid = vendor.restaurant.id
    await _set(rid, business_hours=_week(), status="CLOSED", scheduled_open=None)

    await _sync(dhaka(*MON, 12, 0))
    r = await _restaurant(rid)
    assert (str(r.status), r.scheduled_open) == ("OPEN", True)

    await _sync(dhaka(*MON, 22, 0))
    r = await _restaurant(rid)
    assert (str(r.status), r.scheduled_open) == ("CLOSED", False)


@pytest.mark.usefixtures("db_available")
async def test_the_vendors_toggle_holds_until_the_next_scheduled_change(vendor):
    rid = vendor.restaurant.id
    await _set(rid, business_hours=_week(), status="CLOSED", scheduled_open=None)
    await _sync(dhaka(*MON, 12, 0))

    # The vendor closes early at 3 PM. The schedule still says open, but it
    # has not changed, so the next minutes leave the store closed.
    await _set(rid, status="CLOSED")
    await _sync(dhaka(*MON, 15, 1))
    await _sync(dhaka(*MON, 21, 59))
    assert str((await _restaurant(rid)).status) == "CLOSED"

    # And it opens again at tomorrow's opening time.
    await _sync(dhaka(*MON, 22, 0))
    await _sync(dhaka(2026, 10, 6, 12, 0))
    assert str((await _restaurant(rid)).status) == "OPEN"

    # Staying open late works the same way, until the next closing time.
    await _sync(dhaka(2026, 10, 6, 22, 0))
    await _set(rid, status="OPEN")
    await _sync(dhaka(2026, 10, 6, 23, 0))
    assert str((await _restaurant(rid)).status) == "OPEN"


@pytest.mark.usefixtures("db_available")
async def test_a_store_without_hours_is_left_to_its_toggle(vendor):
    rid = vendor.restaurant.id
    await _set(rid, business_hours=None, status="OPEN", scheduled_open=None)
    await _sync(dhaka(*MON, 3, 0))
    assert str((await _restaurant(rid)).status) == "OPEN"


# ---------------------------------------------------------------------------
# The vendor's screens
# ---------------------------------------------------------------------------


def _around_now(minutes_before: int, minutes_after: int) -> tuple[str, str]:
    now = datetime.now(LOCAL_TZ)
    opens = (now - timedelta(minutes=minutes_before)).strftime("%H:%M")
    closes = (now + timedelta(minutes=minutes_after)).strftime("%H:%M")
    return opens, closes


@pytest.mark.usefixtures("db_available")
async def test_saving_hours_opens_the_store_right_away(client, vendor):
    """The reported bug: hours saved, store still closed. Saving hours that
    cover now opens it on the spot, without waiting for the worker."""
    assert str((await _restaurant(vendor.restaurant.id)).status) == "CLOSED"
    opens, closes = _around_now(60, 60)

    r = await client.put(
        f"{V1}/vendor/hours", json=_week(opens, closes), headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["store_status"] == "OPEN"
    assert data["is_open_by_hours"] is True
    assert data["timezone"] == "Asia/Dhaka"
    assert data["next_change_at"] is not None

    # Customers see it open: the vendor fixture is verified.
    r = await client.get(f"{V1}/restaurants/{vendor.restaurant.id}")
    assert r.json()["data"]["is_open"] is True

    # Hours that do not cover now close it.
    opens, closes = _around_now(-60, 120)
    r = await client.put(
        f"{V1}/vendor/hours", json=_week(opens, closes), headers=vendor.headers
    )
    assert r.json()["data"]["store_status"] == "CLOSED"
    assert r.json()["data"]["is_open_by_hours"] is False


@pytest.mark.usefixtures("db_available")
async def test_the_toggle_says_when_the_hours_take_over_again(client, vendor):
    opens, closes = _around_now(60, 60)
    await client.put(f"{V1}/vendor/hours", json=_week(opens, closes), headers=vendor.headers)

    r = await client.patch(
        f"{V1}/vendor/store/status", json={"status": "CLOSED"}, headers=vendor.headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "CLOSED"
    assert data["next_scheduled_change_at"] is not None
    assert "business hours will open it at" in data["message"]


# ---------------------------------------------------------------------------
# The Schedule Order sheet
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("db_available")
async def test_delivery_slots_are_on_the_dhaka_clock(client, vendor):
    """Slots used to be generated in UTC: a 12:00 opening produced a first
    slot of 6 PM Dhaka time."""
    await _set(
        vendor.restaurant.id, business_hours=_week("12:00", "13:00"), scheduled_open=None
    )
    r = await client.get(f"{V1}/restaurants/{vendor.restaurant.id}/schedule")
    assert r.status_code == 200, r.text
    days = r.json()["data"]["days"]
    assert days[0]["date"] == datetime.now(LOCAL_TZ).date().isoformat()

    tomorrow = days[1]["slots"]
    assert tomorrow[0]["label"] == "12:00 PM - 12:10 PM"
    assert tomorrow[0]["starts_at"].endswith("T12:00:00+06:00")
    assert tomorrow[-1]["label"] == "12:50 PM - 1:00 PM"
    assert len(tomorrow) == 6


@pytest.mark.usefixtures("db_available")
async def test_slots_continue_past_midnight(client, vendor):
    await _set(
        vendor.restaurant.id, business_hours=_week("23:00", "01:00"), scheduled_open=None
    )
    r = await client.get(f"{V1}/restaurants/{vendor.restaurant.id}/schedule")
    tomorrow = r.json()["data"]["days"][1]["slots"]
    assert len(tomorrow) == 12  # two hours of ten-minute slots
    assert tomorrow[-1]["label"] == "12:50 AM - 1:00 AM"
