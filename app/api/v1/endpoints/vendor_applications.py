"""Vendor partner applications — [EXTENDED] public endpoints.

The partner app's registration flow: five form steps, one submission, an
application number on the success screen, and a status check while waiting.
Everything here is **unauthenticated by design** — the applicant does not have
an account yet — which is why every write is rate limited per source IP and the
status read requires the reference *and* the owner's email.

Registered before `vendor.router` so these paths are matched as literals;
nothing in `/vendor/**` takes a path parameter at this level, but the ordering
keeps that true by construction rather than by luck.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DbSession
from app.core import rate_limit
from app.core.client import client_ip
from app.core.config import settings
from app.core.responses import ok
from app.models.enums import OtpPurpose
from app.schemas.requests import ApplicationUploadRequest, VendorApplicationRequest
from app.services import otp_service, storage_service, vendor_application_service

router = APIRouter(prefix="/vendor/applications", tags=["Vendor Applications"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Submit a partner application")
async def submit_application(body: VendorApplicationRequest, request: Request, db: DbSession):
    """**[EXTENDED]** — the Review & Submit step of the application form.

    Call `POST /auth/otp/send` with `role: "VENDOR"` and the owner's email at
    the Owner Information step; the code arrives by email and is redeemed here.

    One transaction creates three things: the application record an
    administrator reviews, a VENDOR account **without a password**, and an
    unverified, CLOSED restaurant. The applicant cannot sign in yet — approval
    emails them instructions to set a password via `/auth/password/forgot`.

    The response carries `application_no` (`PTN-88291`) — show it on the
    success screen and tell the user to keep it.
    """
    await rate_limit.hit(
        rate_limit.application_submit_key(client_ip(request)),
        limit=settings.APPLICATION_SUBMIT_MAX_PER_HOUR,
        window_seconds=3600,
    )

    email = otp_service.normalise_identifier(body.owner.email)
    body.owner.email = email
    await otp_service.verify_and_consume(db, email, body.otp_code, OtpPurpose.SIGNUP)

    application, _ = await vendor_application_service.submit(db, body)
    await db.commit()
    return ok(vendor_application_service.to_submitted(application).model_dump())


@router.post("/uploads", summary="Get an upload URL for application documents")
async def application_upload(body: ApplicationUploadRequest, request: Request):
    """**[EXTENDED]** — presigned PUT for the Document step.

    `POST /uploads/presigned-url` requires a session, and an applicant does not
    have one yet. Same mechanics — PUT the raw bytes with the returned
    `Content-Type` header, then place `public_url` into the application's
    `documents` block. PDF is accepted here on top of the image types, because
    a trade licence is routinely a scan.

    Keys land under `applications/…`, never `uploads/{user_id}/…`, so an
    anonymous caller cannot collide with any user's objects.
    """
    await rate_limit.hit(
        rate_limit.application_upload_key(client_ip(request)),
        limit=settings.APPLICATION_UPLOAD_MAX_PER_HOUR,
        window_seconds=3600,
    )
    result = storage_service.create_presigned_put(
        "anonymous",
        body.file_type,
        body.file_name,
        root="applications",
        extra_types=storage_service.APPLICATION_EXTRA_TYPES,
    )
    return ok(result.model_dump())


@router.get("/{application_no}", summary="Check application status")
async def application_status(
    application_no: str,
    email: Annotated[str, Query(description="The owner email the application was made with")],
    db: DbSession,
):
    """**[EXTENDED]** — poll while waiting for the 2–3 business-day review.

    Requires the reference AND the matching owner email; either one wrong is
    the same 404, so the reference space cannot be walked to learn who applied.
    `review_note` is present only on REJECTED applications.
    """
    result = await vendor_application_service.get_status(
        db, application_no, otp_service.normalise_identifier(email)
    )
    return ok(result.model_dump())
