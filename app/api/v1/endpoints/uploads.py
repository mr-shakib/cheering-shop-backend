"""Uploads — spec endpoint #47."""

from fastapi import APIRouter

from app.api.deps import VendorUser
from app.core.errors import NotImplementedYetError
from app.schemas.requests import PresignedUrlRequest

router = APIRouter(prefix="/uploads", tags=["Uploads"])


@router.post("/presigned-url", summary="Get an S3 presigned upload URL")
async def create_presigned_url(body: PresignedUrlRequest, user: VendorUser):
    """Spec #47. The backend never touches image bytes (spec §2) — the client
    uploads straight to S3/CDN. `file_type` is validated against
    ALLOWED_UPLOAD_TYPES so the URL cannot be used to host arbitrary content."""
    raise NotImplementedYetError()
