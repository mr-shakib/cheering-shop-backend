"""Payouts — the Withdraw flow and the admin decision on it."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PayoutCreateRequest(BaseModel):
    """POST /vendor/payouts — the Withdraw Money button.

    Destination details are per-request, not read from the application's saved
    payout block: the withdraw form lets the vendor pay out to any account,
    and the request is the snapshot the finance team executes against.
    """

    amount: Decimal = Field(gt=0, description="Whole taka")
    method: Literal["BANK", "BKASH", "NAGAD", "ROCKET"]
    account_number: str = Field(min_length=4, max_length=50)
    account_name: str = Field(
        min_length=2, max_length=150, description="Beneficiary name"
    )
    bank_name: str | None = Field(default=None, max_length=150, description="BANK only")
    branch_name: str | None = Field(default=None, max_length=150)


class PayoutFailRequest(BaseModel):
    """POST /admin/payouts/{id}/fail — the reason is shown to the vendor."""

    reason: str | None = Field(default=None, max_length=500)
