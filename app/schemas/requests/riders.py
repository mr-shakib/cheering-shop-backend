"""[EXTENDED] Rider accounts and dispatch. Administrator-only, both of them."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiderCreateRequest(BaseModel):
    """POST /admin/riders

    `is_verified` defaults to true because an administrator typing this request
    IS the verification step — there is no rider document review queue. Pass
    false to enrol somebody who is not cleared to carry food yet.
    """

    full_name: str = Field(min_length=1, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, min_length=6, max_length=20)
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description=(
            "Sets the rider up to sign in at /auth/login. Omit to create the "
            "account without credentials — dispatch works either way, but the "
            "rider app cannot be used until a password exists."
        ),
    )
    vehicle_type: str | None = Field(default=None, max_length=40)
    license_number: str | None = Field(default=None, max_length=60)
    is_online: bool = Field(default=True, description="Start the rider on shift")
    is_verified: bool = Field(default=True, description="Cleared to carry orders")

    @model_validator(mode="after")
    def _needs_an_identifier(self):
        # ck_users_identifier rejects a row with neither. A 422 naming the
        # fields beats a 500 naming the constraint.
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        return self


class RiderUpdateRequest(BaseModel):
    """PATCH /admin/riders/{id} — shift state, clearance, credentials, and the
    Personal Info fields on Rider Details. PATCH: omitted fields are left
    alone; `documents` replaces the whole map when sent."""

    model_config = ConfigDict(extra="forbid")

    is_online: bool | None = None
    is_verified: bool | None = None
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Issue or reset the rider's sign-in password",
    )
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    vehicle_type: str | None = Field(default=None, max_length=40)
    license_number: str | None = Field(default=None, max_length=60)
    date_of_birth: date | None = None
    national_id: str | None = Field(default=None, max_length=50)
    documents: dict[str, str] | None = Field(
        default=None, description="Document kind -> URL, e.g. nid, driving_license"
    )

    @model_validator(mode="after")
    def _needs_a_field(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        return self


class RiderShiftRequest(BaseModel):
    """PATCH /rider/me/shift — the rider's own go-online toggle.

    Same column as the administrator's `is_online`, deliberately: a rider
    clocking on and an operator forcing them off must not be two states that
    can disagree.
    """

    is_online: bool


class AssignRiderRequest(BaseModel):
    """POST /admin/orders/{id}/assign-rider

    Omitting `rider_id` means "dispatch picks" — the same path the order
    lifecycle takes on its own. Naming one is the operator override.
    """

    rider_id: uuid.UUID | None = None


class RiderLocationRequest(BaseModel):
    """POST /rider/location

    Sent every few seconds while on shift. `heading` and `speed_kph` are
    optional because a phone that has just woken up has a fix before it has a
    bearing, and refusing the position until it does would blank the customer's
    map for no reason.
    """

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    heading: int | None = Field(default=None, ge=0, le=359)
    speed_kph: float | None = Field(default=None, ge=0, le=300)


class RiderIncentiveRequest(BaseModel):
    """POST /admin/riders/{id}/incentives — a bonus, added to the rider's
    balance at once. Write the reason for the rider: they see it."""

    amount: Decimal = Field(gt=0, le=100_000, description="Whole taka")
    reason: str = Field(min_length=3, max_length=255)


class RiderApplicationDocuments(BaseModel):
    """URLs from POST /rider-applications/uploads."""

    nid: str = Field(max_length=1000, description="National ID or passport")
    profile_photo: str = Field(max_length=1000)
    driving_license: str | None = Field(
        default=None, max_length=1000, description="Required for motorised vehicles"
    )
    payout_proof: str | None = Field(
        default=None, max_length=1000, description="Bank statement or wallet screenshot"
    )


class RiderApplicationPayout(BaseModel):
    method: Literal["BANK", "BKASH", "NAGAD", "ROCKET"]
    account_name: str = Field(min_length=2, max_length=150)
    account_number: str = Field(min_length=4, max_length=50)
    bank_name: str | None = Field(default=None, max_length=150)
    branch_name: str | None = Field(default=None, max_length=150)


class RiderApplicationRequest(BaseModel):
    """POST /rider-applications — [EXTENDED]. Public.

    No OTP: `/auth/otp/send` creates a provisional account, and a rider
    applicant must not get one until approved. Submissions are rate limited
    per source IP, one pending application per email, and every one is read by
    a person before anything is created.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(min_length=6, max_length=20)
    vehicle_type: Literal["CYCLE", "BIKE", "MOTORCYCLE", "SCOOTER", "CAR"]
    license_number: str | None = Field(default=None, max_length=60)
    date_of_birth: date
    national_id: str = Field(min_length=4, max_length=50)
    documents: RiderApplicationDocuments
    payout: RiderApplicationPayout
    agreed_to_terms: Literal[True]

    @model_validator(mode="after")
    def _motorised_needs_a_license(self):
        if self.vehicle_type in {"MOTORCYCLE", "SCOOTER", "CAR"} and not (
            self.license_number and self.documents.driving_license
        ):
            raise ValueError(
                "A motorised vehicle needs license_number and documents.driving_license"
            )
        return self


class RiderApplicationApproveRequest(BaseModel):
    """POST /admin/rider-applications/{id}/approve"""

    note: str | None = Field(default=None, max_length=1000)
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Sign-in password for the new rider. Omit to set one later "
        "with PATCH /admin/riders/{id}.",
    )


class RiderApplicationRejectRequest(BaseModel):
    """POST /admin/rider-applications/{id}/reject — the note is emailed to the
    applicant as the reason."""

    note: str = Field(min_length=3, max_length=1000)
