"""Vendor partner applications — submission, status, and the admin decision.

**How this relates to `storefront.register_vendor`.** Both create a VENDOR
account and an unverified restaurant. The difference is what the caller holds
afterwards: registration is the API fast path (password up front, tokens back,
menu-building immediately), while an application is the *product* path the
partner app ships — no password, an application number the applicant can quote,
a document bundle for the reviewer, and credentials only once a human approves.
The two share the same underlying invariants: one restaurant per account, roles
fixed at creation, `is_verified` flipped only by an administrator.

The applicant's account exists from the moment of submission but has **no
password**, so it cannot be signed into. Approval emails the owner
instructions to set one via the OTP reset flow — which is also why rejection
needs no account teardown: a passwordless account owning an unverified,
CLOSED restaurant can do nothing.
"""

import secrets
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import UserRole, VendorApplicationStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.vendor_application import VendorApplication
from app.schemas.requests import VendorApplicationRequest
from app.schemas.vendor import (
    VendorApplicationDetail,
    VendorApplicationSubmitted,
)
from app.schemas.vendor import (
    VendorApplicationStatus as VendorApplicationStatusOut,
)
from app.services import email_service
from app.services.vendor import storefront

log = structlog.get_logger()


async def _generate_application_no(db: AsyncSession) -> str:
    """A short, human-quotable reference like ``PTN-88291``.

    Five random digits first — that is what fits on the success screen and in a
    phone call to support. On the (unlikely, then increasingly likely as the
    marketplace grows) collision, widen a digit at a time rather than loop
    forever in an exhausted space.
    """
    for digits in (5, 5, 5, 6, 6, 7):
        low = 10 ** (digits - 1)
        candidate = f"PTN-{secrets.randbelow(9 * low) + low}"
        exists = await db.scalar(
            select(func.count())
            .select_from(VendorApplication)
            .where(VendorApplication.application_no == candidate)
        )
        if not exists:
            return candidate
    raise RuntimeError("could not allocate an application number")  # pragma: no cover


async def _resolve_applicant(db: AsyncSession, body: VendorApplicationRequest) -> User:
    """Find or create the VENDOR account this application belongs to.

    The OTP has already been redeemed for the owner's email, so the address is
    verified. A provisional row from `/auth/otp/send` is completed in place.
    """
    from app.services.auth_service import find_by_identifier

    email = body.owner.email
    user = await find_by_identifier(db, email)

    if user is not None and user.role != UserRole.VENDOR:
        raise ConflictError(
            "This email is already registered as a customer account. "
            "Use a different address for your business."
        )

    phone = body.owner.phone.replace(" ", "")
    phone_owner = await find_by_identifier(db, phone)
    if phone_owner is not None and (user is None or phone_owner.id != user.id):
        raise ConflictError("This phone number is already registered to another account")

    if user is None:
        user = User(role=UserRole.VENDOR.value, email=email)
        db.add(user)

    user.is_email_verified = True
    user.full_name = body.owner.full_name
    if user.phone is None:
        user.phone = phone
    await db.flush()
    return user


async def submit(
    db: AsyncSession, body: VendorApplicationRequest
) -> tuple[VendorApplication, Restaurant]:
    """Create the application, its VENDOR account, and its restaurant.

    One transaction: an application without an account has nobody to approve,
    and an account without an application row gives the reviewer nothing to
    review. The caller commits.
    """
    if not body.agreed_to_terms:
        raise ValidationError(
            "You must agree to the Partner Terms & Conditions",
            details=["agreed_to_terms must be true"],
        )

    user = await _resolve_applicant(db, body)

    existing = await db.scalar(
        select(VendorApplication).where(VendorApplication.user_id == user.id)
    )
    if existing is not None:
        raise ConflictError(
            f"An application for this email already exists ({existing.application_no}). "
            "Its status can be checked with that reference."
        )
    if await db.scalar(select(Restaurant).where(Restaurant.owner_id == user.id)) is not None:
        raise ConflictError("This account already has a restaurant")

    restaurant = Restaurant(
        owner_id=user.id,
        name=body.business.name,
        slug=await storefront._unique_slug(db, storefront.slugify(body.business.name)),
        phone=body.owner.phone.replace(" ", ""),
        address_line=body.location.address_line,
        latitude=body.location.latitude,
        longitude=body.location.longitude,
        cuisine_types=[c.strip() for c in body.business.cuisine_types if c.strip()],
        # Invisible to customers until approval; CLOSED until the vendor opens it.
        is_verified=False,
        status="CLOSED",
        commission_rate=storefront.default_commission_rate(),
    )
    db.add(restaurant)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("This account already has a restaurant") from exc

    application = VendorApplication(
        application_no=await _generate_application_no(db),
        user_id=user.id,
        restaurant_id=restaurant.id,
        business_name=body.business.name,
        business_type=body.business.business_type,
        business_category=body.business.business_category,
        branch_count=body.business.branch_count,
        cuisine_types=[c.strip() for c in body.business.cuisine_types if c.strip()],
        address_line=body.location.address_line,
        area=body.location.area,
        latitude=body.location.latitude,
        longitude=body.location.longitude,
        owner_full_name=body.owner.full_name,
        owner_email=body.owner.email,
        owner_phone=body.owner.phone.replace(" ", ""),
        national_id=body.owner.national_id,
        documents={k: v for k, v in body.documents.model_dump().items() if v},
        payout=body.payout.model_dump(exclude_none=True),
        agreed_to_terms=True,
    )
    db.add(application)
    await db.flush()

    log.info(
        "vendor_application_submitted",
        application_no=application.application_no,
        user_id=str(user.id),
        restaurant_id=str(restaurant.id),
        business_type=application.business_type,
    )
    await _notify(
        application.owner_email,
        email_service.application_received(application.application_no, application.business_name),
    )
    return application, restaurant


