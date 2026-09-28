"""App banners — the promotional banners the apps show, managed from the admin
console [EXTENDED].

A banner is shown while it is active and inside its optional window
(`starts_at` <= now < `ends_at`), at its `placement`, lowest `sort_order`
first. The window is evaluated at read time, so a scheduled banner goes live
and an expired one disappears without anything having to run.

Media is an image, a GIF or a Lottie animation (JSON). The server never sees
the bytes: the admin uploads to R2 first and sends the public URL.
"""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.models.category import Category
from app.models.content import AppBanner
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.content import AdminBannerOut, BannerOut
from app.schemas.requests import BannerCreateRequest, BannerUpdateRequest
from app.services import category_service

log = structlog.get_logger()

_MEDIA_BY_EXTENSION = {"gif": "GIF", "json": "LOTTIE", "lottie": "LOTTIE"}
_STATUSES = {"LIVE", "SCHEDULED", "EXPIRED", "INACTIVE", "ALL"}


def infer_media_type(url: str) -> str:
    """GIF and Lottie by extension; anything else renders as an image."""
    name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return _MEDIA_BY_EXTENSION.get(extension, "IMAGE")


def _live_clause(now: datetime) -> ColumnElement[bool]:
    return and_(
        AppBanner.is_active.is_(True),
        or_(AppBanner.starts_at.is_(None), AppBanner.starts_at <= now),
        or_(AppBanner.ends_at.is_(None), AppBanner.ends_at > now),
    )


def _status_clause(status: str, now: datetime) -> ColumnElement[bool] | None:
    not_ended = or_(AppBanner.ends_at.is_(None), AppBanner.ends_at > now)
    active = AppBanner.is_active.is_(True)
    return {
        "LIVE": _live_clause(now),
        "SCHEDULED": and_(active, AppBanner.starts_at > now, not_ended),
        "EXPIRED": and_(active, AppBanner.ends_at <= now),
        "INACTIVE": AppBanner.is_active.is_(False),
        "ALL": None,
    }[status]


def _status_of(banner: AppBanner, now: datetime) -> str:
    if not banner.is_active:
        return "INACTIVE"
    if banner.ends_at is not None and banner.ends_at <= now:
        return "EXPIRED"
    if banner.starts_at is not None and banner.starts_at > now:
        return "SCHEDULED"
    return "LIVE"


def _to_out(banner: AppBanner) -> BannerOut:
    return BannerOut(
        id=str(banner.id),
        title=banner.title,
        media_url=banner.media_url,
        media_type=banner.media_type,
        placement=banner.placement,
        action_type=banner.action_type,
        action_value=banner.action_value,
        sort_order=banner.sort_order,
    )


def _to_admin(banner: AppBanner, now: datetime | None = None) -> AdminBannerOut:
    return AdminBannerOut(
        **_to_out(banner).model_dump(),
        is_active=banner.is_active,
        starts_at=banner.starts_at,
        ends_at=banner.ends_at,
        status=_status_of(banner, now or datetime.now(UTC)),
        created_by=str(banner.created_by) if banner.created_by else None,
        created_at=banner.created_at,
        updated_at=banner.updated_at,
    )


async def _checked_action(db: AsyncSession, action_type: str, value: str | None) -> str | None:
    """The stored action_value, validated against what the tap will open.

    Checked now rather than left to the app: a banner that opens a deleted
    restaurant is a dead tap on the most prominent spot in the app.
    """
    if action_type == "NONE":
        return None
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"action_value is required when action_type is {action_type}")
    if action_type == "RESTAURANT":
        try:
            restaurant_id = uuid.UUID(value)
        except ValueError as exc:
            raise ValidationError("action_value must be a restaurant id") from exc
        if await db.get(Restaurant, restaurant_id) is None:
            raise NotFoundError("No restaurant with that id")
        return str(restaurant_id)
    if action_type == "CATEGORY":
        category = await db.scalar(select(Category).where(category_service.by_slug(value)))
        if category is None:
            raise NotFoundError(f"No category with the slug '{value}'")
        return category.slug
    # URL. Only web links: a `javascript:` or `intent:` value would run in
    # whatever web view the app opens it with.
    if urlsplit(value).scheme not in {"http", "https"}:
        raise ValidationError("action_value must be an http(s) URL")
    return value


