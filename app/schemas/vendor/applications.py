"""Partner applications — submission receipt, status check, admin review."""

from datetime import datetime

from pydantic import BaseModel, Field


class VendorApplicationSubmitted(BaseModel):
    """POST /vendor/applications — what the 'Application submitted!' screen shows."""

    application_no: str = Field(description='Human-readable reference, e.g. "PTN-88291"')
    status: str
    restaurant_id: str
    submitted_at: datetime
    message: str


class VendorApplicationStatus(BaseModel):
    """GET /vendor/applications/{application_no} — the applicant's view.

    `review_note` is populated only for REJECTED applications: an approval note
    is an internal remark, but a rejection reason belongs to the applicant.
    """

    application_no: str
    business_name: str
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None = None
    review_note: str | None = None


class VendorApplicationDetail(BaseModel):
    """The administrator's full view — everything the form submitted."""

    id: str
    application_no: str
    status: str
    user_id: str
    restaurant_id: str

    business_name: str
    business_type: str
    business_category: str
    branch_count: int
    cuisine_types: list[str] = Field(default_factory=list)

    address_line: str
    area: str | None = None
    latitude: float
    longitude: float

    owner_full_name: str
    owner_email: str
    owner_phone: str
    national_id: str

    documents: dict[str, str] = Field(default_factory=dict)
    payout: dict = Field(default_factory=dict)

    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
