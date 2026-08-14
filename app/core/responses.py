"""Standard response envelope (spec §2).

    { "success": true, "data": {...}, "meta": {"total": 100, "page": 1} }

`SuccessResponse` is generic so OpenAPI documents the real payload shape rather
than a bare object — clients generating typed SDKs get the actual `data` type.
"""

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int = Field(description="Total rows matching the query, ignoring pagination")
    limit: int
    offset: int
    page: int = Field(description="1-indexed page number, derived from limit/offset")
    has_more: bool


class SuccessResponse[T](BaseModel):
    success: bool = True
    data: T
    meta: PageMeta | dict | None = None


def ok(data: object, meta: PageMeta | dict | None = None) -> dict:
    """Build the success envelope.

    Endpoints should prefer returning ``SuccessResponse[Model]`` so the schema is
    documented; this helper exists for the handful of responses whose shape is
    genuinely dynamic (e.g. the aggregated /home/feed).
    """
    payload: dict = {"success": True, "data": data}
    if meta is not None:
        payload["meta"] = meta.model_dump() if isinstance(meta, PageMeta) else meta
    return payload


def paginated(items: list, total: int, limit: int, offset: int) -> dict:
    return ok(
        items,
        PageMeta(
            total=total,
            limit=limit,
            offset=offset,
            page=(offset // limit) + 1 if limit else 1,
            has_more=offset + len(items) < total,
        ),
    )
