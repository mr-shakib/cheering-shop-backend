"""Rider applications: submitted publicly, decided by an administrator.

Nothing is created at submission except the application. Approval is the
moment a RIDER account exists, made through the same roster code an
administrator uses to enrol a rider by hand, so the two paths cannot drift.
"""

import secrets
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import VendorApplicationStatus
from app.models.rider_application import RiderApplication
from app.models.user import User
from app.schemas.admin import (
    RiderApplicationOut,
    RiderApplicationStatus,
    RiderApplicationSubmitted,
)
from app.schemas.requests import RiderApplicationRequest, RiderCreateRequest
from app.services import email_service
from app.services.rider import roster

log = structlog.get_logger()

_PENDING = VendorApplicationStatus.PENDING.value


async def _application_no(db: AsyncSession) -> str:
    for _ in range(5):
        candidate = f"RDR-{secrets.randbelow(900_000) + 100_000}"
        taken = await db.scalar(
            select(func.count())
            .select_from(RiderApplication)
            .where(RiderApplication.application_no == candidate)
        )
        if not taken:
            return candidate
    raise RuntimeError("could not allocate an application number")  # pragma: no cover


def to_out(a: RiderApplication) -> RiderApplicationOut:
    return RiderApplicationOut(
        id=str(a.id),
        application_no=a.application_no,
        full_name=a.full_name,
        email=a.email,
        phone=a.phone,
        vehicle_type=a.vehicle_type,
        license_number=a.license_number,
        date_of_birth=a.date_of_birth,
        national_id=a.national_id,
        documents={k: str(v) for k, v in (a.documents or {}).items() if v},
        payout=a.payout or {},
        status=str(a.status),
        review_note=a.review_note,
        reviewed_at=a.reviewed_at,
        rider_id=str(a.user_id) if a.user_id else None,
        submitted_at=a.created_at,
    )


async def _notify(to: str, subject: str, paragraphs: list[str]) -> None:
    """Best effort: the decision is already made and must not roll back
    because an email provider had a bad minute."""
    html = "".join(f"<p>{p}</p>" for p in paragraphs)
    try:
        await email_service.send_email(to, subject, html, "\n\n".join(paragraphs))
    except Exception as exc:
        log.error("rider_application_email_failed", subject=subject, error=str(exc))


async def submit(db: AsyncSession, body: RiderApplicationRequest) -> RiderApplicationSubmitted:
    email = body.email.strip().lower()
    pending = await db.scalar(
        select(func.count())
        .select_from(RiderApplication)
        .where(RiderApplication.email == email, RiderApplication.status == _PENDING)
    )
    if pending:
        raise ConflictError(
            "An application with this email is already waiting for review",
            details=["Check its status with the application number we emailed you"],
        )

    application = RiderApplication(
        application_no=await _application_no(db),
        full_name=body.full_name.strip(),
        email=email,
        phone=body.phone.replace(" ", ""),
        vehicle_type=body.vehicle_type,
        license_number=body.license_number,
        date_of_birth=body.date_of_birth,
        national_id=body.national_id.strip(),
        documents=body.documents.model_dump(exclude_none=True),
        payout=body.payout.model_dump(exclude_none=True),
    )
    db.add(application)
    await db.flush()
    await db.refresh(application)
    log.info("rider_application_submitted", application_no=application.application_no)

    brand = settings.EMAIL_FROM_NAME
    await _notify(
        email,
        f"We received your {brand} rider application",
        [
            f"Thanks for applying to ride with {brand}.",
            f"Your application number is {application.application_no}. Keep it — "
            "you need it to check your status.",
            "We review every application by hand and will email you with the decision.",
        ],
    )
    return RiderApplicationSubmitted(
        application_no=application.application_no,
        status=str(application.status),
        message="Application received. We will email you once it has been reviewed.",
    )


async def get_status(db: AsyncSession, application_no: str, email: str) -> RiderApplicationStatus:
    """Reference AND email must match; either wrong is the same 404."""
    application = await db.scalar(
        select(RiderApplication).where(
            RiderApplication.application_no == application_no.strip().upper(),
            RiderApplication.email == email.strip().lower(),
        )
    )
    if application is None:
        raise NotFoundError("No application matches that number and email")
    return RiderApplicationStatus(
        application_no=application.application_no,
        status=str(application.status),
        review_note=application.review_note
        if str(application.status) == VendorApplicationStatus.REJECTED
        else None,
        submitted_at=application.created_at,
        reviewed_at=application.reviewed_at,
    )


