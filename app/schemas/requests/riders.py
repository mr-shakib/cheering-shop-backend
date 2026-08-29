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
    """PATCH /admin/riders/{id} — shift state and clearance."""

    is_online: bool | None = None
    is_verified: bool | None = None

    @model_validator(mode="after")
    def _needs_a_field(self):
        if self.is_online is None and self.is_verified is None:
            raise ValueError("Send is_online, is_verified, or both")
        return self


class AssignRiderRequest(BaseModel):
    """POST /admin/orders/{id}/assign-rider

    Omitting `rider_id` means "dispatch picks" — the same path the order
    lifecycle takes on its own. Naming one is the operator override.
    """

    rider_id: uuid.UUID | None = None
