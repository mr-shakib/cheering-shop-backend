"""Addresses and favorites — spec #24–25, #34."""

from decimal import Decimal

from pydantic import BaseModel, Field


class AddressOut(BaseModel):
    """A saved delivery address. Coordinates come from the map pin.

    Field names mirror `AddressCreateRequest` exactly, so the Address screen
    can round-trip an edit without renaming anything between the GET and the
    PUT.
    """

    id: str
    type: str
    label: str | None = None
    street_address: str
    apartment: str | None = None
    landmark: str | None = None
    city: str | None = None
    postal_code: str | None = None
    contact_phone: str | None = None
    latitude: float
    longitude: float
    is_default: bool


class FavoriteToggled(BaseModel):
    """The heart button's new state, so the client never has to guess."""

    restaurant_id: str
    is_favorite: bool


class DeliverySlot(BaseModel):
    """One bookable window on the Schedule Order sheet.

    `is_available` is false for slots inside the lead time or outside the
    restaurant's opening hours — returned anyway, greyed, because a picker that
    silently omits times looks broken.
    """

    starts_at: str = Field(description="ISO 8601 with offset")
    ends_at: str
    label: str = Field(description='Rendered window, e.g. "2:40 PM - 2:50 PM"')
    is_available: bool


class ScheduleDay(BaseModel):
    """One date tab: Today / Tomorrow / Mon / Tue."""

    date: str = Field(description="YYYY-MM-DD in the restaurant's timezone")
    label: str
    slots: list[DeliverySlot] = Field(default_factory=list)


class ScheduleOptions(BaseModel):
    """GET /restaurants/{id}/schedule — the whole picker in one response."""

    restaurant_id: str
    slot_minutes: int
    min_lead_minutes: int
    days: list[ScheduleDay] = Field(default_factory=list)


class MinimumOrder(BaseModel):
    """Reused by the cart and checkout screens."""

    required: Decimal
    current: Decimal
    is_met: bool
