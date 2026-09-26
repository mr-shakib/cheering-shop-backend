"""Request bodies, one module per domain.

Only bodies an implemented endpoint accepts are modelled here — inventing
contracts ahead of their modules would be guessing.

Everything is re-exported at the package level, so
``from app.schemas.requests import X`` works regardless of which module holds
X — the split is an authoring convenience, not an API surface.
"""

from app.schemas.requests.admin import (
    AdCampaignUpdateRequest,
    AdminInvitationAcceptRequest,
    AdminInvitationRequest,
    AdminOrderCancelRequest,
    AdminOrderRefundRequest,
    AdminProductCreateRequest,
    AdminProductUpdateRequest,
    AttachmentIn,
    CommunityPostRequest,
    CommunityRemoveRequest,
    CommunityReportRequest,
    DeviceRegisterRequest,
    NotificationCampaignRequest,
    PlatformSettingsUpdateRequest,
    PromotionEventsRequest,
    SupportMessageRequest,
    SupportTicketCreateRequest,
    SupportTicketUpdateRequest,
    SurchargeUpdate,
    UserStatusRequest,
)
from app.schemas.requests.applications import (
    ApplicationBusinessInfo,
    ApplicationDecisionRequest,
    ApplicationDocuments,
    ApplicationLocation,
    ApplicationOwnerInfo,
    ApplicationPayout,
    ApplicationUploadRequest,
    VendorApplicationRequest,
)
from app.schemas.requests.auth import (
    BiometricChallengeRequest,
    BiometricLoginRequest,
    BiometricsEnableRequest,
    Login2FARequest,
    LoginRequest,
    LogoutRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RefreshRequest,
    TotpEnableRequest,
)
from app.schemas.requests.base import Money
from app.schemas.requests.categories import (
    CategoryCreateRequest,
    CategoryMergeRequest,
    CategoryUpdateRequest,
)
from app.schemas.requests.commerce import (
    CartAddOnChoice,
    CartItemRequest,
    CartLineUpdateRequest,
    ChatMessageRequest,
    OrderCancelRequest,
    OrderCreateRequest,
    ReviewCreateRequest,
)
from app.schemas.requests.finance import (
    PayoutCreateRequest,
    PayoutFailRequest,
    PayoutReopenRequest,
)
from app.schemas.requests.promotions import (
    PromotionCreateRequest,
    PromotionUpdateRequest,
)
from app.schemas.requests.riders import (
    AssignRiderRequest,
    RiderApplicationApproveRequest,
    RiderApplicationDocuments,
    RiderApplicationPayout,
    RiderApplicationRejectRequest,
    RiderApplicationRequest,
    RiderCreateRequest,
    RiderIncentiveRequest,
    RiderLocationRequest,
    RiderShiftRequest,
    RiderUpdateRequest,
)
from app.schemas.requests.users import (
    AddressCreateRequest,
    ChangePasswordRequest,
    PresignedUrlRequest,
    ProfileUpdateRequest,
)
from app.schemas.requests.vendor import (
    BusinessHoursRequest,
    DayHours,
    HandoffRequest,
    OrderRejectRequest,
    RestaurantDetails,
    RestaurantProfileUpdateRequest,
    SetCommissionRequest,
    StoreStatusRequest,
    VendorRegisterRequest,
    VerifyRestaurantRequest,
)
from app.schemas.requests.vendor_menu import (
    AddOnCreateRequest,
    AddOnRequest,
    AddOnUpdateRequest,
    MenuCategoryCreateRequest,
    MenuCategoryUpdateRequest,
    MenuItemCreateRequest,
    MenuItemStatusRequest,
    MenuItemUpdateRequest,
    MenuReorderRequest,
    ReorderEntry,
    VariantCreateRequest,
    VariantRequest,
    VariantUpdateRequest,
)

__all__ = [
    "Money",
    # auth
    "OtpSendRequest",
    "OtpVerifyRequest",
    "LoginRequest",
    "Login2FARequest",
    "PasswordForgotRequest",
    "PasswordResetRequest",
    "RefreshRequest",
    "LogoutRequest",
    "TotpEnableRequest",
    "BiometricsEnableRequest",
    "BiometricChallengeRequest",
    "BiometricLoginRequest",
    # users
    "ProfileUpdateRequest",
    "ChangePasswordRequest",
    "AddressCreateRequest",
    "PresignedUrlRequest",
    # commerce
    "CartItemRequest",
    "CartAddOnChoice",
    "CartLineUpdateRequest",
    "ChatMessageRequest",
    "OrderCreateRequest",
    "OrderCancelRequest",
    "ReviewCreateRequest",
    # vendor storefront & lifecycle
    "StoreStatusRequest",
    "HandoffRequest",
    "OrderRejectRequest",
    "RestaurantProfileUpdateRequest",
    "SetCommissionRequest",
    "RestaurantDetails",
    "VendorRegisterRequest",
    "VerifyRestaurantRequest",
    "DayHours",
    "BusinessHoursRequest",
    # vendor menu
    "VariantRequest",
    "VariantCreateRequest",
    "VariantUpdateRequest",
    "AddOnRequest",
    "AddOnCreateRequest",
    "AddOnUpdateRequest",
    "MenuItemCreateRequest",
    "MenuItemUpdateRequest",
    "MenuItemStatusRequest",
    "MenuCategoryCreateRequest",
    "MenuCategoryUpdateRequest",
    "ReorderEntry",
    "MenuReorderRequest",
    # applications
    "ApplicationBusinessInfo",
    "ApplicationLocation",
    "ApplicationOwnerInfo",
    "ApplicationDocuments",
    "ApplicationPayout",
    "VendorApplicationRequest",
    "ApplicationUploadRequest",
    "ApplicationDecisionRequest",
    # finance
    "PayoutCreateRequest",
    "PayoutFailRequest",
    "PayoutReopenRequest",
    # promotions
    "PromotionCreateRequest",
    "PromotionUpdateRequest",
    # platform categories (admin)
    "CategoryCreateRequest",
    "CategoryUpdateRequest",
    "CategoryMergeRequest",
    # riders & dispatch
    "RiderCreateRequest",
    "RiderUpdateRequest",
    "RiderShiftRequest",
    "RiderLocationRequest",
    "AssignRiderRequest",
    "RiderApplicationApproveRequest",
    "RiderApplicationDocuments",
    "RiderApplicationPayout",
    "RiderApplicationRejectRequest",
    "RiderApplicationRequest",
    "RiderIncentiveRequest",
    # admin console
    "AdminOrderCancelRequest",
    "AdminOrderRefundRequest",
    "AdminProductCreateRequest",
    "AdminProductUpdateRequest",
    "PlatformSettingsUpdateRequest",
    "SurchargeUpdate",
    "AttachmentIn",
    "CommunityPostRequest",
    "CommunityRemoveRequest",
    "CommunityReportRequest",
    "AdCampaignUpdateRequest",
    "PromotionEventsRequest",
    "AdminInvitationAcceptRequest",
    "AdminInvitationRequest",
    "DeviceRegisterRequest",
    "NotificationCampaignRequest",
    "SupportMessageRequest",
    "SupportTicketCreateRequest",
    "SupportTicketUpdateRequest",
    "UserStatusRequest",
]
