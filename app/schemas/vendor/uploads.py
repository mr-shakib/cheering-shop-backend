"""Presigned uploads."""

from pydantic import BaseModel, Field


class PresignedUpload(BaseModel):
    """POST /uploads/presigned-url

    `upload_url` takes a PUT of the raw bytes with a matching `Content-Type`
    header; it points at Cloudflare R2's S3 endpoint and expires.
    `public_url` is a different host — the bucket's public domain — and is
    where the object will be readable afterwards, so it is the value to send
    back to us in `logo_url`, `image_url` and friends.
    """

    upload_url: str
    public_url: str
    key: str
    method: str = "PUT"
    headers: dict[str, str] = Field(
        default_factory=dict, description="Headers that MUST be sent with the upload"
    )
    expires_in: int = Field(description="Seconds until `upload_url` stops working")
