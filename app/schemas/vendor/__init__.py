"""Vendor response models, one module per screen domain.

**Money crosses this boundary in whole taka.** The database stores BIGINT paisa
(``app/core/money.py``); every field typed ``Decimal`` here has already been
through ``to_major``. Nothing downstream should divide by 100 again.

Ids are serialised as strings rather than ``uuid.UUID`` to match the rest of the
API — a client that round-trips an id through JSON gets back exactly what it
sent, with no dependence on how a given JSON library renders a UUID.

Everything is re-exported here, so ``from app.schemas.vendor import X`` works
regardless of which module holds X — the split is an authoring convenience,
not an API surface.
"""

from app.schemas.vendor.applications import (
    VendorApplicationDetail,
    VendorApplicationStatus,
    VendorApplicationSubmitted,
)
from app.schemas.vendor.finance import (
    EarningsTransaction,
    PayoutOut,
    VendorEarnings,
)
from app.schemas.vendor.insights import (
    AnalyticsDay,
    AnalyticsItem,
    AnalyticsTotals,
    DashboardDay,
    QueueCounts,
    RecentOrderRow,
    ReviewsSummary,
    VendorAnalytics,
    VendorDashboard,
    VendorPerformance,
    VendorReviewOut,
)
from app.schemas.vendor.menu import (
    AddOnOut,
    MenuCategoryOut,
    MenuCategoryWithItems,
    MenuItemOut,
    VariantOut,
    VendorMenu,
)
from app.schemas.vendor.orders import (
    HandoffResult,
    VendorOrderDetail,
    VendorOrderItemAddOnOut,
    VendorOrderItemOut,
    VendorOrderSummary,
)
from app.schemas.vendor.promotions import (
    PromotionDay,
    PromotionDetail,
    PromotionOut,
)
from app.schemas.vendor.storefront import (
    BusinessHoursOut,
    DayHoursOut,
    RestaurantProfile,
    StoreStatusResult,
)
from app.schemas.vendor.uploads import PresignedUpload

__all__ = [
    # menu
    "VariantOut",
    "AddOnOut",
    "MenuItemOut",
    "MenuCategoryOut",
    "MenuCategoryWithItems",
    "VendorMenu",
    # storefront
    "RestaurantProfile",
    "StoreStatusResult",
    "DayHoursOut",
    "BusinessHoursOut",
    # orders
    "VendorOrderItemAddOnOut",
    "VendorOrderItemOut",
    "VendorOrderSummary",
    "VendorOrderDetail",
    "HandoffResult",
    # insights
    "AnalyticsTotals",
    "AnalyticsDay",
    "AnalyticsItem",
    "VendorAnalytics",
    "QueueCounts",
    "DashboardDay",
    "RecentOrderRow",
    "VendorDashboard",
    "VendorPerformance",
    "VendorReviewOut",
    "ReviewsSummary",
    # finance
    "EarningsTransaction",
    "VendorEarnings",
    "PayoutOut",
    # promotions
    "PromotionDay",
    "PromotionOut",
    "PromotionDetail",
    # applications
    "VendorApplicationSubmitted",
    "VendorApplicationStatus",
    "VendorApplicationDetail",
    # uploads
    "PresignedUpload",
]
