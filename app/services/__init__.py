"""Business logic layer.

Endpoints stay thin: validate, delegate here, shape the response. Anything that
touches more than one table, or that has a rule worth testing on its own, lives
in a service rather than in a route handler.

The vendor and customer domains live in the ``app.services.vendor`` and
``app.services.customer`` packages; the aliases below keep their modules
importable under the flat ``*_service`` names every endpoint uses — the package
layout is an authoring convenience, not an import-path migration.
"""

from app.services import (
    auth_service,
    idempotency,
    menu_service,
    otp_service,
    realtime,
    storage_service,
    token_service,
)
from app.services.customer import account as account_service
from app.services.customer import cart as cart_service
from app.services.customer import chat as chat_service
from app.services.customer import discovery as discovery_service
from app.services.customer import orders as order_service
from app.services.customer import promos as promo_service
from app.services.customer import reviews as review_service
from app.services.vendor import applications as vendor_application_service
from app.services.vendor import finance as vendor_finance_service
from app.services.vendor import insights as vendor_insights_service
from app.services.vendor import orders as vendor_order_service
from app.services.vendor import promotions as vendor_promotion_service
from app.services.vendor import storefront as vendor_service

__all__ = [
    "account_service",
    "auth_service",
    "cart_service",
    "chat_service",
    "discovery_service",
    "idempotency",
    "menu_service",
    "order_service",
    "otp_service",
    "promo_service",
    "realtime",
    "review_service",
    "storage_service",
    "token_service",
    "vendor_application_service",
    "vendor_finance_service",
    "vendor_insights_service",
    "vendor_order_service",
    "vendor_promotion_service",
    "vendor_service",
]
