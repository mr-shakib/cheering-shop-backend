"""Reels — short restaurant videos in the customer app [EXTENDED].

A vendor posts reels for their own restaurant; an administrator can post for
any restaurant, and hide a reel from the feed without deleting it (the vendor
still sees it, with the reason). The feed shows reels of restaurants
customers can find at all — the same visibility rule as discovery — newest
first, each with the restaurant card the overlay and the View button need.

The video goes straight from the uploading client to R2 (`POST
/vendor/reels/uploads`, `POST /admin/uploads/presigned-url`); the server
never touches the bytes, so `duration_seconds` is whatever the client reports.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major
from app.models.content import Reel
from app.models.menu import MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.content import ManagedReelOut
from app.schemas.customer import ReelDish, ReelOut
from app.schemas.requests import AdminReelCreateRequest, ReelCreateRequest, ReelUpdateRequest
from app.services import platform_settings

log = structlog.get_logger()

_STATUSES = {"LIVE", "HIDDEN", "ALL"}


async def _dishes(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, MenuItem]:
    if not ids:
        return {}
    rows = await db.scalars(select(MenuItem).where(MenuItem.id.in_(ids)))
    return {item.id: item for item in rows.all()}


async def _check_dish(
    db: AsyncSession, restaurant_id: uuid.UUID, menu_item_id: uuid.UUID | None
) -> None:
    if menu_item_id is None:
        return
    item = await db.get(MenuItem, menu_item_id)
    if item is None or item.restaurant_id != restaurant_id or item.deleted_at is not None:
        raise ValidationError("menu_item_id must be a dish on this restaurant's menu")


async def _render(db: AsyncSession, reels: list[Reel]) -> list[ManagedReelOut]:
    if not reels:
        return []
    rows = await db.execute(
        select(Restaurant.id, Restaurant.name).where(
            Restaurant.id.in_({r.restaurant_id for r in reels})
        )
    )
    names: dict[uuid.UUID, str] = {rid: name for rid, name in rows.all()}
    dishes = await _dishes(db, {r.menu_item_id for r in reels if r.menu_item_id})
    return [
        ManagedReelOut(
            id=str(r.id),
            restaurant_id=str(r.restaurant_id),
            restaurant_name=names.get(r.restaurant_id, ""),
            video_url=r.video_url,
            thumbnail_url=r.thumbnail_url,
            caption=r.caption,
            duration_seconds=r.duration_seconds,
            menu_item_id=str(r.menu_item_id) if r.menu_item_id else None,
            menu_item_name=dishes[r.menu_item_id].name if r.menu_item_id in dishes else None,
            is_hidden=r.is_hidden,
            hidden_reason=r.hidden_reason,
            uploaded_by=str(r.uploaded_by) if r.uploaded_by else None,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in reels
    ]


async def _page(
    db: AsyncSession, conditions: list[ColumnElement[bool]], limit: int, offset: int
) -> tuple[list[ManagedReelOut], int]:
    total = await db.scalar(select(func.count()).select_from(Reel).where(*conditions))
    reels = (
        await db.scalars(
            select(Reel)
            .where(*conditions)
            .order_by(Reel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return await _render(db, list(reels)), int(total or 0)


async def create(
    db: AsyncSession, restaurant: Restaurant, uploader: User, body: ReelCreateRequest
) -> ManagedReelOut:
    await _check_dish(db, restaurant.id, body.menu_item_id)
    reel = Reel(
        restaurant_id=restaurant.id,
        video_url=body.video_url.strip(),
        thumbnail_url=body.thumbnail_url,
        caption=body.caption.strip() if body.caption else None,
        duration_seconds=body.duration_seconds,
        menu_item_id=body.menu_item_id,
        uploaded_by=uploader.id,
    )
    db.add(reel)
    await db.flush()
    await db.refresh(reel)
    log.info("reel_created", reel_id=str(reel.id), restaurant_id=str(restaurant.id))
    [out] = await _render(db, [reel])
    return out


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


async def list_for_restaurant(
    db: AsyncSession, restaurant: Restaurant, limit: int, offset: int
) -> tuple[list[ManagedReelOut], int]:
    """The vendor's own reels, hidden ones included, so they can see why."""
    return await _page(db, [Reel.restaurant_id == restaurant.id], limit, offset)


async def delete_own(db: AsyncSession, restaurant: Restaurant, reel_id: uuid.UUID) -> None:
    reel = await db.get(Reel, reel_id)
    # Another vendor's reel is a 404, not a 403: its existence is not theirs to learn.
    if reel is None or reel.restaurant_id != restaurant.id:
        raise NotFoundError("Reel not found")
    await db.delete(reel)
    await db.flush()
    log.info("reel_deleted", reel_id=str(reel_id), by="vendor")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


