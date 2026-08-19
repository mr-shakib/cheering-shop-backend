"""Uploads — spec endpoint #47."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.responses import ok
from app.schemas.requests import PresignedUrlRequest
from app.services import storage_service

router = APIRouter(prefix="/uploads", tags=["Uploads"])


@router.post("/presigned-url", summary="Get an S3 presigned upload URL")
async def create_presigned_url(body: PresignedUrlRequest, user: CurrentUser):
    """Spec #47. The backend never touches image bytes (spec §2) — the client
    uploads straight to S3/CDN.

    `file_type` is validated against `ALLOWED_UPLOAD_TYPES` **and signed into
    the URL** as `Content-Type`. Validating without signing would be theatre:
    a client could declare `image/png` to us and PUT an HTML document, turning
    the bucket into a host for arbitrary content on our own domain. Because the
    header is part of the SigV4 signature, S3 itself rejects a mismatch.

    Open to any authenticated user, not just vendors: customers need it for
    avatars and, later, review photos. The object key is namespaced under the
    caller's id, so one user cannot overwrite another's upload.

    Returns 503 when no bucket is configured — nothing is broken, the feature
    simply is not provisioned in this environment.
    """
    result = storage_service.create_presigned_put(str(user.id), body.file_type, body.file_name)
    return ok(result.model_dump())
