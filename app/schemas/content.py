"""Reels and app banners — [EXTENDED].

The customer's reel card lives with the other discovery models
(`app.schemas.customer.ReelOut`), because it embeds a `RestaurantCard`.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class BannerOut(BaseModel):
    """A banner as the apps render it."""

    id: str
    title: str
    media_url: str
    media_type: str = Field(description="IMAGE, GIF or LOTTIE (a Lottie JSON animation)")
    placement: str
    action_type: str = Field(description="NONE, RESTAURANT, CATEGORY or URL")
    action_value: str | None = Field(
        default=None, description="Restaurant id, category slug or URL, by action_type"
    )
    sort_order: int


class AdminBannerOut(BannerOut):
    is_active: bool
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str = Field(
        description="LIVE (showing now), SCHEDULED (starts later), EXPIRED or INACTIVE"
    )
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ManagedReelOut(BaseModel):
    """A reel as its vendor and the admin console see it, hidden ones included."""

    id: str
    restaurant_id: str
    restaurant_name: str
    video_url: str
    thumbnail_url: str | None = None
    caption: str | None = None
    duration_seconds: int | None = None
    menu_item_id: str | None = None
    menu_item_name: str | None = None
    is_hidden: bool
    hidden_reason: str | None = None
    uploaded_by: str | None = None
    created_at: datetime
    updated_at: datetime
