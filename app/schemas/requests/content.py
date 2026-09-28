"""Reels and app banners — [EXTENDED].

Media is uploaded first (`POST /vendor/reels/uploads` or
`POST /admin/uploads/presigned-url`) and the resulting `public_url` sent here.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReelCreateRequest(BaseModel):
    """POST /vendor/reels"""

    model_config = ConfigDict(extra="forbid")

    video_url: str = Field(min_length=1, max_length=2048)
    thumbnail_url: str | None = Field(
        default=None, max_length=2048, description="Poster frame shown while the video loads"
    )
    caption: str | None = Field(default=None, max_length=300)
    duration_seconds: int | None = Field(default=None, ge=1, le=600)
    menu_item_id: uuid.UUID | None = Field(
        default=None, description="The dish the video shows; must be on this restaurant's menu"
    )


class AdminReelCreateRequest(ReelCreateRequest):
    """POST /admin/reels — the same, for any restaurant."""

    restaurant_id: uuid.UUID


class ReelUpdateRequest(BaseModel):
    """PATCH /admin/reels/{id} — edit, or hide from the feed without deleting."""

    model_config = ConfigDict(extra="forbid")

    caption: str | None = Field(default=None, max_length=300)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    menu_item_id: uuid.UUID | None = None
    is_hidden: bool | None = None
    hidden_reason: str | None = Field(
        default=None, max_length=255, description="Shown to the vendor on their reel list"
    )

    @model_validator(mode="after")
    def _needs_a_field(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        return self


BannerMediaType = Literal["IMAGE", "GIF", "LOTTIE"]
BannerAction = Literal["NONE", "RESTAURANT", "CATEGORY", "URL"]
# Free-form so the apps can add a slot without a backend change, but shaped
# like an identifier so typos are visible: HOME, HOME_MIDDLE, OFFERS, ...
_PLACEMENT = r"^[A-Z][A-Z0-9_]{1,39}$"


class _BannerFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120, description="Admin label and alt text")
    media_url: str = Field(min_length=1, max_length=2048)
    media_type: BannerMediaType | None = Field(
        default=None,
        description="IMAGE, GIF or LOTTIE. Omit to infer from the URL's extension "
        "(.gif → GIF, .json → LOTTIE, anything else → IMAGE)",
    )
    placement: str = Field(default="HOME", pattern=_PLACEMENT)
    action_type: BannerAction = "NONE"
    action_value: str | None = Field(
        default=None,
        max_length=2048,
        description="RESTAURANT: its id. CATEGORY: its slug. URL: an http(s) link",
    )
    sort_order: int = Field(default=0, ge=0, le=9999, description="Lowest first")
    is_active: bool = True
    starts_at: datetime | None = Field(default=None, description="Hidden before this")
    ends_at: datetime | None = Field(default=None, description="Hidden from this moment")


class BannerCreateRequest(_BannerFields):
    """POST /admin/banners"""


class BannerUpdateRequest(BaseModel):
    """PATCH /admin/banners/{id} — omitted fields are left alone; send null to
    clear `starts_at`, `ends_at` or `action_value`."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    media_url: str | None = Field(default=None, min_length=1, max_length=2048)
    media_type: BannerMediaType | None = None
    placement: str | None = Field(default=None, pattern=_PLACEMENT)
    action_type: BannerAction | None = None
    action_value: str | None = Field(default=None, max_length=2048)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _needs_a_field(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        return self
