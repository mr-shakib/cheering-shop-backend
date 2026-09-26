"""The admin Customers screens, and blocking an account."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AdminCustomerRow(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    order_count: int = Field(description="Every order placed, cancelled ones included")
    total_spent: Decimal = Field(description="Sum of grand_total over DELIVERED orders")
    is_active: bool = Field(description="false renders as Blocked")
    created_at: datetime


class AdminCustomerStats(BaseModel):
    total_orders: int
    delivered_orders: int
    cancelled_orders: int
    total_spent: Decimal
    average_order: Decimal = Field(description="total_spent / delivered_orders; 0 with none")


class AdminCustomerDetail(AdminCustomerRow):
    """Customer Details. Recent orders come from
    `GET /admin/orders?customer_id=`."""

    default_address: str | None = None
    last_login_at: datetime | None = None
    stats: AdminCustomerStats


class AccountStatus(BaseModel):
    """PATCH /admin/users/{id}/status"""

    id: str
    role: str
    is_active: bool
    sessions_revoked: int = Field(description="Refresh tokens revoked by this change")
    message: str