async def admin_list(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = _PENDING,
    q: str | None = None,
    vehicle_type: str | None = None,
) -> tuple[list[RiderApplicationOut], int]:
    """The review queue, oldest first."""
    from app.services.admin.common import like_pattern

    conditions: list[ColumnElement[bool]] = []
    if status:
        try:
            conditions.append(
                RiderApplication.status == VendorApplicationStatus(status.upper()).value
            )
        except ValueError:
            raise ValidationError("status must be PENDING, APPROVED or REJECTED") from None
    if q and q.strip():
        pattern = like_pattern(q.strip())
        conditions.append(
            or_(
                RiderApplication.full_name.ilike(pattern),
                RiderApplication.phone.ilike(pattern),
                RiderApplication.email.ilike(pattern),
                RiderApplication.application_no.ilike(pattern),
            )
        )
    if vehicle_type:
        conditions.append(RiderApplication.vehicle_type == vehicle_type.strip().upper())

    total = await db.scalar(select(func.count()).select_from(RiderApplication).where(*conditions))
    rows = await db.scalars(
        select(RiderApplication)
        .where(*conditions)
        .order_by(RiderApplication.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return [to_out(a) for a in rows.all()], int(total or 0)


async def _get(
    db: AsyncSession, application_id: uuid.UUID, *, lock: bool = False
) -> RiderApplication:
    application = await db.get(RiderApplication, application_id, with_for_update=lock)
    if application is None:
        raise NotFoundError("Application not found")
    return application


async def admin_get(db: AsyncSession, application_id: uuid.UUID) -> RiderApplicationOut:
    return to_out(await _get(db, application_id))


async def _pending(db: AsyncSession, application_id: uuid.UUID) -> RiderApplication:
    application = await _get(db, application_id, lock=True)
    if str(application.status) != _PENDING:
        raise ConflictError(f"This application is already {str(application.status).lower()}")
    return application


async def approve(
    db: AsyncSession,
    admin: User,
    application_id: uuid.UUID,
    note: str | None,
    password: str | None,
) -> RiderApplicationOut:
    """Create the RIDER account and its profile, copying the application's
    identity fields across. Verified (cleared to carry food) but off shift:
    the rider goes online themselves when they start work."""
    application = await _pending(db, application_id)
    rider = await roster.create_rider(
        db,
        RiderCreateRequest(
            full_name=application.full_name,
            email=application.email,
            phone=application.phone,
            password=password,
            vehicle_type=application.vehicle_type,
            license_number=application.license_number,
            is_online=False,
            is_verified=True,
        ),
    )
    _, profile = await roster.get_rider(db, uuid.UUID(rider.id))
    profile.date_of_birth = application.date_of_birth
    profile.national_id = application.national_id
    profile.documents = dict(application.documents or {})
    profile.payout = dict(application.payout or {})
    rider_user = await db.get(User, uuid.UUID(rider.id))
    if rider_user is not None and application.documents.get("profile_photo"):
        rider_user.avatar_url = application.documents["profile_photo"]

    application.status = VendorApplicationStatus.APPROVED.value
    application.review_note = note
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(UTC)
    application.user_id = uuid.UUID(rider.id)
    await db.flush()
    log.info("rider_application_approved", application_no=application.application_no)

    sign_in = (
        "Sign in to the rider app with this email and the password our team gave you."
        if password
        else "Our team will contact you with your sign-in details."
    )
    await _notify(
        application.email,
        f"Welcome to {settings.EMAIL_FROM_NAME}: your rider account is ready",
        [f"Good news, {application.full_name}: your rider application was approved.", sign_in],
    )
    return to_out(application)


async def reject(
    db: AsyncSession, admin: User, application_id: uuid.UUID, note: str
) -> RiderApplicationOut:
    application = await _pending(db, application_id)
    application.status = VendorApplicationStatus.REJECTED.value
    application.review_note = note
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(UTC)
    await db.flush()
    log.info("rider_application_rejected", application_no=application.application_no)
    await _notify(
        application.email,
        f"About your {settings.EMAIL_FROM_NAME} rider application",
        [
            "Thank you for applying. After review we are unable to approve your "
            "application at this time.",
            f"Reason: {note}",
            "Reply to this email if you can address the reason above.",
        ],
    )
    return to_out(application)
