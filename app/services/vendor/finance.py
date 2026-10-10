"""Earnings and payouts — the money behind the Withdraw screens.

**The balance is a query, not a column.**

    available = Σ (item_total − commission_amount)  over DELIVERED orders
              − Σ amount                            over payouts not FAILED

A stored balance is a second copy of the truth: the first time a payout row
and a balance update land in different transactions, they disagree forever
and quietly. A derived balance cannot drift — a FAILED payout returns its
amount by arithmetic, with no compensating write to forget.

PROCESSING payouts are already deducted. Money on its way out must not be
withdrawable a second time while the finance team executes the transfer.

No gateway moves money yet. A payout is **recorded** here (PROCESSING) and
**confirmed** by an administrator (COMPLETED / FAILED) — the same recorded-
then-executed convention refunds follow. The response says "on its way",
never "sent".
"""

import secrets
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import local_day, local_midnight, local_today
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.money import to_major, to_minor
from app.models.enums import OrderStatus, PayoutStatus
from app.models.order import Order
from app.models.payout import VendorPayout
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.requests import PayoutCreateRequest
from app.schemas.vendor import (
    EarningsTransaction,
    PayoutOut,
    VendorEarnings,
    VendorEarningsDay,
)

log = structlog.get_logger()

_DELIVERED = OrderStatus.DELIVERED.value
# Local (BUSINESS_TIMEZONE) days, as on the analytics screen. One expression
# object, so SELECT, GROUP BY and ORDER BY bind the same timezone parameter.
_DAY = local_day(Order.delivered_at)


async def _generate_reference(db: AsyncSession) -> str:
    """Receipt id like ``CHR64445654`` — short enough to read over the phone."""
    for digits in (8, 8, 9, 10):
        low = 10 ** (digits - 1)
        candidate = f"CHR{secrets.randbelow(9 * low) + low}"
        exists = await db.scalar(
            select(func.count())
            .select_from(VendorPayout)
            .where(VendorPayout.reference == candidate)
        )
        if not exists:
            return candidate
    raise RuntimeError("could not allocate a payout reference")  # pragma: no cover


def _delivered(restaurant: Restaurant) -> list:
    """The orders that earn: this restaurant's, DELIVERED. Served by
    `ix_orders_analytics (restaurant_id, delivered_at) WHERE status = 'DELIVERED'`."""
    return [Order.restaurant_id == restaurant.id, Order.status == _DELIVERED]


async def _totals_minor(
    db: AsyncSession, restaurant: Restaurant, since: datetime | None = None
) -> tuple[int, int, int]:
    """(orders, gross sales, commission) in paisa over delivered orders."""
    conditions = _delivered(restaurant)
    if since is not None:
        conditions.append(Order.delivered_at >= since)
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Order.item_total), 0),
                func.coalesce(func.sum(Order.commission_amount), 0),
            ).where(*conditions)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


async def _earned_since(db: AsyncSession, restaurant: Restaurant, since: datetime) -> int:
    _, gross, commission = await _totals_minor(db, restaurant, since)
    return gross - commission


async def _lifetime_earnings_minor(db: AsyncSession, restaurant: Restaurant) -> int:
    _, gross, commission = await _totals_minor(db, restaurant)
    return gross - commission


def _credit(order: Order) -> EarningsTransaction:
    return EarningsTransaction(
        order_id=str(order.id),
        order_number=order.order_number,
        amount=to_major(order.item_total - order.commission_amount),
        gross_sales=to_major(order.item_total),
        commission=to_major(order.commission_amount),
        payment_method=str(order.payment_method),
        delivered_at=order.delivered_at,
    )


async def _payout_sums_minor(db: AsyncSession, restaurant: Restaurant) -> tuple[int, int]:
    """(completed, processing) in paisa. FAILED is deliberately in neither."""
    result = await db.execute(
        select(VendorPayout.status, func.coalesce(func.sum(VendorPayout.amount), 0))
        .where(VendorPayout.restaurant_id == restaurant.id)
        .group_by(VendorPayout.status)
    )
    sums = {str(status): int(total) for status, total in result.all()}
    return sums.get(PayoutStatus.COMPLETED, 0), sums.get(PayoutStatus.PROCESSING, 0)


