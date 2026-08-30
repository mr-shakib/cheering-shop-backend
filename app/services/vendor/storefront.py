"""Vendor account creation and approval.

**The model: self-service signup, admin approval before going live.**

A vendor registers themselves and immediately gets a working account — they can
sign in, build their menu, upload photos. What they cannot do is take orders:
the restaurant is created with `is_verified = false`, and the discovery index is
`WHERE is_active AND is_verified`, so an unapproved storefront is invisible to
customers by construction rather than by a filter someone has to remember.

That separation matters. Making vendors wait for approval before they can even
log in means every onboarding stalls on an admin; letting them appear in search
before anyone has checked them means the first customer experience is a gamble.
"""

import re
import unicodedata
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.auth import RestaurantSummary
from app.schemas.requests import (
    BusinessHoursRequest,
    RestaurantDetails,
    RestaurantProfileUpdateRequest,
)
from app.schemas.vendor import (
    BusinessHoursOut,
    DayHoursOut,
    RestaurantProfile,
    StoreStatusResult,
)

log = structlog.get_logger()


def slugify(name: str) -> str:
    """URL-safe slug from a restaurant name.

    NFKD-normalises first so accented and non-Latin characters degrade to
    something usable rather than vanishing entirely.
    """
    normalised = unicodedata.normalize("NFKD", name)
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "restaurant"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Append a counter until the slug is free.

    `restaurants.slug` is UNIQUE, and two vendors calling their place "Pizza
    House" is not a hypothetical.
    """
    slug = base
    for suffix in range(2, 100):
        exists = await db.scalar(select(func.count()).select_from(Restaurant).where(
            Restaurant.slug == slug
        ))
        if not exists:
            return slug
        slug = f"{base}-{suffix}"
    # Astronomically unlikely; better than looping forever.
    from uuid import uuid4

    return f"{base}-{uuid4().hex[:6]}"


async def register_vendor(
    db: AsyncSession, email: str, password: str, full_name: str, details: RestaurantDetails
) -> tuple[User, Restaurant]:
    """Create a VENDOR account and its restaurant in one transaction.

    The caller must have already redeemed the OTP — this function assumes the
    address is verified.
    """
    from app.services.auth_service import find_by_identifier, set_password

    user = await find_by_identifier(db, email)

    if user is not None and user.role != UserRole.VENDOR:
        # Roles are fixed at creation: the composite role-guard FKs make a live
        # change unsafe once the account owns rows, and silently converting a
        # customer into a vendor would be a surprising thing to do to someone.
        raise ConflictError(
            "This email is already registered as a customer account. "
            "Use a different address for your restaurant."
        )

    if user is None:
        user = User(role=UserRole.VENDOR.value, email=email, is_email_verified=True)
        db.add(user)
        await db.flush()
    else:
        user.is_email_verified = True

    existing = await db.scalar(select(Restaurant).where(Restaurant.owner_id == user.id))
    if existing is not None:
        raise ConflictError("This account already has a restaurant")

    await set_password(db, user, password)
    user.full_name = full_name

    restaurant = Restaurant(
        owner_id=user.id,
        name=details.name,
        slug=await _unique_slug(db, slugify(details.name)),
        description=details.description,
        phone=details.phone,
        address_line=details.address_line,
        latitude=details.latitude,
        longitude=details.longitude,
        cuisine_types=details.cuisine_types,
        # Both deliberate. Unverified keeps it out of discovery until a human
        # checks it; CLOSED means it cannot take orders even after approval
        # until the vendor opens it themselves.
        is_verified=False,
        status="CLOSED",
        commission_rate=default_commission_rate(),
    )
    db.add(restaurant)

    try:
        await db.flush()
    except IntegrityError as exc:
        # uq_restaurants_owner is the likely culprit — two concurrent
        # registrations for the same account.
        raise ConflictError("This account already has a restaurant") from exc

    log.info(
        "vendor_registered",
        user_id=str(user.id),
        restaurant_id=str(restaurant.id),
        slug=restaurant.slug,
    )
    return user, restaurant


async def list_pending(db: AsyncSession, limit: int, offset: int) -> tuple[list[Restaurant], int]:
    """Restaurants awaiting approval, oldest first — a work queue, not a feed."""
    base = select(Restaurant).where(Restaurant.is_verified.is_(False))
    total = await db.scalar(
        select(func.count()).select_from(Restaurant).where(Restaurant.is_verified.is_(False))
    )
    result = await db.execute(
        base.order_by(Restaurant.created_at.asc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total or 0


def default_commission_rate() -> float:
    """The commission a restaurant is created on, as a fraction.

    Both creation paths (the registration fast path and application approval)
    call this rather than letting the column default to 0. A restaurant that
    exists at 0% is not a pricing decision anyone made, and because each order
    snapshots `commission_amount`, every order it takes before someone notices
    is permanently un-billable.
    """
    return settings.DEFAULT_COMMISSION_BASIS_POINTS / 10_000


async def set_commission_rate(db: AsyncSession, restaurant_id, rate: Decimal) -> Restaurant:
    """Reprice one restaurant. `rate` is a fraction: 0.15 is 15%.

    Forward-looking only, and that is the point of D6: orders already placed
    keep the `commission_amount` they were charged, so renegotiating a vendor
    from 15% to 18% cannot rewrite what they earned last month, in either
    direction.
    """
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")

    previous = Decimal(str(restaurant.commission_rate))
    restaurant.commission_rate = float(rate)
    await db.flush()

    log.info(
        "restaurant_commission_changed",
        restaurant_id=str(restaurant.id),
        previous_rate=str(previous),
        new_rate=str(rate),
    )
    return restaurant


async def set_verified(db: AsyncSession, restaurant_id, verified: bool) -> Restaurant:
    """Approve or revoke a restaurant.

    Revoking is not a delete: the storefront disappears from discovery but its
    order history, menu and payouts remain intact. A marketplace needs to be
    able to suspend a vendor without destroying the records of what they sold.
    """
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")

    if restaurant.is_verified == verified:
        raise ValidationError(
            f"Restaurant is already {'approved' if verified else 'unapproved'}"
        )

    restaurant.is_verified = verified
    if not verified:
        # Suspending must also take it offline; leaving it OPEN would let
        # in-flight traffic keep ordering.
        restaurant.status = "CLOSED"
    await db.flush()

    log.info("restaurant_verification_changed", restaurant_id=str(restaurant.id), verified=verified)
    return restaurant


def to_summary(restaurant: Restaurant) -> RestaurantSummary:
    return RestaurantSummary(
        id=str(restaurant.id),
        name=restaurant.name,
        slug=restaurant.slug,
        status=str(restaurant.status),
        is_verified=restaurant.is_verified,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        address_line=restaurant.address_line,
        cuisine_types=list(restaurant.cuisine_types or []),
    )


# ---------------------------------------------------------------------------
# Storefront profile & trading status
# ---------------------------------------------------------------------------


def is_accepting_orders(restaurant: Restaurant) -> bool:
    """The one flag that decides whether a customer can order.

    Three independent switches, owned by three different parties: `is_active`
    (the platform's kill switch), `is_verified` (the approval gate) and `status`
    (the vendor's own OPEN/CLOSED toggle). Derived in one place so no caller
    has to remember all three — forgetting `is_verified` here is exactly how an
    unapproved storefront starts taking orders.
    """
    return bool(
        restaurant.is_active and restaurant.is_verified and str(restaurant.status) == "OPEN"
    )


def to_profile(restaurant: Restaurant) -> RestaurantProfile:
    """The owner's full view. Money is converted to whole taka on the way out."""
    return RestaurantProfile(
        id=str(restaurant.id),
        owner_id=str(restaurant.owner_id),
        name=restaurant.name,
        slug=restaurant.slug,
        description=restaurant.description,
        cuisine_types=list(restaurant.cuisine_types or []),
        phone=restaurant.phone,
        logo_url=restaurant.logo_url,
        cover_image_url=restaurant.cover_image_url,
        status=str(restaurant.status),
        is_verified=restaurant.is_verified,
        is_active=restaurant.is_active,
        is_accepting_orders=is_accepting_orders(restaurant),
        rating_avg=float(restaurant.rating_avg),
        rating_count=restaurant.rating_count,
        address_line=restaurant.address_line,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        # Platform policy, not the stored column — which nothing reads any
        # more. Reported so a vendor can see what their customers are
        # charged without having to read the customer docs.
        delivery_fee_base=Decimal(settings.DELIVERY_FEE_BASE),
        min_order_amount=to_major(restaurant.min_order_amount),
        avg_prep_time_mins=restaurant.avg_prep_time_mins,
        commission_rate=Decimal(str(restaurant.commission_rate)),
        created_at=restaurant.created_at,
        updated_at=restaurant.updated_at,
    )


async def set_store_status(
    db: AsyncSession, restaurant: Restaurant, status: str
) -> StoreStatusResult:
    """Spec #36. The vendor's own OPEN/CLOSED switch.

    Opening an unapproved restaurant is **allowed and does nothing** — the
    response says so. Refusing would block a vendor from configuring their
    store during onboarding, which is precisely when they are setting it up;
    silently reporting success would be worse still. So the toggle is recorded,
    `is_accepting_orders` stays false, and the message explains which of the
    three switches is still off.

    There are no scheduled opening hours. `status` is a manual toggle and
    nothing sweeps it — a vendor who forgets to close stays open. Automatic
    hours need a table this schema does not have.
    """
    restaurant.status = status
    await db.flush()

    accepting = is_accepting_orders(restaurant)
    if accepting:
        message = "Your store is open and accepting orders"
    elif status == "CLOSED":
        message = "Your store is closed and will not receive new orders"
    elif not restaurant.is_verified:
        message = (
            "Saved, but your restaurant is still awaiting approval — customers "
            "cannot see or order from it yet"
        )
    else:
        message = "Saved, but this restaurant has been deactivated by an administrator"

    log.info(
        "store_status_changed",
        restaurant_id=str(restaurant.id),
        status=status,
        accepting=accepting,
    )
    return StoreStatusResult(
        restaurant_id=str(restaurant.id),
        status=str(restaurant.status),
        is_accepting_orders=accepting,
        message=message,
    )


async def update_profile(
    db: AsyncSession, restaurant: Restaurant, body: RestaurantProfileUpdateRequest
) -> RestaurantProfile:
    """[EXTENDED] Edit the storefront.

    Registration was previously the only write to a restaurant row, so nothing
    set here could ever be changed: no logo, no delivery fee, not even a typo in
    the address.

    PATCH semantics — only fields present in the body are touched, so an
    omitted `description` is left alone while an explicit `null` clears it.

    **The slug is deliberately not recomputed on rename.** It is the public URL
    of the storefront; regenerating it would break every link, QR code and
    bookmark already in circulation, and a restaurant that rebrands still wants
    its existing customers to arrive.
    """
    fields = body.model_dump(exclude_unset=True)

    # Coordinates move together or not at all. Accepting one alone would place
    # the restaurant on a new latitude with its old longitude — a point
    # somewhere it has never been, and one that discovery would then index.
    has_lat = "latitude" in fields and fields["latitude"] is not None
    has_lng = "longitude" in fields and fields["longitude"] is not None
    if has_lat != has_lng:
        raise ValidationError(
            "latitude and longitude must be updated together",
            details=["Send both coordinates, or neither"],
        )

    simple = ("name", "description", "phone", "logo_url", "cover_image_url", "address_line")
    for field in simple:
        if field in fields:
            value = fields[field]
            if field == "name":
                if value is None:
                    raise ValidationError("name cannot be cleared")
                value = value.strip()
            setattr(restaurant, field, value)

    if "cuisine_types" in fields and fields["cuisine_types"] is not None:
        restaurant.cuisine_types = [c.strip() for c in fields["cuisine_types"] if c.strip()]
    if has_lat and has_lng:
        # `location` is a GENERATED column; the database recomputes the geography
        # point from these two, so discovery follows automatically.
        restaurant.latitude = fields["latitude"]
        restaurant.longitude = fields["longitude"]
    if "min_order_amount" in fields and fields["min_order_amount"] is not None:
        restaurant.min_order_amount = to_minor(fields["min_order_amount"])
    if "avg_prep_time_mins" in fields and fields["avg_prep_time_mins"] is not None:
        restaurant.avg_prep_time_mins = fields["avg_prep_time_mins"]

    await db.flush()
    log.info(
        "restaurant_profile_updated",
        restaurant_id=str(restaurant.id),
        fields=sorted(fields.keys()),
    )
    return to_profile(restaurant)


# ---------------------------------------------------------------------------
# Business hours
# ---------------------------------------------------------------------------

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# What GET returns before the vendor ever saves — the Business Hour screen
# needs seven rows to render, not an empty object.
_DEFAULT_DAY = {"is_open": True, "opens_at": "10:00", "closes_at": "22:00"}


def hours_out(restaurant: Restaurant) -> BusinessHoursOut:
    """Stored hours, or the default template when none were ever saved.

    `store_status` rides along because these hours are **informational**:
    nothing flips the OPEN/CLOSED toggle from them (there is no scheduler),
    and a screen showing "Mon 10–22" next to a closed store should say so.
    """
    stored = restaurant.business_hours or {}
    days = {
        day: DayHoursOut(**stored.get(day, _DEFAULT_DAY)) for day in DAY_KEYS
    }
    return BusinessHoursOut(
        restaurant_id=str(restaurant.id),
        is_configured=bool(restaurant.business_hours),
        days=days,
        store_status=str(restaurant.status),
    )


async def set_hours(
    db: AsyncSession, restaurant: Restaurant, body: BusinessHoursRequest
) -> BusinessHoursOut:
    """PUT /vendor/hours — replace the whole week.

    A day marked open must carry both times; a closed day's times are
    discarded rather than stored, so reopening a day starts from the defaults
    instead of resurrecting stale hours. `closes_at` before `opens_at` means
    trading past midnight and is legal.
    """
    hours: dict = {}
    for day in DAY_KEYS:
        entry = getattr(body, day)
        if entry.is_open:
            if not entry.opens_at or not entry.closes_at:
                raise ValidationError(
                    f"{day}: opens_at and closes_at are required when the day is open"
                )
            if entry.opens_at == entry.closes_at:
                raise ValidationError(
                    f"{day}: opening and closing at the same minute is not a day"
                )
            hours[day] = {
                "is_open": True,
                "opens_at": entry.opens_at,
                "closes_at": entry.closes_at,
            }
        else:
            hours[day] = {"is_open": False, "opens_at": None, "closes_at": None}

    restaurant.business_hours = hours
    await db.flush()
    log.info("business_hours_updated", restaurant_id=str(restaurant.id))
    return hours_out(restaurant)
