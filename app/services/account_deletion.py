"""Account self-deletion — DELETE /users/me.

Google Play requires every app that lets people create an account to let them
delete it from inside the app. This is that deletion, for customers, vendors
and riders alike. Administrators are not covered: their accounts are managed
from the admin console.

**The row stays; the person goes.** `orders.customer_id`, `orders.rider_id`
and `restaurants.owner_id` are ON DELETE RESTRICT, and completed orders are
records we must keep for tax and accounting (privacy policy §5). So deleting
an account means:

* everything that only describes the person is **deleted**: addresses,
  favourites, cart, devices, sessions, biometric keys, Google links, inbox,
  community posts, pending codes; a rider's location trail and application;
  a vendor's partner application (NID, documents, payout details);
* the `users` row is **wiped** down to id, role, timestamps and
  `deleted_at`. Email, phone, name, photo and every credential are cleared,
  so the email and phone are free to register again as a new account;
* what must be kept **stays**, now pointing at an id that identifies nobody:
  orders (minus the contact phone and delivery note), payouts, reviews,
  order chat and support tickets. A vendor's restaurant is closed and taken
  off the app for good, but kept, because its orders name it.

**When it is refused (409).** While an order is still under way — the
kitchen, the rider and the customer all need each other until it is
delivered or cancelled — and, for vendors and riders, while money is still
owed to them or a withdrawal is being processed. Deleting would make that
money impossible to pay out.

**Proof of identity.** An account with a password must re-enter it, as
`POST /users/me/password` demands, so a stolen access token cannot delete the
account. An account without one (Google or code sign-in) is confirmed by its
session alone: such a session can already set a password, so asking for
nothing more here lowers no bar.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import verify_password
from app.models.address import Address
from app.models.cart import Cart
from app.models.community import CommunityPost
from app.models.enums import RestaurantStatus, UserRole
from app.models.notification import UserNotification
from app.models.order import Order
from app.models.restaurant import Favorite, Restaurant
from app.models.rider import RiderLocationPing, RiderProfile
from app.models.rider_application import RiderApplication
from app.models.user import (
    AuthIdentity,
    BiometricCredential,
    IdempotencyKey,
    OtpCode,
    RefreshToken,
    User,
    UserDevice,
)
from app.models.vendor_application import VendorApplication
from app.schemas.rider import RiderEarnings
from app.schemas.vendor import VendorEarnings
from app.services.otp_service import normalise_identifier
from app.services.rider import earnings as rider_earnings
from app.services.rider.dispatch import IN_FLIGHT
from app.services.vendor import finance as vendor_finance

log = structlog.get_logger()

# Rows that exist only for the account itself, keyed on `user_id`.
_OWNED_BY_USER = (
    RefreshToken,
    UserDevice,
    BiometricCredential,
    AuthIdentity,
    IdempotencyKey,
    Address,
    Favorite,
    Cart,
    UserNotification,
)


async def delete_account(db: AsyncSession, user: User, password: str | None) -> datetime:
    """Delete the caller's account. Returns when it was deleted.

    Flushes but does not commit; the endpoint commits. Calling it again for an
    account that is already deleted returns the original time, so a retried
    request reads as the success it was.
    """
    # Locked so two taps on "Delete" cannot both run the wipe, and refreshed
    # so the second sees what the first did.
    locked = await db.get(User, user.id, with_for_update=True, populate_existing=True)
    assert locked is not None  # the caller was resolved from this row
    if locked.deleted_at is not None:
        return locked.deleted_at

    role = str(locked.role)
    if role == UserRole.ADMIN:
        raise ForbiddenError("Administrator accounts are removed from the admin console")

    if locked.password_hash is not None:
        if not password:
            raise ValidationError("Enter your password to delete your account")
        if not verify_password(password, locked.password_hash):
            raise UnauthorizedError("Password is incorrect", code=ErrorCode.INVALID_CREDENTIALS)

    restaurant = None
    if role == UserRole.VENDOR:
        restaurant = await db.scalar(select(Restaurant).where(Restaurant.owner_id == locked.id))

    await _refuse_if_orders_under_way(db, locked, restaurant)
    await _refuse_if_money_owed(db, locked, restaurant)

    now = datetime.now(UTC)
    await _delete_personal_rows(db, locked)
    if role == UserRole.CUSTOMER:
        # The order is kept; how to reach the person who placed it is not.
        await db.execute(
            update(Order)
            .where(Order.customer_id == locked.id)
            .values(delivery_contact_phone=None, special_instructions=None)
        )
    elif role == UserRole.RIDER:
        await _wipe_rider(db, locked.id)
    elif role == UserRole.VENDOR:
        await _close_store(db, locked.id, restaurant)

    _wipe_user(locked, now)
    await db.flush()
    log.info("account_deleted", user_id=str(locked.id), role=role)
    return now


async def _refuse_if_orders_under_way(
    db: AsyncSession, user: User, restaurant: Restaurant | None
) -> None:
    role = str(user.role)
    if role == UserRole.CUSTOMER:
        whose = Order.customer_id == user.id
    elif role == UserRole.RIDER:
        whose = Order.rider_id == user.id
    elif restaurant is not None:
        whose = Order.restaurant_id == restaurant.id
    else:
        return

    numbers = (
        await db.scalars(
            select(Order.order_number)
            .where(whose, Order.status.in_([s.value for s in IN_FLIGHT]))
            .order_by(Order.order_number)
        )
    ).all()
    if numbers:
        raise ConflictError(
            "You have orders in progress. Delete your account once they are "
            "delivered or cancelled",
            code=ErrorCode.ACCOUNT_HAS_ACTIVE_ORDERS,
            details=[f"Order #{n}" for n in numbers],
        )


async def _refuse_if_money_owed(
    db: AsyncSession, user: User, restaurant: Restaurant | None
) -> None:
    """Earnings not yet paid out, or a withdrawal on its way. Either one needs
    the payout details this deletion would wipe."""
    role = str(user.role)
    summary: RiderEarnings | VendorEarnings
    if role == UserRole.RIDER:
        summary = await rider_earnings.summary(db, user.id)
    elif role == UserRole.VENDOR and restaurant is not None:
        summary = await vendor_finance.earnings(db, restaurant, recent_n=0)
    else:
        return
    balance, processing = summary.available_balance, summary.processing_payouts

    details = []
    if balance > 0:
        details.append(f"Unpaid balance: ৳{balance}")
    if processing > 0:
        details.append(f"Withdrawal being processed: ৳{processing}")
    if details:
        raise ConflictError(
            "You still have earnings with us. Withdraw them, or contact support "
            "to settle them, before deleting your account",
            code=ErrorCode.ACCOUNT_HAS_BALANCE,
            details=details,
        )


async def _delete_personal_rows(db: AsyncSession, user: User) -> None:
    for model in _OWNED_BY_USER:
        await db.execute(delete(model).where(model.user_id == user.id))
    # Their reports go with them (ON DELETE CASCADE on the post).
    await db.execute(delete(CommunityPost).where(CommunityPost.author_id == user.id))
    identifiers = [normalise_identifier(i) for i in (user.email, user.phone) if i]
    if identifiers:
        await db.execute(delete(OtpCode).where(OtpCode.identifier.in_(identifiers)))


async def _wipe_rider(db: AsyncSession, rider_id: uuid.UUID) -> None:
    """Off shift, identity documents and payout details gone, trail deleted.
    Vehicle type and ratings stay: they describe deliveries, not the person."""
    profile = await db.get(RiderProfile, rider_id)
    if profile is not None:
        profile.is_online = False
        profile.license_number = None
        profile.national_id = None
        profile.date_of_birth = None
        profile.documents = {}
        profile.payout = {}
        profile.current_latitude = None
        profile.current_longitude = None
        profile.last_location_at = None
    await db.execute(delete(RiderLocationPing).where(RiderLocationPing.rider_id == rider_id))
    await db.execute(delete(RiderApplication).where(RiderApplication.user_id == rider_id))


async def _close_store(
    db: AsyncSession, owner_id: uuid.UUID, restaurant: Restaurant | None
) -> None:
    """Closed, off the app, and off the hours schedule so the worker never
    opens it again. Kept, because its orders name it."""
    if restaurant is not None:
        restaurant.is_active = False
        restaurant.status = RestaurantStatus.CLOSED.value
        restaurant.business_hours = None
        restaurant.scheduled_open = None
        restaurant.phone = None
    await db.execute(delete(VendorApplication).where(VendorApplication.user_id == owner_id))


def _wipe_user(user: User, now: datetime) -> None:
    user.email = None
    user.phone = None
    user.full_name = None
    user.avatar_url = None
    user.password_hash = None
    user.totp_secret = None
    user.totp_pending_secret = None
    user.is_2fa_enabled = False
    user.is_biometrics_enabled = False
    user.is_email_verified = False
    user.is_phone_verified = False
    user.is_active = False
    user.deleted_at = now
