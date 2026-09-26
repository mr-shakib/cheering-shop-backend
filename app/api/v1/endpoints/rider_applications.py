"""Rider applications — [EXTENDED] public endpoints.

The rider app's Become a Rider form: upload documents, submit, then check the
status with the application number. Unauthenticated by design, so every write
is rate limited per source IP, and the status read needs the number AND the
email it was made with.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession
from app.core import rate_limit
from app.core.client import client_ip
from app.core.config import settings
from app.core.responses import ok
from app.schemas.requests import ApplicationUploadRequest, RiderApplicationRequest
from app.services import rider_application_service, storage_service

router = APIRouter(prefix="/rider-applications", tags=["Rider Applications"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Apply to become a rider")
async def submit(body: RiderApplicationRequest, request: Request, db: DbSession):
    """**[EXTENDED]** — creates the application only. No account exists until
    an administrator approves; the applicant is emailed either way. One pending
    application per email. The response carries `application_no`
    (`RDR-482910`): show it on the success screen."""
    await rate_limit.hit(
        rate_limit.rider_application_submit_key(client_ip(request)),
        limit=settings.APPLICATION_SUBMIT_MAX_PER_HOUR,
        window_seconds=3600,
    )
    result = await rider_application_service.submit(db, body)
    await db.commit()
    return ok(result.model_dump())


@router.post("/uploads", summary="Get an upload URL for rider documents")
async def upload(body: ApplicationUploadRequest, request: Request):
    """**[EXTENDED]** — presigned PUT for the NID, licence, photo and payout
    proof. PUT the bytes with the returned `Content-Type`, then send the
    `public_url` in the application's `documents`. PDF is accepted."""
    await rate_limit.hit(
        rate_limit.rider_application_upload_key(client_ip(request)),
        limit=settings.APPLICATION_UPLOAD_MAX_PER_HOUR,
        window_seconds=3600,
    )
    result = storage_service.create_presigned_put(
        "anonymous",
        body.file_type,
        body.file_name,
        root="rider-applications",
        extra_types=storage_service.APPLICATION_EXTRA_TYPES,
    )
    return ok(result.model_dump())


@router.get("/{application_no}", summary="Check rider application status")
async def application_status(
    application_no: str,
    email: Annotated[str, Query(description="The email the application was made with")],
    db: DbSession,
):
    """**[EXTENDED]** — `review_note` is present only when REJECTED."""
    result = await rider_application_service.get_status(db, application_no, email)
    return ok(result.model_dump())
