"""Admin console response models, one module per screen domain.

Money is whole taka (already through ``to_major``) and ids are strings, as in
every other response package. Everything is re-exported here, so
``from app.schemas.admin import X`` works regardless of which module holds X.
"""

from app.schemas.admin.accounts import (
    AccountStatus,
    AdminCustomerDetail,
    AdminCustomerRow,
    AdminCustomerStats,
)
from app.schemas.admin.ads import AdCampaignOut
from app.schemas.admin.insights import (
    AdminDashboard,
    AdminSearchResults,
    FinanceSummary,
    FinanceTransaction,
    Kpi,
    LiveOrderCounts,
    PendingApprovals,
    RevenuePoint,
    RevenueSeries,
    SearchHit,
    ServiceShare,
    SupportTicketCard,
)
from app.schemas.admin.invitations import AdminInvitationOut, InvitationPreview
from app.schemas.admin.orders import (
    AdminOrderActions,
    AdminOrderCustomer,
    AdminOrderDetail,
    AdminOrderEvent,
    AdminOrderMoney,
    AdminOrderPayment,
    AdminOrderRider,
    AdminOrderRow,
    AdminOrderVendor,
    AdminRiderLocation,
)
from app.schemas.admin.products import AdminProductDetail, AdminProductRow, ProductCommission
from app.schemas.admin.riders import (
    AdminRiderDetail,
    AdminRiderEarnings,
    AdminRiderPayoutRow,
    AdminRiderRow,
    LiveOrderBrief,
    LiveRider,
    RiderApplicationOut,
    RiderApplicationStatus,
    RiderApplicationSubmitted,
    RiderIncentiveOut,
)
from app.schemas.admin.settings import PlatformSettingsOut, SurchargeOut
from app.schemas.admin.vendors import (
    AdminPayoutRow,
    AdminVendorDetail,
    AdminVendorFinance,
    AdminVendorOwner,
    AdminVendorReviews,
    AdminVendorRow,
)

__all__ = [
    # ads
    "AdCampaignOut",
    # accounts
    "AccountStatus",
    "AdminCustomerDetail",
    "AdminCustomerRow",
    "AdminCustomerStats",
    # insights
    "AdminDashboard",
    "AdminSearchResults",
    "FinanceSummary",
    "FinanceTransaction",
    "Kpi",
    "LiveOrderCounts",
    "PendingApprovals",
    "RevenuePoint",
    "RevenueSeries",
    "SearchHit",
    "ServiceShare",
    "SupportTicketCard",
    # invitations
    "AdminInvitationOut",
    "InvitationPreview",
    # orders
    "AdminOrderActions",
    "AdminOrderCustomer",
    "AdminOrderDetail",
    "AdminOrderEvent",
    "AdminOrderMoney",
    "AdminOrderPayment",
    "AdminOrderRider",
    "AdminOrderRow",
    "AdminOrderVendor",
    "AdminRiderLocation",
    # products
    "AdminProductDetail",
    "AdminProductRow",
    "ProductCommission",
    # riders
    "AdminRiderDetail",
    "AdminRiderEarnings",
    "AdminRiderPayoutRow",
    "AdminRiderRow",
    "LiveOrderBrief",
    "LiveRider",
    "RiderApplicationOut",
    "RiderApplicationStatus",
    "RiderApplicationSubmitted",
    "RiderIncentiveOut",
    # settings
    "PlatformSettingsOut",
    "SurchargeOut",
    # vendors
    "AdminPayoutRow",
    "AdminVendorDetail",
    "AdminVendorFinance",
    "AdminVendorOwner",
    "AdminVendorReviews",
    "AdminVendorRow",
]
