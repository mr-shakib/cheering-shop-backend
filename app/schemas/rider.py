"""[EXTENDED] The rider roster, as an administrator and dispatch see it.

The specification models a RIDER role but never a rider, so there is no
specified shape for one. These are the fields dispatch and the admin console
actually need: who they are, whether they are on shift, and how much they are
already carrying.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class RiderOut(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool
    vehicle_type: str | None = None
    license_number: str | None = None
    is_online: bool = Field(description="On shift — only online riders are auto-assigned")
    is_verified: bool = Field(description="Cleared to carry orders")
    orders_in_flight: int = Field(
        description="Orders this rider is holding right now — what dispatch balances on"
    )
    total_deliveries: int
    created_at: datetime


class RiderAssignment(BaseModel):
    """POST /admin/orders/{id}/assign-rider"""

    order_id: str
    status: str
    rider: RiderOut
    chosen_by: str = Field(description='"dispatch" when picked automatically, else "operator"')
    message: str
