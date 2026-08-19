"""Vendor partner applications.

The nested blocks mirror the application form's steps one-to-one (business →
location → owner → documents), so the mobile client can validate each screen
against exactly one sub-model and submit the whole thing at Review.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ApplicationBusinessInfo(BaseModel):
    """Form step 1 — Business Information."""

    name: str = Field(min_length=2, max_length=180, description="Business/store name")
    business_type: Literal["RESTAURANT", "GROCERY", "PHARMACY"] = Field(
        description="What kind of shop this is; decides which storefront features apply"
    )
    business_category: str = Field(
        min_length=2, max_length=80, description='e.g. "Street Food", "Fine Dining"'
    )
    branch_count: int = Field(
        default=1, ge=1, le=50, description="Number of branches to register"
    )
    cuisine_types: list[str] = Field(default_factory=list, max_length=10)


class ApplicationLocation(BaseModel):
    """Form step 2 — Location. Coordinates come from the map pin."""

    address_line: str = Field(min_length=5, max_length=500)
    area: str | None = Field(
        default=None, max_length=120, description='Area/zone name, e.g. "Nikunja 2"'
    )
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ApplicationOwnerInfo(BaseModel):
    """Form step 3 — Owner Information. The email is the future login identifier."""

    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(min_length=6, max_length=20)
    national_id: str = Field(
        min_length=4, max_length=50, description="National ID or passport number"
    )


class ApplicationDocuments(BaseModel):
    """Form step 4 — uploaded document URLs from POST /vendor/applications/uploads.

    `trade_license` is optional at submission — a street-food stall may not
    hold one, and the admin decides whether that matters for approval.
    """

    shop_image: str = Field(max_length=1000)
    owner_nid: str = Field(max_length=1000, description="Photo of the owner's NID/passport")
    menu_list: str = Field(max_length=1000, description="Menu / product list with prices")
    trade_license: str | None = Field(default=None, max_length=1000)


class ApplicationPayout(BaseModel):
    """Form step 4 — bank / mobile wallet details, for payouts once approved."""

    method: Literal["BANK", "BKASH", "NAGAD", "ROCKET"]
    account_name: str = Field(min_length=2, max_length=150)
    account_number: str = Field(min_length=4, max_length=50)
    bank_name: str | None = Field(default=None, max_length=150)
    branch_name: str | None = Field(default=None, max_length=150)


class VendorApplicationRequest(BaseModel):
    """POST /vendor/applications — [EXTENDED].

    `otp_code` is the code sent to the owner's email at the Owner Information
    step (`POST /auth/otp/send` with `role: "VENDOR"`). Redeeming it here proves
    the applicant controls the address the approval decision will be sent to.

    No password field, deliberately: the form never asks for one. Credentials
    are set after approval via the OTP-based `/auth/password/forgot` →
    `/auth/password/reset` flow.
    """

    otp_code: str = Field(min_length=4, max_length=8)
    business: ApplicationBusinessInfo
    location: ApplicationLocation
    owner: ApplicationOwnerInfo
    documents: ApplicationDocuments
    payout: ApplicationPayout
    # Rejected at the schema boundary, not in the service: by the time the
    # service runs, the OTP has been consumed, and a terms error should not
    # cost the applicant a fresh code.
    agreed_to_terms: Literal[True] = Field(
        description="Must be true — the Partner Terms & Conditions checkbox"
    )


class ApplicationUploadRequest(BaseModel):
    """POST /vendor/applications/uploads — [EXTENDED]. Unauthenticated by
    design (applicants have no account yet), so it is rate limited per IP."""

    file_type: str = Field(description="MIME type, e.g. image/jpeg or application/pdf")
    file_name: str | None = None


class ApplicationDecisionRequest(BaseModel):
    """POST /admin/vendor-applications/{id}/approve and .../reject."""

    note: str | None = Field(
        default=None,
        max_length=1000,
        description="Approve: internal note. Reject: the reason, emailed to the applicant.",
    )
