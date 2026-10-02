"""Business hours: when a store's own schedule says it is open, and the job
that opens and closes it accordingly.

**Hours are wall-clock times in `settings.BUSINESS_TIMEZONE`.** A vendor who
types 12:00–22:00 means noon in Dhaka. The server runs in UTC, and reading
those strings as UTC is what kept stores shut through lunch and open until
4 AM; everything here converts through `core.clock` first.

**The hours drive `status`; the vendor's toggle still wins until the next
change.** Every minute the worker asks each restaurant with hours whether its
schedule says open, and compares that with `scheduled_open`, what the schedule
said last time. Only when the two differ, at an opening or closing time, does
it set `status`. A vendor who closes early for the day therefore stays closed
until tomorrow's opening time, and one who stays open late stays open until
they close or the next closing time comes round. Comparing with the last
answer rather than the clock also means a minute the worker missed (a deploy,
a restart) is caught up on the next.

Everything downstream keeps reading `status`, so discovery, the cart and
checkout need no idea that hours exist.

A restaurant with no hours saved (`business_hours` NULL) is left alone: its
toggle is the only switch, as before.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import LOCAL_TZ
from app.models.enums import RestaurantStatus
from app.models.restaurant import Restaurant

log = structlog.get_logger()

# date.weekday() order: Monday is 0.
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _clock_time(value: str | None) -> time | None:
    try:
        hour, minute = (int(part) for part in (value or "").split(":")[:2])
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        return None


def spans_starting(hours: dict | None, day: date) -> list[tuple[datetime, datetime]]:
    """The open period that begins on `day`, as aware local datetimes.

    `closes_at` at or before `opens_at` runs past midnight (18:00–02:00, or
    10:00–00:00 for "until midnight"), so the end moves to the next day.
    """
    entry = (hours or {}).get(DAY_KEYS[day.weekday()]) or {}
    opens, closes = _clock_time(entry.get("opens_at")), _clock_time(entry.get("closes_at"))
    if not entry.get("is_open") or opens is None or closes is None:
        return []
    start = datetime.combine(day, opens, tzinfo=LOCAL_TZ)
    end = datetime.combine(day, closes, tzinfo=LOCAL_TZ)
    if end <= start:
        end += timedelta(days=1)
    return [(start, end)]


def is_open_at(hours: dict | None, at: datetime) -> bool:
    """Whether the schedule says open at the instant `at`.

    Yesterday's period is checked too, because one that runs past midnight is
    still open in the small hours of today.
    """
    local = at.astimezone(LOCAL_TZ)
    today = local.date()
    for day in (today - timedelta(days=1), today):
        for start, end in spans_starting(hours, day):
            if start <= local < end:
                return True
    return False


def next_change(hours: dict | None, at: datetime) -> datetime | None:
    """When the schedule next flips between open and closed, after `at`. None
    when it never does (closed every day, or open without a break)."""
    local = at.astimezone(LOCAL_TZ)
    now_open = is_open_at(hours, local)
    candidates = sorted(
        moment
        for offset in range(-1, 8)
        for span in spans_starting(hours, local.date() + timedelta(days=offset))
        for moment in span
        if moment > local
    )
    for moment in candidates:
        if is_open_at(hours, moment) != now_open:
            return moment
    return None


def apply(restaurant: Restaurant, at: datetime) -> bool:
    """Set the store to what its hours say right now, whatever its toggle
    says. For when the hours themselves were just saved: the vendor has told
    us their schedule, and a store that should be open now opens now rather
    than at tomorrow's opening time. Returns whether `status` changed."""
    if not restaurant.business_hours:
        return False
    scheduled = is_open_at(restaurant.business_hours, at)
    wanted = RestaurantStatus.OPEN.value if scheduled else RestaurantStatus.CLOSED.value
    changed = str(restaurant.status) != wanted
    restaurant.status = wanted
    restaurant.scheduled_open = scheduled
    return changed


async def sync_all(db: AsyncSession, at: datetime) -> int:
    """The worker's minute: open or close every store whose schedule changed
    since the last pass. Returns how many stores changed.

    Each write is conditional on `scheduled_open` still holding the value this
    pass read, so a vendor saving new hours at the same moment is never
    overwritten with an answer computed from the old ones.
    """
    rows = (
        await db.execute(
            select(Restaurant.id, Restaurant.business_hours, Restaurant.scheduled_open).where(
                Restaurant.business_hours.is_not(None)
            )
        )
    ).all()
    changed = 0
    for restaurant_id, hours, last in rows:
        if not hours:
            continue
        scheduled = is_open_at(hours, at)
        if scheduled == last:
            continue
        updated = await db.scalar(
            update(Restaurant)
            .where(
                Restaurant.id == restaurant_id,
                Restaurant.scheduled_open.is_(None)
                if last is None
                else Restaurant.scheduled_open.is_(last),
            )
            .values(
                status=RestaurantStatus.OPEN.value if scheduled else RestaurantStatus.CLOSED.value,
                scheduled_open=scheduled,
            )
            .returning(Restaurant.id)
        )
        if updated is not None:
            changed += 1
            log.info(
                "store_hours_applied",
                restaurant_id=str(restaurant_id),
                status="OPEN" if scheduled else "CLOSED",
            )
    return changed


__all__ = ["DAY_KEYS", "apply", "is_open_at", "next_change", "spans_starting", "sync_all"]
