"""Notification campaigns, the in-app inbox, and device registration.

**Sending a campaign** is two steps, in this order:

1. Fan out into `user_notifications` — one INSERT … SELECT over every active
   account in the audience. This is the record, and what the apps read.
2. Push to the active devices of those accounts, if push is configured. Best
   effort: a failed push never unsends the inbox rows.

"Send now" runs both inside the admin's request. A scheduled campaign is
picked up by the worker's once-a-minute sweep (`send_due_notifications`),
which uses FOR UPDATE SKIP LOCKED so two workers never send the same one.

The audience never includes administrators; ALL means customers, vendors and
riders.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import UserRole
from app.models.notification import NotificationCampaign, UserNotification
from app.models.user import User, UserDevice
from app.schemas.notifications import DeviceOut, InboxItem, NotificationCampaignOut
from app.schemas.requests import DeviceRegisterRequest, NotificationCampaignRequest
from app.services import push_service

log = structlog.get_logger()

MAX_SCHEDULE_AHEAD = timedelta(days=90)
_AUDIENCE_ROLES = {
    "CUSTOMER": [UserRole.CUSTOMER.value],
    "VENDOR": [UserRole.VENDOR.value],
    "RIDER": [UserRole.RIDER.value],
    "ALL": [UserRole.CUSTOMER.value, UserRole.VENDOR.value, UserRole.RIDER.value],
}


def to_out(c: NotificationCampaign) -> NotificationCampaignOut:
    return NotificationCampaignOut(
        id=str(c.id),
        title=c.title,
        message=c.message,
        type=c.type,
        audience=c.audience,
        status=c.status,
        scheduled_for=c.scheduled_for,
        sent_at=c.sent_at,
        recipient_count=c.recipient_count,
        push_sent_count=c.push_sent_count,
        push_enabled=push_service.enabled(),
        failure_reason=c.failure_reason,
        created_by=str(c.created_by) if c.created_by else None,
        created_at=c.created_at,
    )


async def dispatch(db: AsyncSession, campaign: NotificationCampaign) -> NotificationCampaign:
    """Fan out and push. The caller commits."""
    roles = _AUDIENCE_ROLES[campaign.audience]
    audience = select(
        User.id,
        literal(campaign.id),
        literal(campaign.title),
        literal(campaign.message),
        literal(campaign.type),
    ).where(User.role.in_(roles), User.is_active.is_(True))
    # A data-modifying CTE: the INSERT's RETURNING is counted in the same
    # statement. rowcount is not reliable for INSERT … SELECT under psycopg's
    # async driver.
    fanout = (
        insert(UserNotification)
        .from_select(["user_id", "campaign_id", "title", "message", "type"], audience)
        .returning(UserNotification.id)
        .cte("fanout")
    )
    try:
        # A savepoint, so a failed fan-out can still be recorded as FAILED
        # instead of poisoning the whole transaction.
        async with db.begin_nested():
            inserted = await db.scalar(select(func.count()).select_from(fanout))
    except Exception as exc:
        campaign.status = "FAILED"
        campaign.failure_reason = f"Could not write the inbox rows: {exc}"[:500]
        log.error("notification_fanout_failed", campaign_id=str(campaign.id), error=str(exc))
        return campaign

    campaign.recipient_count = int(inserted or 0)
    tokens = list(
        (
            await db.scalars(
                select(UserDevice.fcm_token)
                .join(User, User.id == UserDevice.user_id)
                .where(
                    UserDevice.is_active.is_(True),
                    User.role.in_(roles),
                    User.is_active.is_(True),
                )
            )
        ).all()
    )
    pushed = await push_service.send(
        db,
        tokens,
        campaign.title,
        campaign.message,
        {"campaign_id": str(campaign.id), "type": campaign.type},
    )
    campaign.push_sent_count = pushed.sent
    campaign.status = "SENT"
    campaign.sent_at = datetime.now(UTC)
    log.info(
        "notification_sent",
        campaign_id=str(campaign.id),
        recipients=campaign.recipient_count,
        pushed=pushed.sent,
    )
    return campaign


async def create(
    db: AsyncSession, admin: User, body: NotificationCampaignRequest
) -> NotificationCampaignOut:
    now = datetime.now(UTC)
    when = body.scheduled_for
    if when is not None:
        if when.tzinfo is None:
            raise ValidationError("scheduled_for needs a timezone, e.g. 2026-09-30T18:00:00+06:00")
        if when <= now:
            raise ValidationError("scheduled_for must be in the future; omit it to send now")
        if when - now > MAX_SCHEDULE_AHEAD:
            raise ValidationError("A notification can be scheduled up to 90 days ahead")

    campaign = NotificationCampaign(
        title=body.title.strip(),
        message=body.message.strip(),
        type=body.type,
        audience=body.audience,
        scheduled_for=when or now,
        created_by=admin.id,
    )
    db.add(campaign)
    await db.flush()
    if when is None:
        await dispatch(db, campaign)
        await db.flush()
    await db.refresh(campaign)
    return to_out(campaign)


async def cancel(db: AsyncSession, campaign_id: uuid.UUID) -> NotificationCampaignOut:
    campaign = await db.get(NotificationCampaign, campaign_id, with_for_update=True)
    if campaign is None:
        raise NotFoundError("Notification not found")
    if campaign.status != "SCHEDULED":
        raise ValidationError(
            f"Only a scheduled notification can be cancelled; this one is {campaign.status.lower()}"
        )
    campaign.status = "CANCELLED"
    await db.flush()
    return to_out(campaign)


async def list_campaigns(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    audience: str | None = None,
) -> tuple[list[NotificationCampaignOut], int]:
    """Newest first (by when it goes out)."""
    conditions: list[ColumnElement[bool]] = []
    if status:
        conditions.append(NotificationCampaign.status == status.strip().upper())
    if audience:
        conditions.append(NotificationCampaign.audience == audience.strip().upper())
    total = await db.scalar(
        select(func.count()).select_from(NotificationCampaign).where(*conditions)
    )
    rows = await db.scalars(
        select(NotificationCampaign)
        .where(*conditions)
        .order_by(NotificationCampaign.scheduled_for.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_out(c) for c in rows.all()], int(total or 0)


async def send_due(db: AsyncSession) -> int:
    """The worker sweep: every SCHEDULED campaign whose time has come."""
    due = list(
        (
            await db.scalars(
                select(NotificationCampaign)
                .where(
                    NotificationCampaign.status == "SCHEDULED",
                    NotificationCampaign.scheduled_for <= datetime.now(UTC),
                )
                .order_by(NotificationCampaign.scheduled_for)
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        ).all()
    )
    for campaign in due:
        await dispatch(db, campaign)
    await db.flush()
    return len(due)


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


async def inbox(
    db: AsyncSession, user: User, limit: int, offset: int
) -> tuple[list[InboxItem], int, int]:
    """(page, total, unread)."""
    mine = UserNotification.user_id == user.id
    total = await db.scalar(select(func.count()).select_from(UserNotification).where(mine))
    unread = await db.scalar(
        select(func.count())
        .select_from(UserNotification)
        .where(mine, UserNotification.read_at.is_(None))
    )
    rows = await db.scalars(
        select(UserNotification)
        .where(mine)
        .order_by(UserNotification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return (
        [
            InboxItem(
                id=str(n.id),
                title=n.title,
                message=n.message,
                type=n.type,
                is_read=n.read_at is not None,
                created_at=n.created_at,
            )
            for n in rows.all()
        ],
        int(total or 0),
        int(unread or 0),
    )


async def mark_read(db: AsyncSession, user: User, notification_id: uuid.UUID | None) -> int:
    """One notification, or all of them when the id is None."""
    conditions = [UserNotification.user_id == user.id, UserNotification.read_at.is_(None)]
    if notification_id is not None:
        conditions.append(UserNotification.id == notification_id)
    result = await db.execute(
        update(UserNotification).where(*conditions).values(read_at=datetime.now(UTC))
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


async def register_device(db: AsyncSession, user: User, body: DeviceRegisterRequest) -> DeviceOut:
    """Idempotent. A token already registered to someone else moves to this
    user: the phone changed hands (or accounts), and the newest sign-in owns it."""
    device = await db.scalar(select(UserDevice).where(UserDevice.fcm_token == body.fcm_token))
    now = datetime.now(UTC)
    if device is None:
        device = UserDevice(user_id=user.id, fcm_token=body.fcm_token, platform=body.platform)
        db.add(device)
    device.user_id = user.id
    device.platform = body.platform
    device.is_active = True
    device.last_seen_at = now
    await db.flush()
    return DeviceOut(
        fcm_token=device.fcm_token,
        platform=str(device.platform),
        is_active=device.is_active,
        last_seen_at=device.last_seen_at,
    )


async def unregister_device(db: AsyncSession, user: User, fcm_token: str) -> bool:
    """Call on sign-out, so the next person on this phone does not get your pushes."""
    result = await db.execute(
        update(UserDevice)
        .where(UserDevice.fcm_token == fcm_token, UserDevice.user_id == user.id)
        .values(is_active=False)
    )
    return bool(getattr(result, "rowcount", 0))
