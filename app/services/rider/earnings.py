"""What a rider has earned, and their withdrawals.

**What a rider earns.** Each order they deliver pays them its `delivery_fee`
and its `tip`, in full; administrators can add incentives on top. There is no
separate rider tariff: the delivery fee is what the customer pays to have the
food brought, and the rider is who brings it.

**The balance is a query, not a column** — exactly the vendor rule:

    available = Σ (delivery_fee + tip) over DELIVERED orders they carried
              + Σ incentives
              − Σ payouts not FAILED

PROCESSING payouts are already deducted, so money on its way out cannot be
withdrawn twice; a FAILED payout returns by arithmetic; a COMPLETED payout
reopened to PROCESSING leaves the balance where it was.
"""

import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.enums import OrderStatus, PayoutStatus
from app.models.order import Order
from app.models.payout import RiderPayout
from app.models.rider import RiderIncentive, RiderProfile
from app.models.user import User
from app.schemas.requests import PayoutCreateRequest
from app.schemas.rider import RiderEarnings, RiderEarningsDay, RiderEarningsTotals, RiderPayoutOut

log = structlog.get_logger()

_DELIVERED = OrderStatus.DELIVERED.value
_DAY = cast(func.timezone("UTC", Order.delivered_at), Date)
_INCENTIVE_DAY = cast(func.timezone("UTC", RiderIncentive.created_at), Date)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


async def _order_money(
    db: AsyncSession, rider_id: uuid.UUID, since: datetime | None = None
) -> tuple[int, int, int]:
    """(orders, delivery fees, tips) in paisa over delivered orders."""
    conditions = [Order.rider_id == rider_id, Order.status == _DELIVERED]
    if since is not None:
        conditions.append(Order.delivered_at >= since)
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Order.delivery_fee), 0),
                func.coalesce(func.sum(Order.tip), 0),
            ).where(*conditions)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


async def _incentives(db: AsyncSession, rider_id: uuid.UUID, since: datetime | None = None) -> int:
    conditions = [RiderIncentive.rider_id == rider_id]
    if since is not None:
        conditions.append(RiderIncentive.created_at >= since)
    value = await db.scalar(
        select(func.coalesce(func.sum(RiderIncentive.amount), 0)).where(*conditions)
    )
    return int(value or 0)


async def _earned_since(db: AsyncSession, rider_id: uuid.UUID, since: datetime) -> int:
    _, fees, tips = await _order_money(db, rider_id, since)
    return fees + tips + await _incentives(db, rider_id, since)


async def _payout_sums(db: AsyncSession, rider_id: uuid.UUID) -> tuple[int, int]:
    """(completed, processing) in paisa. FAILED is in neither."""
    rows = await db.execute(
        select(RiderPayout.status, func.coalesce(func.sum(RiderPayout.amount), 0))
        .where(RiderPayout.rider_id == rider_id)
        .group_by(RiderPayout.status)
    )
    sums = {str(status): int(total) for status, total in rows.all()}
    return sums.get(PayoutStatus.COMPLETED, 0), sums.get(PayoutStatus.PROCESSING, 0)


async def summary(db: AsyncSession, rider_id: uuid.UUID) -> RiderEarnings:
    _, fees, tips = await _order_money(db, rider_id)
    incentives = await _incentives(db, rider_id)
    total = fees + tips + incentives
    completed, processing = await _payout_sums(db, rider_id)

    today = datetime.now(UTC).date()
    return RiderEarnings(
        rider_id=str(rider_id),
        today=to_major(await _earned_since(db, rider_id, _midnight(today))),
        this_week=to_major(
            await _earned_since(db, rider_id, _midnight(today - timedelta(days=today.weekday())))
        ),
        this_month=to_major(await _earned_since(db, rider_id, _midnight(today.replace(day=1)))),
        totals=RiderEarningsTotals(
            delivery_earning=to_major(fees),
            tips=to_major(tips),
            incentives=to_major(incentives),
            total=to_major(total),
        ),
        available_balance=to_major(total - completed - processing),
        total_withdrawn=to_major(completed),
        processing_payouts=to_major(processing),
        min_payout_amount=to_major(to_minor(settings.PAYOUT_MIN_AMOUNT)),
    )


async def daily(
    db: AsyncSession, rider_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[RiderEarningsDay], int]:
    """One row per UTC day with any earnings, newest first."""
    orders = await db.execute(
        select(
            _DAY,
            func.count(),
            func.coalesce(func.sum(Order.delivery_fee), 0),
            func.coalesce(func.sum(Order.tip), 0),
        )
        .where(Order.rider_id == rider_id, Order.status == _DELIVERED)
        .group_by(_DAY)
    )
    incentives = await db.execute(
        select(_INCENTIVE_DAY, func.sum(RiderIncentive.amount))
        .where(RiderIncentive.rider_id == rider_id)
        .group_by(_INCENTIVE_DAY)
    )
    days: dict[date, list[int]] = {}
    for day, n, fees, tips in orders.all():
        days[day] = [int(n), int(fees), int(tips), 0]
    for day, amount in incentives.all():
        days.setdefault(day, [0, 0, 0, 0])[3] = int(amount)

    ordered = sorted(days.items(), reverse=True)
    page = ordered[offset : offset + limit]
    return [
        RiderEarningsDay(
            date=day,
            orders=n,
            delivery_earning=to_major(fees),
            tips=to_major(tips),
            incentives=to_major(bonus),
            total=to_major(fees + tips + bonus),
        )
        for day, (n, fees, tips, bonus) in page
    ], len(ordered)


