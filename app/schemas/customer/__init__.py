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
from app.schemas.customer.cart import CartLineOut, CartOut, CheckoutSummary
from app.schemas.customer.chat import ChatMessageOut, ChatMessageSent, ChatThread
from app.schemas.customer.discovery import (
    AddOnOut,
    CuisineChip,
    HomeFeed,
    MenuCategoryOut,
    MenuItemOut,
    PromotionBanner,
    RestaurantCard,
    RestaurantDetail,
    SearchItemHit,
    SearchResults,
    VariantOut,
)
from app.schemas.customer.orders import (
    OrderDetail,
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
    "CartLineOut",
    "CartOut",
    "ChatMessageOut",
    "ChatMessageSent",
    "ChatThread",
    "CheckoutSummary",
    "CuisineChip",
    "DeliverySlot",
    "FavoriteToggled",
    "HomeFeed",
    "MenuCategoryOut",
    "MenuItemOut",
    "MinimumOrder",
    "OrderDetail",
    "OrderItemOut",
    "OrderStatusEvent",
    "OrderSummary",
    "OrderTracking",
    "PlacedOrder",
    "PromotionBanner",
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