async def _notify(to: str, message: tuple[str, str, str]) -> None:
    """Send a lifecycle email, never letting delivery decide the request.

    The state change is already flushed; a Resend outage should show up in the
    logs, not roll back an approval that has in fact happened.
    """
    subject, html, text = message
    try:
        await email_service.send_email(to, subject, html, text)
    except Exception as exc:
        log.error("application_email_failed", subject=subject, error=str(exc))


# ---------------------------------------------------------------------------
# Applicant-facing reads
# ---------------------------------------------------------------------------


async def get_status(
    db: AsyncSession, application_no: str, email: str
) -> VendorApplicationStatusOut:
    """Status by reference + owner email.

    Both must match, and a wrong email returns the same 404 as a wrong
    reference — the pair is what stops the five-digit space being walked to
    enumerate who has applied.
    """
    application = await db.scalar(
        select(VendorApplication).where(
            VendorApplication.application_no == application_no.strip().upper(),
            VendorApplication.owner_email == email.strip(),
        )
    )
    if application is None:
        raise NotFoundError("No application found for that reference and email")
    return VendorApplicationStatusOut(
        application_no=application.application_no,
        business_name=application.business_name,
        status=str(application.status),
        submitted_at=application.created_at,
        reviewed_at=application.reviewed_at,
        review_note=(
            application.review_note
            if str(application.status) == VendorApplicationStatus.REJECTED
            else None
        ),
    )


def to_submitted(application: VendorApplication) -> VendorApplicationSubmitted:
    return VendorApplicationSubmitted(
        application_no=application.application_no,
        status=str(application.status),
        restaurant_id=str(application.restaurant_id),
        submitted_at=application.created_at,
        message=(
            "Application submitted! We'll review it and get back to you within "
            "2–3 business days by email."
        ),
    )


# ---------------------------------------------------------------------------
# Admin review
# ---------------------------------------------------------------------------


async def list_applications(
    db: AsyncSession, status_filter: str | None, limit: int, offset: int
) -> tuple[list[VendorApplication], int]:
    """The review queue, oldest first. Defaults to PENDING — that is the work."""
    where = []
    if status_filter is not None:
        try:
            where.append(
                VendorApplication.status == VendorApplicationStatus(status_filter.upper()).value
            )
        except ValueError:
            valid = ", ".join(s.value for s in VendorApplicationStatus)
            raise ValidationError(f"Unknown status. Valid values: {valid}") from None

    total = await db.scalar(
        select(func.count()).select_from(VendorApplication).where(*where)
    )
    result = await db.execute(
        select(VendorApplication)
        .where(*where)
        .order_by(VendorApplication.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total or 0


async def _get_pending(db: AsyncSession, application_id) -> VendorApplication:
    application = await db.get(VendorApplication, application_id)
    if application is None:
        raise NotFoundError("Application not found")
    if str(application.status) != VendorApplicationStatus.PENDING:
        raise ValidationError(
            f"This application has already been "
            f"{'approved' if str(application.status) == 'APPROVED' else 'rejected'}"
        )
    return application


async def get_detail(db: AsyncSession, application_id) -> VendorApplicationDetail:
    application = await db.get(VendorApplication, application_id)
    if application is None:
        raise NotFoundError("Application not found")
    return to_detail(application)


async def approve(
    db: AsyncSession, application_id, admin: User, note: str | None
) -> VendorApplication:
    """Approve: the restaurant becomes verified, the owner is told how to sign in.

    Verification alone does not open the store — `status` stays CLOSED until
    the vendor themselves flips it, so approval can never surprise a kitchen
    with live orders.
    """
    application = await _get_pending(db, application_id)

    restaurant = await db.get(Restaurant, application.restaurant_id)
    if restaurant is not None:
        restaurant.is_verified = True

    application.status = VendorApplicationStatus.APPROVED.value
    application.review_note = note
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(UTC)
    await db.flush()

    log.info(
        "vendor_application_approved",
        application_no=application.application_no,
        admin_id=str(admin.id),
    )
    await _notify(
        application.owner_email,
        email_service.application_approved(application.business_name, application.owner_email),
    )
    return application


async def reject(
    db: AsyncSession, application_id, admin: User, note: str | None
) -> VendorApplication:
    """Reject: the restaurant stays unverified and invisible; the reason is emailed."""
    application = await _get_pending(db, application_id)

    application.status = VendorApplicationStatus.REJECTED.value
    application.review_note = note
    application.reviewed_by = admin.id
    application.reviewed_at = datetime.now(UTC)
    await db.flush()

    log.info(
        "vendor_application_rejected",
        application_no=application.application_no,
        admin_id=str(admin.id),
    )
    await _notify(
        application.owner_email,
        email_service.application_rejected(application.business_name, note),
    )
    return application


def to_detail(application: VendorApplication) -> VendorApplicationDetail:
    return VendorApplicationDetail(
        id=str(application.id),
        application_no=application.application_no,
        status=str(application.status),
        user_id=str(application.user_id),
        restaurant_id=str(application.restaurant_id),
        business_name=application.business_name,
        business_type=application.business_type,
        business_category=application.business_category,
        branch_count=application.branch_count,
        cuisine_types=list(application.cuisine_types or []),
        address_line=application.address_line,
        area=application.area,
        latitude=application.latitude,
        longitude=application.longitude,
        owner_full_name=application.owner_full_name,
        owner_email=application.owner_email,
        owner_phone=application.owner_phone,
        national_id=application.national_id,
        documents=dict(application.documents or {}),
        payout=dict(application.payout or {}),
        review_note=application.review_note,
        reviewed_by=str(application.reviewed_by) if application.reviewed_by else None,
        reviewed_at=application.reviewed_at,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )
