"""Read-only admin numbers: the Overview dashboard, Finance, and global search."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.admin.orders import AdminOrderRow


class Kpi(BaseModel):
    """A stat card: the value and how it moved against the previous period."""

    value: Decimal
    previous: Decimal
    change_pct: float | None = Field(
        description="Percent change vs the previous period; null when that was zero"
    )


class PendingApprovals(BaseModel):
    total: int
    vendors: int = Field(description="Restaurants not yet verified")
    riders: int = Field(description="Rider applications awaiting review")


class LiveOrderCounts(BaseModel):
    """The Live order card."""

    new: int = Field(description="PENDING")
    preparing: int = Field(description="PREPARING and READY")
    on_delivery: int = Field(description="PICKED_UP")
    cancelled_today: int
    avg_delivery_minutes: int | None = Field(
        description="Placed → delivered, over orders delivered today; null if none"
    )


class SupportTicketCard(BaseModel):
    """The Support tickets card: open plus pending, and how many are urgent."""

    open: int
    urgent: int


class AdminDashboard(BaseModel):
    """GET /admin/dashboard — the Overview screen in one call.

    `revenue_today` and `orders_today` compare today with yesterday, both as
    UTC days. The revenue chart is `GET /admin/analytics/revenue`.
    """

    revenue_today: Kpi = Field(description="GMV of orders delivered today")
    orders_today: Kpi = Field(description="Orders placed today, any status")
    active_riders: int = Field(description="Riders on shift now")
    online_vendors: int = Field(description="Verified, active restaurants that are OPEN")
    pending_approvals: PendingApprovals
    live_orders: LiveOrderCounts
    support_tickets: SupportTicketCard
    recent_orders: list[AdminOrderRow]
    generated_at: datetime


class RevenuePoint(BaseModel):
    period_start: date = Field(description="The day, or the first of the month for 12m")
    label: str = Field(description='"Sat", "14 Aug" or "Aug 2026" — ready for the x-axis')
    gmv: Decimal
    orders: int


class RevenueSeries(BaseModel):
    """GET /admin/analytics/revenue — the Revenue overview chart."""

    range: str = Field(description="7d, 30d or 12m")
    granularity: str = Field(description="day or month")
    total_gmv: Decimal
    points: list[RevenuePoint]


class ServiceShare(BaseModel):
    business_type: str = Field(description="RESTAURANT, GROCERY, PHARMACY or UNKNOWN")
    gmv: Decimal
    share_pct: float


class FinanceSummary(BaseModel):
    """GET /admin/finance/summary — the four Finance cards and the donut.

    Every figure counts DELIVERED orders only, in the window ending now,
    compared with the window of the same length before it.
    """

    days: int
    gmv: Kpi = Field(description="Sum of grand_total")
    net_revenue: Kpi = Field(
        description="commission + platform fees — what the platform keeps. Delivery "
        "fees and tips are paid to riders, so they are not in it."
    )
    commission_revenue: Kpi
    delivery_revenue: Kpi = Field(
        description="Delivery fees collected — passed on to the riders who delivered"
    )
    revenue_by_service: list[ServiceShare]


class FinanceTransaction(BaseModel):
    """One row of Transaction details: a delivered order and its payment."""

    order_id: str
    order_number: int
    payment_reference: str | None = Field(
        default=None, description="The gateway's reference; null for COD"
    )
    payment_method: str
    payment_status: str
    restaurant_id: str
    restaurant_name: str
    customer_id: str
    customer_name: str | None = None
    amount: Decimal = Field(description="grand_total")
    commission_amount: Decimal
    delivered_at: datetime


class SearchHit(BaseModel):
    id: str
    title: str
    subtitle: str | None = None


class AdminSearchResults(BaseModel):
    """GET /admin/search — the top bar. At most five hits per group."""

    query: str
    orders: list[SearchHit]
    customers: list[SearchHit]
    vendors: list[SearchHit]
    riders: list[SearchHit]
