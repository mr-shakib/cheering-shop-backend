"""Read-only numbers: analytics, dashboard, performance, reviews."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Analytics (spec #43)
# ---------------------------------------------------------------------------


class AnalyticsTotals(BaseModel):
    orders: int
    gross_sales: Decimal = Field(description="Sum of item_total across delivered orders")
    commission: Decimal
    net_payout: Decimal = Field(description="gross_sales - commission")
    avg_order_value: Decimal


class AnalyticsDay(BaseModel):
    date: date
    orders: int
    gross_sales: Decimal
    net_payout: Decimal


class AnalyticsItem(BaseModel):
    menu_item_id: str | None = None
    name: str
    quantity: int
    gross_sales: Decimal


class VendorAnalytics(BaseModel):
    """GET /vendor/analytics

    Counts only DELIVERED orders. A cancelled or in-flight order is not
    earnings, and showing it as such would make the dashboard disagree with
    every payout the vendor ever receives.
    """

    restaurant_id: str
    date_from: date
    date_to: date
    totals: AnalyticsTotals
    daily: list[AnalyticsDay] = Field(default_factory=list)
    top_items: list[AnalyticsItem] = Field(default_factory=list)
    status_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Order counts by status in the window, including cancelled",
    )


# ---------------------------------------------------------------------------
# Dashboard & performance
# ---------------------------------------------------------------------------


class QueueCounts(BaseModel):
    """The Order tab's chips: New(5) · Preparing(2) · Complete(21)."""

    new: int = Field(description="PENDING orders awaiting accept/reject")
    preparing: int
    ready: int
    completed_today: int = Field(description="DELIVERED since local midnight (UTC)")


class DashboardDay(BaseModel):
    date: date
    orders: int
    earnings: Decimal


class RecentOrderRow(BaseModel):
    id: str
    order_number: int
    status: str
    customer_name: str | None = None
    grand_total: Decimal
    placed_at: datetime


class VendorDashboard(BaseModel):
    """GET /vendor/dashboard — one call renders the Order tab header and the
    whole Overview tab. Money in whole taka, like everything else."""

    restaurant_id: str
    store_status: str
    is_accepting_orders: bool
    queue: QueueCounts
    today_orders: int = Field(description="DELIVERED today")
    today_earnings: Decimal
    rating_avg: float
    rating_count: int
    acceptance_rate: float | None = Field(
        description="Accepted / decided over the last 30 days; null before any order"
    )
    last_7_days: list[DashboardDay] = Field(default_factory=list)
    recent_orders: list[RecentOrderRow] = Field(default_factory=list)


class VendorPerformance(BaseModel):
    """GET /vendor/performance — the Performance & ratings screen.

    `on_time_rate` counts an order on time when it was marked READY within the
    restaurant's own `avg_prep_time_mins` of acceptance — the only promise the
    schema records. Rates are fractions (0.82), null until there is data.
    """

    restaurant_id: str
    window_days: int
    acceptance_rate: float | None = None
    on_time_rate: float | None = None
    rating_avg: float
    rating_count: int
    rejections_this_week: int


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class VendorReviewOut(BaseModel):
    id: str
    order_id: str
    order_number: int | None = None
    restaurant_rating: int
    comment: str | None = None
    customer_name: str | None = None
    created_at: datetime


class ReviewsSummary(BaseModel):
    """GET /vendor/reviews/summary — the Feedback header: 4.3, 27 ratings, bars."""

    restaurant_id: str
    rating_avg: float
    rating_count: int
    histogram: dict[int, int] = Field(
        description="Star (1–5) -> count. Every key present, zeroes included."
    )
