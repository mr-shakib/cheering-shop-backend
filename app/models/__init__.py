"""Model registry.

Every model must be imported here. Alembic's autogenerate walks `Base.metadata`,
and a model that is never imported is invisible to it — the classic cause of a
table silently vanishing from a migration.
"""

from app.models.address import Address
from app.models.base import Base
from app.models.cart import Cart, CartItem, CartItemAddOn
from app.models.chat import OrderMessage
from app.models.menu import ItemAddOn, ItemVariant, MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderItemAddOn, OrderStatusHistory
from app.models.payout import VendorPayout
from app.models.promo import PromoCode, PromoRedemption
from app.models.restaurant import Favorite, Restaurant
from app.models.review import Review
from app.models.rider import RiderLocationPing, RiderProfile
from app.models.user import (
    AuthIdentity,
    BiometricCredential,
    IdempotencyKey,
    OtpCode,
    RefreshToken,
    User,
    UserDevice,
)
from app.models.vendor_application import VendorApplication

__all__ = [
    "Base",
    # Identity & security
    "User",
    "AuthIdentity",
    "BiometricCredential",
    "UserDevice",
    "RefreshToken",
    "OtpCode",
    "IdempotencyKey",
    # Addresses
    "Address",
    # Restaurants & catalog
    "Restaurant",
    "Favorite",
    "VendorApplication",
    "OrderMessage",
    "VendorPayout",
    "MenuCategory",
    "MenuItem",
    "ItemVariant",
    "ItemAddOn",
    # Cart
    "Cart",
    "CartItem",
    "CartItemAddOn",
    # Promotions
    "PromoCode",
    "PromoRedemption",
    # Riders
    "RiderProfile",
    "RiderLocationPing",
    # Orders
    "Order",
    "OrderItem",
    "OrderItemAddOn",
    "OrderStatusHistory",
    # Reviews
    "Review",
]