async def admin_create(
    db: AsyncSession, admin: User, body: AdminReelCreateRequest
) -> ManagedReelOut:
    restaurant = await db.get(Restaurant, body.restaurant_id)
    if restaurant is None:
        raise NotFoundError("No restaurant with that id")
    return await create(db, restaurant, admin, body)


async def admin_list(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    restaurant_id: uuid.UUID | None = None,
    status: str = "ALL",
) -> tuple[list[ManagedReelOut], int]:
    wanted = (status or "ALL").strip().upper()
    if wanted not in _STATUSES:
        raise ValidationError("status must be LIVE, HIDDEN or ALL")
    conditions: list[ColumnElement[bool]] = []
    if wanted != "ALL":
        conditions.append(Reel.is_hidden.is_(wanted == "HIDDEN"))
    if restaurant_id is not None:
        conditions.append(Reel.restaurant_id == restaurant_id)
    return await _page(db, conditions, limit, offset)


async def _get(db: AsyncSession, reel_id: uuid.UUID) -> Reel:
    reel = await db.get(Reel, reel_id)
    if reel is None:
        raise NotFoundError("Reel not found")
    return reel


async def admin_update(
    db: AsyncSession, reel_id: uuid.UUID, body: ReelUpdateRequest
) -> ManagedReelOut:
    reel = await _get(db, reel_id)
    fields = body.model_dump(exclude_unset=True)
    if "caption" in fields:
        reel.caption = fields["caption"].strip() if fields["caption"] else None
    if "thumbnail_url" in fields:
        reel.thumbnail_url = fields["thumbnail_url"]
    if "menu_item_id" in fields:
        await _check_dish(db, reel.restaurant_id, fields["menu_item_id"])
        reel.menu_item_id = fields["menu_item_id"]
    if fields.get("is_hidden") is not None:
        reel.is_hidden = fields["is_hidden"]
        # A reason only means something while the reel is hidden.
        reel.hidden_reason = fields.get("hidden_reason") if reel.is_hidden else None
    elif "hidden_reason" in fields and reel.is_hidden:
        reel.hidden_reason = fields["hidden_reason"]
    await db.flush()
    await db.refresh(reel)
    log.info("reel_updated", reel_id=str(reel.id), fields=sorted(fields))
    [out] = await _render(db, [reel])
    return out


async def admin_delete(db: AsyncSession, reel_id: uuid.UUID) -> None:
    reel = await _get(db, reel_id)
    await db.delete(reel)
    await db.flush()
    log.info("reel_deleted", reel_id=str(reel_id), by="admin")


# ---------------------------------------------------------------------------
# Customer feed
# ---------------------------------------------------------------------------


async def feed(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    lat: float | None = None,
    lng: float | None = None,
    restaurant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> tuple[list[ReelOut], int]:
    """Newest first. Coordinates only fill in each card's distance and
    delivery fee; they do not filter, so the feed is never empty for want of
    a nearby restaurant with a video."""
    from app.services.customer.discovery import (
        _VISIBLE,
        _distance_expr,
        _favorite_ids,
        _to_card,
    )

    conditions = [Reel.is_hidden.is_(False), _VISIBLE]
    if restaurant_id is not None:
        conditions.append(Reel.restaurant_id == restaurant_id)

    total = await db.scalar(
        select(func.count())
        .select_from(Reel)
        .join(Restaurant, Restaurant.id == Reel.restaurant_id)
        .where(*conditions)
    )
    rows = (
        await db.execute(
            select(Reel, Restaurant, _distance_expr(lat, lng))
            .join(Restaurant, Restaurant.id == Reel.restaurant_id)
            .where(*conditions)
            .order_by(Reel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    fees = await platform_settings.delivery_fees(db)
    favorites = await _favorite_ids(db, user_id)
    dishes = await _dishes(db, {reel.menu_item_id for reel, _, _ in rows if reel.menu_item_id})
    out = []
    for reel, restaurant, distance_m in rows:
        dish = dishes.get(reel.menu_item_id) if reel.menu_item_id else None
        out.append(
            ReelOut(
                id=str(reel.id),
                video_url=reel.video_url,
                thumbnail_url=reel.thumbnail_url,
                caption=reel.caption,
                duration_seconds=reel.duration_seconds,
                restaurant=_to_card((restaurant, distance_m), fees, favorites),
                menu_item=ReelDish(
                    id=str(dish.id), name=dish.name, price=to_major(dish.base_price)
                )
                if dish is not None and dish.deleted_at is None
                else None,
                created_at=reel.created_at,
            )
        )
    return out, int(total or 0)


__all__ = [
    "admin_create",
    "admin_delete",
    "admin_list",
    "admin_update",
    "create",
    "delete_own",
    "feed",
    "list_for_restaurant",
]
