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

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.auth import RestaurantSummary
from app.schemas.requests import RestaurantDetails

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