async def grant_incentive(
    db: AsyncSession, admin: User, rider_id: uuid.UUID, amount, reason: str
) -> RiderIncentive:
    if await db.get(RiderProfile, rider_id) is None:
        raise NotFoundError("No rider with that id")
    incentive = RiderIncentive(
        rider_id=rider_id, amount=to_minor(amount), reason=reason.strip(), created_by=admin.id
    )
    db.add(incentive)
    await db.flush()
    await db.refresh(incentive)
    log.info("rider_incentive_granted", rider_id=str(rider_id), admin_id=str(admin.id))
    return incentive


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------


async def _reference(db: AsyncSession) -> str:
    for digits in (8, 8, 9, 10):
        low = 10 ** (digits - 1)
        candidate = f"RDP{secrets.randbelow(9 * low) + low}"
        taken = await db.scalar(
            select(func.count()).select_from(RiderPayout).where(RiderPayout.reference == candidate)
        )
        if not taken:
            return candidate
    raise RuntimeError("could not allocate a payout reference")  # pragma: no cover


async def request_payout(db: AsyncSession, rider: User, body: PayoutCreateRequest) -> RiderPayout:
    """POST /rider/payouts. The rider profile row is locked first so two
    concurrent withdrawals cannot both pass the balance check."""
    if body.method == "BANK" and not body.bank_name:
        raise ValidationError("bank_name is required for bank payouts")
    amount = to_minor(body.amount)
    if amount < to_minor(settings.PAYOUT_MIN_AMOUNT):
        raise ValidationError(f"Minimum withdrawal is {settings.PAYOUT_MIN_AMOUNT} taka")

    locked = await db.scalar(
        select(RiderProfile.user_id).where(RiderProfile.user_id == rider.id).with_for_update()
    )
    if locked is None:
        raise NotFoundError("That rider account has no rider profile")

    earned = await summary(db, rider.id)
    available = to_minor(earned.available_balance)
    if amount > available:
        raise ValidationError(
            f"Insufficient balance: {to_major(available)} taka available",
            details=[f"requested {body.amount} taka"],
        )

    payout = RiderPayout(
        rider_id=rider.id,
        reference=await _reference(db),
        amount=amount,
        method=body.method,
        account_number=body.account_number.strip(),
        account_name=body.account_name.strip(),
        bank_name=body.bank_name,
        branch_name=body.branch_name,
    )
    db.add(payout)
    await db.flush()
    await db.refresh(payout)
    log.info("rider_payout_requested", reference=payout.reference, rider_id=str(rider.id))
    return payout


async def list_payouts(
    db: AsyncSession, rider_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[RiderPayout], int]:
    total = await db.scalar(
        select(func.count()).select_from(RiderPayout).where(RiderPayout.rider_id == rider_id)
    )
    rows = await db.scalars(
        select(RiderPayout)
        .where(RiderPayout.rider_id == rider_id)
        .order_by(RiderPayout.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.all()), int(total or 0)


async def _get_payout(
    db: AsyncSession, payout_id: uuid.UUID, expected: PayoutStatus
) -> RiderPayout:
    payout = await db.get(RiderPayout, payout_id, with_for_update=True)
    if payout is None:
        raise NotFoundError("Payout not found")
    if str(payout.status) != expected:
        raise ValidationError(
            f"This payout is {str(payout.status).lower()}; expected {expected.value.lower()}"
        )
    return payout


async def admin_complete(db: AsyncSession, payout_id: uuid.UUID, admin: User) -> RiderPayout:
    payout = await _get_payout(db, payout_id, PayoutStatus.PROCESSING)
    payout.status = PayoutStatus.COMPLETED.value
    payout.processed_by = admin.id
    payout.processed_at = datetime.now(UTC)
    await db.flush()
    log.info("rider_payout_completed", reference=payout.reference, admin_id=str(admin.id))
    return payout


async def admin_fail(
    db: AsyncSession, payout_id: uuid.UUID, admin: User, reason: str | None
) -> RiderPayout:
    payout = await _get_payout(db, payout_id, PayoutStatus.PROCESSING)
    payout.status = PayoutStatus.FAILED.value
    payout.failure_reason = reason
    payout.processed_by = admin.id
    payout.processed_at = datetime.now(UTC)
    await db.flush()
    log.info("rider_payout_failed", reference=payout.reference, admin_id=str(admin.id))
    return payout


async def admin_reopen(
    db: AsyncSession, payout_id: uuid.UUID, admin: User, reason: str
) -> RiderPayout:
    """Mark Unpaid: COMPLETED back to PROCESSING. The balance does not move."""
    payout = await _get_payout(db, payout_id, PayoutStatus.COMPLETED)
    payout.status = PayoutStatus.PROCESSING.value
    payout.processed_by = None
    payout.processed_at = None
    payout.reopened_at = datetime.now(UTC)
    payout.reopened_by = admin.id
    payout.reopen_reason = reason
    await db.flush()
    log.info("rider_payout_reopened", reference=payout.reference, admin_id=str(admin.id))
    return payout


def to_out(payout: RiderPayout) -> RiderPayoutOut:
    return RiderPayoutOut(
        id=str(payout.id),
        rider_id=str(payout.rider_id),
        reference=payout.reference,
        amount=to_major(payout.amount),
        method=str(payout.method),
        account_number=payout.account_number,
        account_name=payout.account_name,
        bank_name=payout.bank_name,
        branch_name=payout.branch_name,
        status=str(payout.status),
        failure_reason=payout.failure_reason,
        requested_at=payout.created_at,
        processed_at=payout.processed_at,
    )
