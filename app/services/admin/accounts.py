"""Customer lookup and account blocking.

Blocking is `users.is_active = false`. `get_current_user` re-reads the row on
every request, so an access token already in someone's hands stops working on
their next call — there is no window where a blocked account keeps acting —
and the refresh tokens are revoked so nothing can mint a new one.
"""

import uuid
from decimal import Decimal

import structlog
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.money import to_major
from app.models.address import Address
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.rider import RiderProfile
from app.models.user import User
from app.schemas.admin import (
    AccountStatus,
    AdminCustomerDetail,
    AdminCustomerRow,
    AdminCustomerStats,
)
from app.services import token_service
from app.services.admin.common import like_pattern

log = structlog.get_logger()

_DELIVERED = OrderStatus.DELIVERED.value


def _order_stats():
    """Per-customer order figures as a joinable subquery."""
    return (
        select(
            Order.customer_id.label("customer_id"),
            func.count().label("orders"),
            func.count().filter(Order.status == _DELIVERED).label("delivered"),
            func.count().filter(Order.status == OrderStatus.CANCELLED.value).label("cancelled"),
            func.coalesce(
                func.sum(case((Order.status == _DELIVERED, Order.grand_total), else_=0)), 0
            ).label("spent"),
        )
        .group_by(Order.customer_id)
        .subquery()
    )


def _to_row(user: User, orders: int, spent: int) -> AdminCustomerRow:
    return AdminCustomerRow(
        id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        avatar_url=user.avatar_url,
        order_count=orders,
        total_spent=to_major(spent),
        is_active=user.is_active,
        created_at=user.created_at,
    )


async def list_customers(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    q: str | None = None,
    status: str | None = None,
) -> tuple[list[AdminCustomerRow], int]:
    """Newest sign-ups first. `status` is ACTIVE or BLOCKED."""
    stats = _order_stats()
    conditions: list[ColumnElement[bool]] = [User.role == UserRole.CUSTOMER.value]
    if status:
        wanted = status.strip().upper()
        if wanted not in {"ACTIVE", "BLOCKED"}:
            raise ValidationError("status must be ACTIVE or BLOCKED")
        conditions.append(User.is_active.is_(wanted == "ACTIVE"))
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(
            or_(User.full_name.ilike(pattern), User.email.ilike(pattern), User.phone.ilike(pattern))
        )

    total = await db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    result = await db.execute(
        select(User, func.coalesce(stats.c.orders, 0), func.coalesce(stats.c.spent, 0))
        .outerjoin(stats, stats.c.customer_id == User.id)
        .where(*conditions)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_to_row(u, int(n), int(spent)) for u, n, spent in result.all()], total


async def get_customer(db: AsyncSession, customer_id: uuid.UUID) -> AdminCustomerDetail:
    user = await db.get(User, customer_id)
    if user is None or str(user.role) != UserRole.CUSTOMER:
        raise NotFoundError("No customer with that id")

    stats = _order_stats()
    row = (
        await db.execute(
            select(stats.c.orders, stats.c.delivered, stats.c.cancelled, stats.c.spent).where(
                stats.c.customer_id == user.id
            )
        )
    ).first()
    orders, delivered, cancelled, spent = (int(v) for v in row) if row else (0, 0, 0, 0)

    address = await db.scalar(
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
        .limit(1)
    )
    average = to_major(spent // delivered) if delivered else Decimal("0.00")
    return AdminCustomerDetail(
        **_to_row(user, orders, spent).model_dump(),
        default_address=address.street_address if address else None,
        last_login_at=user.last_login_at,
        stats=AdminCustomerStats(
            total_orders=orders,
            delivered_orders=delivered,
            cancelled_orders=cancelled,
            total_spent=to_major(spent),
            average_order=average,
        ),
    )


# Vendors are suspended through their restaurant (`POST /admin/restaurants/{id}/verify`),
# which is what takes them out of discovery; blocking the login alone would
# leave a storefront customers can order from and nobody can run.
_BLOCKABLE = {UserRole.CUSTOMER.value, UserRole.RIDER.value}


async def set_status(
    db: AsyncSession, admin: User, user_id: uuid.UUID, is_active: bool
) -> AccountStatus:
    user = await db.get(User, user_id, with_for_update=True)
    if user is None:
        raise NotFoundError("No account with that id")
    role = str(user.role)
    if role not in _BLOCKABLE:
        if role == UserRole.VENDOR:
            raise ConflictError(
                "Vendors are suspended through their restaurant",
                details=["Use POST /admin/restaurants/{id}/verify with is_verified=false"],
            )
        raise ForbiddenError("Administrator accounts cannot be blocked here")

    revoked = 0
    user.is_active = is_active
    if not is_active:
        revoked = await token_service.revoke_all_for_user(db, user.id)
        if role == UserRole.RIDER:
            # Off shift too, or dispatch keeps handing orders to someone who
            # can no longer open the app to see them.
            profile = await db.get(RiderProfile, user.id)
            if profile is not None:
                profile.is_online = False
    await db.flush()

    log.info(
        "account_status_changed",
        user_id=str(user.id),
        role=role,
        is_active=is_active,
        admin_id=str(admin.id),
    )
    who = user.full_name or user.email or user.phone or "The account"
    return AccountStatus(
        id=str(user.id),
        role=role,
        is_active=is_active,
        sessions_revoked=revoked,
        message=f"{who} is {'active again' if is_active else 'blocked and signed out'}",
    )
