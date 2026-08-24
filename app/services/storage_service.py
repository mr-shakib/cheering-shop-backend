"""Presigned uploads to Cloudflare R2 — spec #47.

Spec §2 is explicit that the backend never touches image bytes: the client PUTs
straight to object storage and sends us back the resulting URL. That is not only
a bandwidth decision — it keeps a 10 MB photo from occupying an API worker for
the length of a mobile upload.

R2 speaks the S3 API, so what follows is plain SigV4. **It is implemented here
rather than pulled in with boto3**: a presigned URL is a deterministic HMAC chain
over a canonical request; that is roughly forty lines, it is exercised by a test
with fixed inputs, and it costs the deployment no new dependency. Now that the
only object store we talk to is R2, an AWS SDK has even less claim to a place in
the image.

Three things R2 does differently from S3, all of which this module has to know:

* **The region in the signature is always `auto`.** R2 has no regions in the S3
  sense; a real region name in the credential scope fails the signature check.
* **Addressing is path-style** — `…r2.cloudflarestorage.com/{bucket}/{key}` —
  so the bucket is part of the canonical URI, not the host.
* **The S3 endpoint is not publicly readable.** An R2 bucket is private until a
  domain is bound to it, and the signing endpoint always requires auth. So
  `public_url` cannot be derived from the endpoint the way it could on S3 — it
  comes from `R2_PUBLIC_BASE_URL`. Getting this wrong is silent: the upload
  succeeds and every reader of the returned URL gets a 401.
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

# R2 has no regions in the S3 sense — the credential scope is always "auto",
# and a real region name here fails the signature check. Not configurable
# because there is nothing to configure.
_REGION = "auto"

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
    """Object storage has no R2 bucket configured.

    A 503, not a 500: nothing is broken, the feature simply is not provisioned
    in this environment. The distinction matters to whoever is on call.
    """

    status_code = 503
    code = "STORAGE_NOT_CONFIGURED"
    message = (
        "File uploads are not configured on this server. "
        "Set the Cloudflare R2 variables to enable them."
    )


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str = _REGION) -> bytes:
    """The SigV4 key derivation chain: date -> region -> service -> request.

    `region` is always `_REGION` in production — R2 accepts nothing else. It
    stays a parameter so the chain can be checked against AWS's published
    SigV4 test vectors, which are naturally in a real region.
    """
    k_date = _sign(f"AWS4{secret}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, _SERVICE)
    return _sign(k_service, "aws4_request")


def missing_config() -> list[str]:
    """Which R2 settings are unset.

    Named individually because "storage is not configured" sends whoever is on
    call to read source, whereas a list of variables sends them to the
    environment file. `R2_PUBLIC_BASE_URL` counts as required: without it an
    upload lands bytes that nothing can read back, which is not a working
    feature.
    """
    required = {
        "R2_BUCKET": settings.R2_BUCKET,
        "R2_ACCESS_KEY_ID": settings.R2_ACCESS_KEY_ID,
        "R2_SECRET_ACCESS_KEY": settings.R2_SECRET_ACCESS_KEY,
        "R2_PUBLIC_BASE_URL": settings.R2_PUBLIC_BASE_URL,
    }
    # Only one of the two is needed: an explicit endpoint makes the account id
    # redundant, since the account id exists purely to build that endpoint.
    if not settings.R2_ENDPOINT_URL:
        required["R2_ACCOUNT_ID"] = settings.R2_ACCOUNT_ID
    return sorted(name for name, value in required.items() if not value)


def check_storage_config() -> dict:
    """Readiness detail, mirroring `check_email_config`.

    Reported but not gating: a bucket that is not provisioned must not pull the
    node out of the load balancer when browsing and ordering work perfectly
    well without it.
    """
    missing = missing_config()
    if not missing:
        return {"status": "ok", "provider": "cloudflare-r2", "bucket": settings.R2_BUCKET}
    if settings.ENVIRONMENT in {"local", "test"}:
        return {"status": "disabled", "detail": f"unset: {', '.join(missing)} (fine locally)"}
    return {"status": "error", "detail": f"unset: {', '.join(missing)}"}


def _endpoint() -> str:
    """The S3-API endpoint the presigned URL is signed against.

    Derived from the account id, because that is the only part that varies for
    the ordinary case. `R2_ENDPOINT_URL` overrides it for a jurisdiction-locked
    bucket (`<account>.eu.r2.cloudflarestorage.com`) or for pointing a local
    stack at MinIO.
    """
    if settings.R2_ENDPOINT_URL:
        return settings.R2_ENDPOINT_URL.rstrip("/")
    return f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


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
    """Where the object is readable once the PUT has landed.

    Deliberately not built from `_endpoint()`: R2's S3 API refuses
    unauthenticated GETs, so such a URL would 401 for every reader. Public
    delivery is whatever domain is bound to the bucket in the Cloudflare
    dashboard — the managed `pub-<hash>.r2.dev` subdomain, or a custom one like
    `cdn.cheeringshop.online`.
    """
    return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{quote(key, safe='/')}"


def _host_and_base(key: str) -> tuple[str, str]:
    """Return `(host, base_url)` for the signed PUT.

    R2 is path-style, so the bucket sits in the path and the host is the
    endpoint's alone. The canonical request must be built against the URL the
    request will actually be sent to, or the signature will not match.
    """
    endpoint = _endpoint()
    scheme, _, remainder = endpoint.partition("://")
    host = remainder or scheme
    return host, f"{endpoint}/{settings.R2_BUCKET}/{key}"


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
    header is part of the signature, a mismatched upload is rejected by R2
    itself.
    """
    allowed = set(settings.ALLOWED_UPLOAD_TYPES) | extra_types
    if file_type not in allowed:
        raise ValidationError(
            f"'{file_type}' cannot be uploaded",
            details=[f"Allowed types: {', '.join(sorted(allowed))}"],
        )
    missing = missing_config()
    if missing:
        raise StorageNotConfiguredError(details=[f"Unset: {', '.join(missing)}"])

    expires = ttl or settings.PRESIGNED_URL_TTL_SECONDS
    key = build_object_key(user_id, file_type, file_name, root=root)
    host, base_url = _host_and_base(key)

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{_REGION}/{_SERVICE}/aws4_request"

    # Content-Type is signed, so it is part of the promise the URL encodes.
    signed_headers = "content-type;host"
    canonical_uri = f"/{settings.R2_BUCKET}/" + quote(key, safe="/")

    query = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{settings.R2_ACCESS_KEY_ID}/{scope}",
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
        _signing_key(settings.R2_SECRET_ACCESS_KEY, datestamp),
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
