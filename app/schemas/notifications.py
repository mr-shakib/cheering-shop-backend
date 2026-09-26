"""Notification campaigns (admin) and each user's inbox and devices."""

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationCampaignOut(BaseModel):
    id: str
    title: str
    message: str
    type: str = Field(description="PROMOTION, ALERT or UPDATE")
    audience: str = Field(description="CUSTOMER, VENDOR, RIDER or ALL")
    status: str = Field(description="SCHEDULED, SENT, FAILED or CANCELLED")
    scheduled_for: datetime
    sent_at: datetime | None = None
    recipient_count: int = Field(description="Inboxes it landed in")
    push_sent_count: int = Field(description="Devices a push reached")
    push_enabled: bool = Field(description="False when push is not configured on the server")
    failure_reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class InboxItem(BaseModel):
    id: str
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime


class DeviceOut(BaseModel):
    fcm_token: str
    platform: str
    is_active: bool
    last_seen_at: datetime
