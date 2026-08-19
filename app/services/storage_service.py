"""Presigned S3 uploads — spec #47.

Spec §2 is explicit that the backend never touches image bytes: the client PUTs
straight to S3/CDN and sends us back the resulting URL. That is not only a
bandwidth decision — it keeps a 10 MB photo from occupying an API worker for the
length of a mobile upload.

**SigV4 is implemented here rather than pulled in with boto3.** A presigned URL
is a deterministic HMAC chain over a canonical request; that is roughly forty
lines, it is exercised by a test with fixed inputs, and it costs the deployment
no new dependency. boto3 would earn its place the moment we needed anything else
from AWS — today we do not.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import structlog

from app.core.config import settings
from app.core.errors import AppError, ValidationError
from app.schemas.vendor import PresignedUpload

log = structlog.get_logger()

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "s3"

# MIME type -> file extension. Restricted to the image types the config allows;
# an extension is what makes the object render inline in a browser rather than
# download as an opaque blob.
_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
}

# Accepted for partner-application documents on top of ALLOWED_UPLOAD_TYPES:
# a trade licence is routinely a PDF scan, never a photo.
APPLICATION_EXTRA_TYPES = frozenset({"application/pdf"})


class StorageNotConfiguredError(AppError):
    """Object storage has no bucket configured.

    A 503, not a 500: nothing is broken, the feature simply is not provisioned
    in this environment. The distinction matters to whoever is on call.
    """

    status_code = 503
    code = "STORAGE_NOT_CONFIGURED"
    message = (
        "File uploads are not configured on this server. "
        "Set S3_BUCKET and AWS credentials to enable them."
    )


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str) -> bytes:
    """The SigV4 key derivation chain: date -> region -> service -> request."""
    k_date = _sign(f"AWS4{secret}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, _SERVICE)
    return _sign(k_service, "aws4_request")


def build_object_key(
    user_id: str, file_type: str, file_name: str | None = None, *, root: str = "uploads"
) -> str:
    """Namespace every upload under its uploader.

    The random component is what stops one vendor overwriting another's image by
    guessing a filename, and it also means a re-upload never collides with a
    cached copy of the old object. The client-supplied name is never used as the
    key — only to recover an extension.

    `root` separates authenticated uploads (`uploads/{user_id}/…`) from
    partner-application documents (`applications/…`), which are accepted before
    any account exists and must not be able to collide with user objects.
    """
    extension = _EXTENSIONS.get(file_type)
    if extension is None and file_name and "." in file_name:
        candidate = file_name.rsplit(".", 1)[-1].lower()
        extension = candidate if candidate.isalnum() and len(candidate) <= 5 else None
    suffix = f".{extension}" if extension else ""
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    return f"{root}/{user_id}/{today}/{uuid.uuid4().hex}{suffix}"


def _public_url(key: str) -> str:
    if settings.S3_ENDPOINT_URL:
        return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{settings.S3_BUCKET}/{key}"
    return f"https://{settings.S3_BUCKET}.s3.{settings.S3_REGION}.amazonaws.com/{key}"


def _host_and_base(key: str) -> tuple[str, str]:
    """Return `(host, base_url)` for the object, honouring a custom endpoint.

    A custom `S3_ENDPOINT_URL` (MinIO, R2, Spaces) is path-style; real S3 is
    virtual-hosted. The canonical request must be built against whichever one
    the request will actually be sent to, or the signature will not match.
    """
    if settings.S3_ENDPOINT_URL:
        endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
        scheme, _, remainder = endpoint.partition("://")
        host = remainder or scheme
        return host, f"{endpoint}/{settings.S3_BUCKET}/{key}"
    host = f"{settings.S3_BUCKET}.s3.{settings.S3_REGION}.amazonaws.com"
    return host, f"https://{host}/{key}"


def create_presigned_put(
    user_id: str,
    file_type: str,
    file_name: str | None = None,
    ttl: int | None = None,
    *,
    root: str = "uploads",
    extra_types: frozenset[str] = frozenset(),
) -> PresignedUpload:
    """Spec #47. A time-limited URL the client PUTs raw bytes to.

    `file_type` is validated against `ALLOWED_UPLOAD_TYPES` (plus any
    caller-supplied `extra_types`) and then **signed into the URL** as
    `Content-Type`. Validating without signing would be theatre: the client
    could declare `image/png` to us and upload an HTML document, turning our
    bucket into a host for arbitrary content on our own domain. Because the
    header is part of the signature, a mismatched upload is rejected by S3
    itself.
    """
    allowed = set(settings.ALLOWED_UPLOAD_TYPES) | extra_types
    if file_type not in allowed:
        raise ValidationError(
            f"'{file_type}' cannot be uploaded",
            details=[f"Allowed types: {', '.join(sorted(allowed))}"],
        )
    if not settings.S3_BUCKET or not settings.AWS_ACCESS_KEY_ID:
        raise StorageNotConfiguredError()

    expires = ttl or settings.PRESIGNED_URL_TTL_SECONDS
    key = build_object_key(user_id, file_type, file_name, root=root)
    host, base_url = _host_and_base(key)

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{settings.S3_REGION}/{_SERVICE}/aws4_request"

    # Content-Type is signed, so it is part of the promise the URL encodes.
    signed_headers = "content-type;host"
    canonical_uri = "/" + quote(key, safe="/")
    if settings.S3_ENDPOINT_URL:
        canonical_uri = f"/{settings.S3_BUCKET}" + canonical_uri

    query = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{settings.AWS_ACCESS_KEY_ID}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": signed_headers,
    }
    canonical_query = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(query.items())
    )
    canonical_headers = f"content-type:{file_type}\nhost:{host}\n"
    canonical_request = "\n".join(
        [
            "PUT",
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            _ALGORITHM,
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(settings.AWS_SECRET_ACCESS_KEY, datestamp, settings.S3_REGION),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    log.info("presigned_upload_issued", user_id=user_id, key=key, file_type=file_type)
    return PresignedUpload(
        upload_url=f"{base_url}?{canonical_query}&X-Amz-Signature={signature}",
        public_url=_public_url(key),
        key=key,
        headers={"Content-Type": file_type},
        expires_in=expires,
    )
