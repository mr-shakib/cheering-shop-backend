"""Addresses, favorites and delivery slots — spec #24–25, #34.

Small, self-contained CRUD. The one piece of real logic is `set_default`, which
has to demote the previous default in the same transaction — two defaults is a
state the checkout screen cannot render, and the database has no partial unique
index to prevent it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.models.address import Address
from app.models.restaurant import Favorite, Restaurant
from app.schemas.customer import (
    AddressOut,
    DeliverySlot,
    FavoriteToggled,
    RestaurantCard,
    ScheduleDay,
    ScheduleOptions,
)
from app.schemas.requests import AddressCreateRequest


def _as_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


def _to_out(address: Address) -> AddressOut:
    return AddressOut(
        id=str(address.id),
        type=str(address.type),
        label=address.label,
        street_address=address.street_address,
        apartment=address.apartment,
        landmark=address.landmark,
        city=address.city,
        postal_code=address.postal_code,
        contact_phone=address.contact_phone,
        latitude=address.latitude,
        longitude=address.longitude,
        is_default=address.is_default,
    )


async def list_addresses(db: AsyncSession, user_id: uuid.UUID) -> list[AddressOut]:
    """Default first — it is the one the checkout screen preselects."""
    rows = await db.scalars(
        select(Address)
        .where(Address.user_id == user_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return [_to_out(a) for a in rows.all()]


async def _demote_others(db: AsyncSession, user_id: uuid.UUID, keep: uuid.UUID | None) -> None:
    stmt = update(Address).where(Address.user_id == user_id, Address.is_default.is_(True))
    if keep is not None:
        stmt = stmt.where(Address.id != keep)
    await db.execute(stmt.values(is_default=False))


async def create_address(
    db: AsyncSession, user_id: uuid.UUID, body: AddressCreateRequest
) -> AddressOut:
    """The first address a customer saves becomes their default automatically.

    Otherwise checkout opens with nothing selected on the very first order,
    which is the worst possible moment to make someone hunt through a picker.
    """
    existing = await db.scalars(select(Address.id).where(Address.user_id == user_id))
    is_first = not existing.first()
    make_default = body.is_default or is_first

    address = Address(
        user_id=user_id,
        type=body.type,
        street_address=body.street_address,
        apartment=body.apartment,
        landmark=body.landmark,
        city=body.city,
        postal_code=body.postal_code,
        contact_phone=body.contact_phone,
        latitude=body.latitude,
        longitude=body.longitude,
        is_default=make_default,
    )
    db.add(address)
    await db.flush()
    if make_default:
        await _demote_others(db, user_id, address.id)
    return _to_out(address)


async def _owned(db: AsyncSession, user_id: uuid.UUID, address_id: str) -> Address:
    address = await db.scalar(
        select(Address).where(
            Address.id == _as_uuid(address_id, "address_id"), Address.user_id == user_id
        )
    )
    if address is None:
        raise NotFoundError("Address not found")
    return address


async def replace_address(
    db: AsyncSession, user_id: uuid.UUID, address_id: str, body: AddressCreateRequest
) -> AddressOut:
    address = await _owned(db, user_id, address_id)
    address.type = body.type
    address.street_address = body.street_address
    address.apartment = body.apartment
    address.landmark = body.landmark
    address.city = body.city
    address.postal_code = body.postal_code
    address.contact_phone = body.contact_phone
    address.latitude = body.latitude
    address.longitude = body.longitude
    if body.is_default:
        address.is_default = True
        await _demote_others(db, user_id, address.id)
    await db.flush()
    return _to_out(address)


async def delete_address(db: AsyncSession, user_id: uuid.UUID, address_id: str) -> None:
    """Deleting the default promotes the next most recent one.

    Leaving a customer with addresses but no default would silently break the
    checkout preselect — and `orders.delivery_address_id` is ON DELETE SET NULL
    with a text snapshot alongside, so past orders keep their address either
    way.
    """
    address = await _owned(db, user_id, address_id)
    was_default = address.is_default
    await db.execute(delete(Address).where(Address.id == address.id))
    if was_default:
        replacement = await db.scalar(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.created_at.desc())
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
    await db.flush()


async def set_default(db: AsyncSession, user_id: uuid.UUID, address_id: str) -> AddressOut:
    address = await _owned(db, user_id, address_id)
    address.is_default = True
    await _demote_others(db, user_id, address.id)
    await db.flush()
    return _to_out(address)


# --- Favorites -------------------------------------------------------------


async def list_favorites(db: AsyncSession, user_id: uuid.UUID) -> list[RestaurantCard]:
    """My Favorites. Reuses the discovery card so the row renders identically
    to the same restaurant seen anywhere else."""
    from app.services.customer.discovery import _to_card

    rows = await db.execute(
        select(Restaurant)
        .join(Favorite, Favorite.restaurant_id == Restaurant.id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
    )
    return [_to_card((r, None), {r.id}) for r in rows.scalars().all()]


async def toggle_favorite(
    db: AsyncSession, user_id: uuid.UUID, restaurant_id: str
) -> FavoriteToggled:
    """One endpoint for both directions — the heart is a toggle, and two
    endpoints would let the client's idea of the state drift from ours."""
    rid = _as_uuid(restaurant_id, "restaurant_id")
    restaurant = await db.get(Restaurant, rid)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")

    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user_id, Favorite.restaurant_id == rid)
    )
    if existing is not None:
        await db.execute(
            delete(Favorite).where(
                Favorite.user_id == user_id, Favorite.restaurant_id == rid
            )
        )
        await db.flush()
        return FavoriteToggled(restaurant_id=restaurant_id, is_favorite=False)

    db.add(Favorite(user_id=user_id, restaurant_id=rid))
    await db.flush()
    return FavoriteToggled(restaurant_id=restaurant_id, is_favorite=True)


