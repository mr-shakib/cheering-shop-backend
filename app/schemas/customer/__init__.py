"""Customer-facing response schemas.

One module per domain, everything re-exported here — the same convention as
`schemas.requests` and `schemas.vendor`. Imports elsewhere say
`from app.schemas.customer import X`; the split is authoring convenience, not
an API surface. When adding a schema: put it in the right domain module AND
add it to `__all__` below.
"""

from app.schemas.customer.account import (
    AddressOut,
    DeliverySlot,
    FavoriteToggled,
    MinimumOrder,
    ScheduleDay,
    ScheduleOptions,
)
from app.schemas.customer.cart import (
    CartAddOnOut,
    CartLineOut,
    CartOut,
    CheckoutSummary,
    DeliveryOption,
)
from app.schemas.customer.chat import ChatMessageOut, ChatMessageSent, ChatThread
from app.schemas.customer.discovery import (
    AddOnOut,
    CategoryChip,
    CategoryDish,
    CuisineChip,
    HomeFeed,
    MenuCategoryOut,
    MenuItemOut,
    PromotionBanner,
    ReelDish,
    ReelOut,
    RestaurantCard,
    RestaurantDetail,
    SearchItemHit,
    SearchResults,
    VariantOut,
)
from app.schemas.customer.orders import (
    OrderDetail,
    OrderItemAddOnOut,
    OrderItemOut,
    OrderStatusEvent,
    OrderSummary,
    OrderTracking,
    PlacedOrder,
    ReviewOut,
    RiderBrief,
)

__all__ = [
    "AddOnOut",
    "AddressOut",
    "CartAddOnOut",
    "CartLineOut",
    "CartOut",
    "CategoryChip",
    "CategoryDish",
    "ChatMessageOut",
    "ChatMessageSent",
    "ChatThread",
    "CheckoutSummary",
    "DeliveryOption",
    "CuisineChip",
    "DeliverySlot",
    "FavoriteToggled",
    "HomeFeed",
    "MenuCategoryOut",
    "MenuItemOut",
    "MinimumOrder",
    "OrderDetail",
    "OrderItemAddOnOut",
    "OrderItemOut",
    "OrderStatusEvent",
    "OrderSummary",
    "OrderTracking",
    "PlacedOrder",
    "PromotionBanner",
    "ReelDish",
    "ReelOut",
    "RestaurantCard",
    "RestaurantDetail",
    "ReviewOut",
    "RiderBrief",
    "ScheduleDay",
    "ScheduleOptions",
    "SearchItemHit",
    "SearchResults",
    "VariantOut",
]