async def available_balance_minor(db: AsyncSession, restaurant: Restaurant) -> int:
    earned = await _lifetime_earnings_minor(db, restaurant)
    completed, processing = await _payout_sums_minor(db, restaurant)
    return earned - completed - processing


async def earnings(
    db: AsyncSession, restaurant: Restaurant, recent_n: int = 10
) -> VendorEarnings:
    """GET /vendor/earnings — balance, period and lifetime totals, and the
    recent per-order credits."""
    orders, gross, commission = await _totals_minor(db, restaurant)
    earned = gross - commission
    completed, processing = await _payout_sums_minor(db, restaurant)

    recent = await db.execute(
        select(Order)
        .where(*_delivered(restaurant))
        .order_by(Order.delivered_at.desc())
        .limit(recent_n)
    )
    transactions = [_credit(o) for o in recent.scalars().all()]

    today = local_today()
    week_start = today - timedelta(days=today.weekday())
    return VendorEarnings(
        restaurant_id=str(restaurant.id),
        available_balance=to_major(earned - completed - processing),
        today=to_major(await _earned_since(db, restaurant, local_midnight(today))),
        this_week=to_major(await _earned_since(db, restaurant, local_midnight(week_start))),
        this_month=to_major(
            await _earned_since(db, restaurant, local_midnight(today.replace(day=1)))
        ),
        delivered_orders=orders,
        gross_sales=to_major(gross),
        total_commission=to_major(commission),
        lifetime_earnings=to_major(earned),
        total_withdrawn=to_major(completed),
        processing_payouts=to_major(processing),
        min_payout_amount=to_major(to_minor(settings.PAYOUT_MIN_AMOUNT)),
        recent_transactions=transactions,
    )


