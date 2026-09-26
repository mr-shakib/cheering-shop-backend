"""Community posts, for the feed and for moderation."""

from datetime import datetime

from pydantic import BaseModel, Field


class PostAuthor(BaseModel):
    id: str
    full_name: str | None = None
    avatar_url: str | None = None


class PostRestaurant(BaseModel):
    id: str
    name: str


class CommunityPostOut(BaseModel):
    id: str
    author: PostAuthor
    body: str
    image_urls: list[str] = Field(default_factory=list)
    restaurant: PostRestaurant | None = None
    is_mine: bool = False
    reported_by_me: bool = False
    created_at: datetime


class ModeratedPostOut(CommunityPostOut):
    """The Community moderation table."""

    report_count: int
    author_is_active: bool = Field(description="false once the author is banned")
    is_removed: bool
    removed_at: datetime | None = None
    removal_reason: str | None = None
