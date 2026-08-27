"""Request bodies, one module per domain.

Only bodies an implemented endpoint accepts are modelled here — inventing
contracts ahead of their modules would be guessing.

Everything is re-exported at the package level, so
``from app.schemas.requests import X`` works regardless of which module holds
X — the split is an authoring convenience, not an API surface.
"""

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
from app.schemas.requests.commerce import (
    CartItemRequest,
    ChatMessageRequest,
    OrderCancelRequest,
    OrderCreateRequest,
    ReviewCreateRequest,
)
from app.schemas.requests.finance import PayoutCreateRequest, PayoutFailRequest
from app.schemas.requests.promotions import (
    PromotionCreateRequest,
    PromotionUpdateRequest,
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
    # promotions
    "PromotionCreateRequest",
    "PromotionUpdateRequest",
]