# --- Scheduled delivery ----------------------------------------------------

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _slot_label(start: datetime, end: datetime) -> str:
    """"2:40 PM - 2:50 PM" — the format on the Schedule Order sheet."""

    def fmt(dt: datetime) -> str:
        return dt.strftime("%-I:%M %p")

    return f"{fmt(start)} - {fmt(end)}"


async def schedule_options(db: AsyncSession, restaurant_id: str) -> ScheduleOptions:
    """The Schedule Order sheet, generated rather than stored.

    Slots are derived from the restaurant's business hours and the configured
    slot width, so there is no table to keep in sync with opening times. Slots
    inside the lead time are returned but marked unavailable — a picker that
    silently omits times looks broken, and greying them explains itself.

    Capacity is deliberately NOT modelled. Every open slot is bookable, because
    nothing anywhere tracks kitchen throughput; inventing a cap here would be a
    number with no basis. When throughput data exists, this is where it goes.
    """
    rid = _as_uuid(restaurant_id, "restaurant_id")
    restaurant = await db.get(Restaurant, rid)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")

    hours = restaurant.business_hours or {}
    now = datetime.now(UTC)
    earliest = now + timedelta(minutes=settings.SCHEDULE_MIN_LEAD_MINUTES)
    width = timedelta(minutes=settings.SCHEDULE_SLOT_MINUTES)

    days: list[ScheduleDay] = []
    for offset in range(settings.SCHEDULE_MAX_DAYS_AHEAD):
        day = now.date() + timedelta(days=offset)
        config = hours.get(_WEEKDAYS[day.weekday()]) or {}
        label = {0: "Today", 1: "Tomorrow"}.get(offset, day.strftime("%a"))

        slots: list[DeliverySlot] = []
        if config.get("is_open", True):
            opens = _parse_time(config.get("opens_at"), default="09:00")
            closes = _parse_time(config.get("closes_at"), default="23:00")
            cursor = datetime.combine(day, opens, tzinfo=UTC)
            end_of_day = datetime.combine(day, closes, tzinfo=UTC)
            while cursor + width <= end_of_day:
                slot_end = cursor + width
                slots.append(
                    DeliverySlot(
                        starts_at=cursor.isoformat(),
                        ends_at=slot_end.isoformat(),
                        label=_slot_label(cursor, slot_end),
                        is_available=cursor >= earliest,
                    )
                )
                cursor = slot_end
        days.append(ScheduleDay(date=day.isoformat(), label=label, slots=slots))

    return ScheduleOptions(
        restaurant_id=restaurant_id,
        slot_minutes=settings.SCHEDULE_SLOT_MINUTES,
        min_lead_minutes=settings.SCHEDULE_MIN_LEAD_MINUTES,
        days=days,
    )


def _parse_time(value: str | None, *, default: str):
    """"HH:MM" from business_hours, falling back when a vendor never set them."""
    from datetime import time

    raw = value or default
    try:
        hour, minute = (int(part) for part in raw.split(":")[:2])
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        hour, minute = (int(part) for part in default.split(":"))
        return time(hour=hour, minute=minute)


__all__ = [
    "create_address",
    "delete_address",
    "list_addresses",
    "list_favorites",
    "replace_address",
    "schedule_options",
    "set_default",
    "toggle_favorite",
]
