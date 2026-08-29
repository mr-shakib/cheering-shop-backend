"""[EXTENDED] The rider roster an administrator maintains.

There is no rider signup and there should not be one: ``/auth/otp/send``
accepts CUSTOMER and VENDOR only, because a public endpoint that mints
couriers is an obvious hole. A rider therefore exists because an administrator
created one, which also means that creating the account IS the verification
step today — there is no rider document pipeline the way there is for vendor
applications, so ``is_verified`` records a decision a human already made rather
than the output of a review queue.

Riders created here cannot sign in. No password is set, and there are no
rider-facing endpoints for a token to reach, so an account that could
authenticate would be a credential with nothing behind it. When the rider app
lands, enrolment gains a password or an OTP path and this stays the roster.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.enums import UserRole
from app.models.rider import RiderProfile
from app.models.user import User
from app.schemas.requests import RiderCreateRequest
from app.schemas.rider import RiderOut
from app.services.rider.dispatch import count_in_flight, in_flight_counts

log = structlog.get_logger()


def to_out(user: User, profile: RiderProfile, in_flight: int) -> RiderOut:
    return RiderOut(
        id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        is_active=user.is_active,
        vehicle_type=profile.vehicle_type,
        license_number=profile.license_number,
        is_online=profile.is_online,
        is_verified=profile.is_verified,
        orders_in_flight=in_flight,
        total_deliveries=profile.total_deliveries,
        created_at=user.created_at,
    )


async def create_rider(db: AsyncSession, body: RiderCreateRequest) -> RiderOut:
    """Create a RIDER account and its profile in one transaction.

    A role is fixed at creation. If the address already belongs to somebody,
    this refuses rather than converting them — the composite role-guard FKs
    make a live role change unsafe once an account owns rows, and turning a
    customer into a courier behind their back would be a surprising thing to
    do to a person.
    """
    from app.services.auth_service import find_by_identifier

    for identifier in (body.email, body.phone):
        if identifier and await find_by_identifier(db, identifier) is not None:
            raise ConflictError(
                "That email or phone already belongs to an account",
                details=["Riders need an identifier nobody else is using"],
            )

    user = User(
        id=uuid.uuid4(),
        role=UserRole.RIDER.value,
        email=body.email,
        phone=body.phone,
        full_name=body.full_name,
        is_email_verified=bool(body.email),
        is_phone_verified=bool(body.phone),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # users.email and users.phone are both UNIQUE — two administrators
        # enrolling the same courier at once land here.
        raise ConflictError("That email or phone already belongs to an account") from exc

    profile = RiderProfile(
        user_id=user.id,
        user_role=UserRole.RIDER.value,
        vehicle_type=body.vehicle_type,
        license_number=body.license_number,
        is_online=body.is_online,
        is_verified=body.is_verified,
    )
    db.add(profile)
    await db.flush()

    log.info("rider_created", rider_id=str(user.id), is_online=profile.is_online)
    return to_out(user, profile, 0)


async def list_riders(
    db: AsyncSession, limit: int, offset: int, *, online_only: bool = False
) -> tuple[list[RiderOut], int]:
    """The dispatch pool, most idle first — the same order dispatch itself uses,
    so an operator overriding a choice sees the list it was choosing from."""
    load = in_flight_counts()
    conditions = [User.role == UserRole.RIDER.value]
    if online_only:
        conditions.append(RiderProfile.is_online.is_(True))

    total = await db.scalar(
        select(func.count())
        .select_from(User)
        .join(RiderProfile, RiderProfile.user_id == User.id)
        .where(*conditions)
    )
    rows = await db.execute(
        select(User, RiderProfile, func.coalesce(load.c.n, 0))
        .join(RiderProfile, RiderProfile.user_id == User.id)
        .outerjoin(load, load.c.rider_id == User.id)
        .where(*conditions)
        .order_by(func.coalesce(load.c.n, 0), User.created_at)
        .limit(limit)
        .offset(offset)
    )
    return [to_out(u, p, n) for u, p, n in rows.all()], int(total or 0)


async def get_rider(db: AsyncSession, rider_id: uuid.UUID) -> tuple[User, RiderProfile]:
    user = await db.get(User, rider_id)
    if user is None or str(user.role) != UserRole.RIDER:
        raise NotFoundError("No rider account with that id")
    profile = await db.get(RiderProfile, rider_id)
    if profile is None:
        raise NotFoundError("That rider account has no rider profile")
    return user, profile


async def set_flags(
    db: AsyncSession,
    rider_id: uuid.UUID,
    *,
    is_online: bool | None = None,
    is_verified: bool | None = None,
) -> RiderOut:
    """Shift state and clearance — the two things dispatch filters on.

    Taking a rider off shift does not touch the orders they are already
    holding. Those are in a bag on a motorcycle; a flag in a database does not
    bring them back, and clearing the assignment would strand the customer.
    """
    user, profile = await get_rider(db, rider_id)
    if is_online is not None:
        profile.is_online = is_online
    if is_verified is not None:
        profile.is_verified = is_verified
    await db.flush()

    log.info(
        "rider_flags_set",
        rider_id=str(user.id),
        is_online=profile.is_online,
        is_verified=profile.is_verified,
    )
    return to_out(user, profile, await count_in_flight(db, user.id))
