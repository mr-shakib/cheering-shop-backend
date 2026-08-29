"""[EXTENDED] Rider accounts and dispatch. Administrator-only, both of them."""

import uuid

from pydantic import BaseModel, Field, model_validator


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
    """PATCH /admin/riders/{id} — shift state, clearance, credentials."""

    is_online: bool | None = None
    is_verified: bool | None = None
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Issue or reset the rider's sign-in password",
    )

    @model_validator(mode="after")
    def _needs_a_field(self):
        if self.is_online is None and self.is_verified is None and self.password is None:
            raise ValueError("Send is_online, is_verified, password, or a combination")
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
