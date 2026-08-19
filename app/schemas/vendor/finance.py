"""Earnings and payouts — the Withdraw screens."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class EarningsTransaction(BaseModel):
    """One credit on the Earnings screen: a delivered order's payout."""

    order_id: str
    order_number: int
    amount: Decimal = Field(description="item_total - commission for that order")
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
    lifetime_earnings: Decimal
    total_withdrawn: Decimal = Field(description="COMPLETED payouts")
    processing_payouts: Decimal = Field(description="Requested but not yet confirmed")
    min_payout_amount: Decimal
    recent_transactions: list[EarningsTransaction] = Field(default_factory=list)


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