def _check_window(banner: AppBanner) -> None:
    # ck_app_banners_window would refuse it anyway, as a 500.
    if banner.starts_at and banner.ends_at and banner.ends_at <= banner.starts_at:
        raise ValidationError("ends_at must be after starts_at")


# ---------------------------------------------------------------------------
# The apps
# ---------------------------------------------------------------------------


async def live(db: AsyncSession, placement: str = "HOME") -> list[BannerOut]:
    now = datetime.now(UTC)
    rows = await db.scalars(
        select(AppBanner)
        .where(AppBanner.placement == placement.upper(), _live_clause(now))
        .order_by(AppBanner.sort_order, AppBanner.created_at.desc())
    )
    return [_to_out(b) for b in rows.all()]


# ---------------------------------------------------------------------------
# Admin console
# ---------------------------------------------------------------------------


async def admin_list(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    placement: str | None = None,
    status: str = "ALL",
) -> tuple[list[AdminBannerOut], int]:
    wanted = (status or "ALL").strip().upper()
    if wanted not in _STATUSES:
        raise ValidationError(f"status must be one of {', '.join(sorted(_STATUSES))}")
    now = datetime.now(UTC)
    conditions: list[ColumnElement[bool]] = []
    if (clause := _status_clause(wanted, now)) is not None:
        conditions.append(clause)
    if placement:
        conditions.append(AppBanner.placement == placement.strip().upper())

    total = await db.scalar(select(func.count()).select_from(AppBanner).where(*conditions))
    rows = await db.scalars(
        select(AppBanner)
        .where(*conditions)
        .order_by(AppBanner.placement, AppBanner.sort_order, AppBanner.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_to_admin(b, now) for b in rows.all()], int(total or 0)


async def _get(db: AsyncSession, banner_id: uuid.UUID) -> AppBanner:
    banner = await db.get(AppBanner, banner_id)
    if banner is None:
        raise NotFoundError("No banner with that id")
    return banner


async def get(db: AsyncSession, banner_id: uuid.UUID) -> AdminBannerOut:
    return _to_admin(await _get(db, banner_id))


async def create(db: AsyncSession, admin: User, body: BannerCreateRequest) -> AdminBannerOut:
    banner = AppBanner(
        title=body.title.strip(),
        media_url=body.media_url.strip(),
        media_type=body.media_type or infer_media_type(body.media_url),
        placement=body.placement,
        action_type=body.action_type,
        action_value=await _checked_action(db, body.action_type, body.action_value),
        sort_order=body.sort_order,
        is_active=body.is_active,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        created_by=admin.id,
    )
    _check_window(banner)
    db.add(banner)
    await db.flush()
    await db.refresh(banner)
    log.info("banner_created", banner_id=str(banner.id), placement=banner.placement)
    return _to_admin(banner)


async def update(
    db: AsyncSession, banner_id: uuid.UUID, body: BannerUpdateRequest
) -> AdminBannerOut:
    banner = await _get(db, banner_id)
    fields = body.model_dump(exclude_unset=True)

    for name in ("title", "media_url", "placement", "sort_order", "is_active"):
        if fields.get(name) is not None:
            value = fields[name]
            setattr(banner, name, value.strip() if isinstance(value, str) else value)
    for name in ("starts_at", "ends_at"):
        if name in fields:
            setattr(banner, name, fields[name])
    if fields.get("media_type") is not None:
        banner.media_type = fields["media_type"]
    elif fields.get("media_url") is not None:
        # A new file without a declared type: infer again rather than keep a
        # type that described the old file.
        banner.media_type = infer_media_type(banner.media_url)
    if "action_type" in fields or "action_value" in fields:
        action_type = fields.get("action_type") or banner.action_type
        value = fields.get("action_value", banner.action_value)
        banner.action_value = await _checked_action(db, action_type, value)
        banner.action_type = action_type
    _check_window(banner)

    await db.flush()
    await db.refresh(banner)
    log.info("banner_updated", banner_id=str(banner.id), fields=sorted(fields))
    return _to_admin(banner)


async def delete(db: AsyncSession, banner_id: uuid.UUID) -> None:
    banner = await _get(db, banner_id)
    await db.delete(banner)
    await db.flush()
    log.info("banner_deleted", banner_id=str(banner_id))


__all__ = ["admin_list", "create", "delete", "get", "infer_media_type", "live", "update"]
