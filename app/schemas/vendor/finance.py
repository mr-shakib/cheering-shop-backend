"""Earnings and payouts — the Withdraw screens."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class EarningsTransaction(BaseModel):
    """One credit on the Earnings screen: a delivered order's payout."""

    order_id: str
    order_number: int
    amount: Decimal = Field(description="item_total - commission for that order")
    gross_sales: Decimal = Field(description="The order's item_total")
    commission: Decimal = Field(description="The commission snapshotted on the order")
    payment_method: str
    delivered_at: datetime


class VendorEarnings(BaseModel):
    """GET /vendor/earnings.

    `available_balance` is derived, never stored:
    lifetime delivered earnings − every payout that has not FAILED. A payout
    still PROCESSING is already deducted — money on its way out is not
    available twice.
    """

    restaurant_id: str
    available_balance: Decimal
    today: Decimal = Field(description="Earned on orders delivered today, Dhaka time")
    this_week: Decimal = Field(description="Since Monday 00:00, Dhaka time")
    this_month: Decimal = Field(description="Since the 1st, 00:00 Dhaka time")
    delivered_orders: int = Field(description="Lifetime count of DELIVERED orders")
    gross_sales: Decimal = Field(description="Lifetime item totals of delivered orders")
    total_commission: Decimal = Field(description="Lifetime commission on those orders")
    lifetime_earnings: Decimal = Field(description="gross_sales - total_commission")
    total_withdrawn: Decimal = Field(description="COMPLETED payouts")
    processing_payouts: Decimal = Field(description="Requested but not yet confirmed")
    min_payout_amount: Decimal
    recent_transactions: list[EarningsTransaction] = Field(
        default_factory=list,
        description="The latest 10; GET /vendor/earnings/transactions has them all",
    )


class VendorEarningsDay(BaseModel):
    """GET /vendor/earnings/days — one Dhaka day with any delivered order."""

    date: date
    orders: int = Field(description="Orders delivered that day")
    gross_sales: Decimal
    commission: Decimal
    earnings: Decimal = Field(description="gross_sales - commission")


class PayoutOut(BaseModel):
    id: str
    restaurant_id: str
    reference: str = Field(description='Receipt id, e.g. "CHR64445654"')
    amount: Decimal
    method: str
    account_number: str
    account_name: str
    bank_name: str | None = None
    branch_name: str | None = None
    status: str = Field(description="PROCESSING, COMPLETED or FAILED")
    failure_reason: str | None = None
    requested_at: datetime
    processed_at: datetime | None = None
