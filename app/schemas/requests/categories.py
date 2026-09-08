"""Administrator curation of the platform browse categories."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Alias = Annotated[str, Field(min_length=1, max_length=80)]


class CategoryCreateRequest(BaseModel):
    """POST /admin/categories — [EXTENDED].

    Vendors create categories implicitly by naming a menu section; this is the
    deliberate path, for seeding a taxonomy ahead of the vendors or adding a
    chip with an image before anyone sells under it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=2048)
    sort_order: int | None = Field(
        default=None, ge=0, le=9999, description="Pin position; omit to leave unpinned"
    )
    aliases: list[Alias] = Field(
        default_factory=list,
        max_length=50,
        description="Other spellings vendors type for this category",
    )
    is_active: bool = True


class CategoryUpdateRequest(BaseModel):
    """PATCH /admin/categories/{id} — [EXTENDED].

    PATCH semantics: an omitted field is left alone. `image_url` and
    `sort_order` are nullable columns, so an explicit `null` clears them —
    `sort_order: null` un-pins. `name` and `is_active` cannot be cleared.

    Renaming keeps the slug: it is the public identifier in deep links and
    filter URLs, and a chip called "Burgers" that used to be "Burger" should
    not break every link already shared.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=2048)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    aliases: list[Alias] | None = Field(
        default=None, max_length=50, description="Replaces the whole list when present"
    )
    is_active: bool | None = None


class CategoryMergeRequest(BaseModel):
    """POST /admin/categories/{id}/merge — [EXTENDED].

    Folds the category in the path into `into_id`: every menu section moves
    over, the old name becomes an alias of the survivor so the same spelling
    resolves there from now on, and the old row is deleted.
    """

    model_config = ConfigDict(extra="forbid")

    into_id: str = Field(description="The category that survives")