async def transactions(
    db: AsyncSession,
    restaurant: Restaurant,
    limit: int,
    offset: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[EarningsTransaction], int]:
    """GET /vendor/earnings/transactions — every credit, newest first.

    No window means all time; either bound alone is allowed. Dates are Dhaka
    days, inclusive at both ends, as on the analytics screen.
    """
    if date_from and date_to and date_from > date_to:
        raise ValidationError("date_from must not be after date_to")
    conditions = _delivered(restaurant)
    if date_from:
        conditions.append(Order.delivered_at >= local_midnight(date_from))
    if date_to:
        conditions.append(Order.delivered_at < local_midnight(date_to + timedelta(days=1)))

    total = await db.scalar(select(func.count()).select_from(Order).where(*conditions))
    result = await db.execute(
        select(Order)
        .where(*conditions)
        .order_by(Order.delivered_at.desc(), Order.order_number.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_credit(o) for o in result.scalars().all()], total or 0


async def daily(
    db: AsyncSession, restaurant: Restaurant, limit: int, offset: int
) -> tuple[list[VendorEarningsDay], int]:
    """GET /vendor/earnings/days — one row per Dhaka day with a delivered
    order, newest first."""
    conditions = _delivered(restaurant)
    total = await db.scalar(select(func.count(func.distinct(_DAY))).where(*conditions))
    rows = await db.execute(
        select(
            _DAY,
            func.count(),
            func.coalesce(func.sum(Order.item_total), 0),
            func.coalesce(func.sum(Order.commission_amount), 0),
        )
        .where(*conditions)
        .group_by(_DAY)
        .order_by(_DAY.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        VendorEarningsDay(
            date=day,
            orders=int(n),
            gross_sales=to_major(int(gross)),
            commission=to_major(int(commission)),
            earnings=to_major(int(gross) - int(commission)),
        )
        for day, n, gross, commission in rows.all()
    ], total or 0


async def request_payout(
    db: AsyncSession, restaurant: Restaurant, body: PayoutCreateRequest
) -> VendorPayout:
    """POST /vendor/payouts — the Withdraw Money button.

    The restaurant row is locked FOR UPDATE first. Without it, two concurrent
    requests both read the same balance and both pass the check — the classic
    double-withdrawal. The lock serialises payout creation per restaurant;
    order traffic is untouched.
    """
    if body.method == "BANK" and not body.bank_name:
        raise ValidationError("bank_name is required for bank payouts")

    amount_minor = to_minor(body.amount)
    if amount_minor < to_minor(settings.PAYOUT_MIN_AMOUNT):
        raise ValidationError(
            f"Minimum withdrawal is {settings.PAYOUT_MIN_AMOUNT} taka"
        )

    await db.execute(
        select(Restaurant.id).where(Restaurant.id == restaurant.id).with_for_update()
    )

    available = await available_balance_minor(db, restaurant)
    if amount_minor > available:
        raise ValidationError(
            f"Insufficient balance: {to_major(available)} taka available",
            details=[f"requested {body.amount} taka"],
        )

    payout = VendorPayout(
        restaurant_id=restaurant.id,
        reference=await _generate_reference(db),
        amount=amount_minor,
        method=body.method,
        account_number=body.account_number.strip(),
        account_name=body.account_name.strip(),
        bank_name=body.bank_name,
        branch_name=body.branch_name,
        status=PayoutStatus.PROCESSING.value,
    )
    db.add(payout)
    await db.flush()

    log.info(
        "payout_requested",
        reference=payout.reference,
        restaurant_id=str(restaurant.id),
        amount=str(body.amount),
        method=body.method,
    )
    return payout


async def list_payouts(
    db: AsyncSession, restaurant: Restaurant, limit: int, offset: int
) -> tuple[list[VendorPayout], int]:
    """Payout History, newest first."""
    where = [VendorPayout.restaurant_id == restaurant.id]
    total = await db.scalar(
        select(func.count()).select_from(VendorPayout).where(*where)
    )
    result = await db.execute(
        select(VendorPayout)
        .where(*where)
        .order_by(VendorPayout.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total or 0


# ---------------------------------------------------------------------------
# The finance decision (admin)
# ---------------------------------------------------------------------------


async def _get_processing(db: AsyncSession, payout_id) -> VendorPayout:
    payout = await db.get(VendorPayout, payout_id, with_for_update=True)
    if payout is None:
        raise NotFoundError("Payout not found")
    if str(payout.status) != PayoutStatus.PROCESSING:
        raise ValidationError(f"This payout is already {str(payout.status).lower()}")
    return payout


async def admin_complete(db: AsyncSession, payout_id, admin: User) -> VendorPayout:
    """Confirm the transfer was made. Irreversible — money has left."""
    payout = await _get_processing(db, payout_id)
    payout.status = PayoutStatus.COMPLETED.value
    payout.processed_by = admin.id
    payout.processed_at = datetime.now(UTC)
    await db.flush()
    log.info("payout_completed", reference=payout.reference, admin_id=str(admin.id))
    return payout


async def admin_fail(db: AsyncSession, payout_id, admin: User, reason: str | None) -> VendorPayout:
    """The transfer bounced. Marking FAILED *is* the refund — the balance
    formula excludes FAILED rows, so the amount is withdrawable again with no
    compensating write."""
    payout = await _get_processing(db, payout_id)
    payout.status = PayoutStatus.FAILED.value
    payout.failure_reason = reason
    payout.processed_by = admin.id
    payout.processed_at = datetime.now(UTC)
    await db.flush()
    log.info("payout_failed", reference=payout.reference, admin_id=str(admin.id))
    return payout


async def admin_reopen(db: AsyncSession, payout_id, admin: User, reason: str) -> VendorPayout:
    """Take back a COMPLETED claim ("Mark Unpaid"): the transfer was marked
    by mistake, or bounced after the fact. Back to PROCESSING, so it re-enters
    the queue. The balance does not move — PROCESSING is already deducted,
    exactly as COMPLETED was — so reopening can never double-pay a vendor."""
    payout = await db.get(VendorPayout, payout_id, with_for_update=True)
    if payout is None:
        raise NotFoundError("Payout not found")
    if str(payout.status) != PayoutStatus.COMPLETED:
        raise ValidationError(
            f"Only a completed payout can be reopened; this one is {str(payout.status).lower()}"
        )
    payout.status = PayoutStatus.PROCESSING.value
    payout.processed_by = None
    payout.processed_at = None
    payout.reopened_at = datetime.now(UTC)
    payout.reopened_by = admin.id
    payout.reopen_reason = reason
    await db.flush()
    log.info("payout_reopened", reference=payout.reference, admin_id=str(admin.id), reason=reason)
    return payout


def to_out(payout: VendorPayout) -> PayoutOut:
    return PayoutOut(
        id=str(payout.id),
        restaurant_id=str(payout.restaurant_id),
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
