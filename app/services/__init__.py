"""Business logic layer.

Endpoints stay thin: validate, delegate here, shape the response. Anything that
touches more than one table, or that has a rule worth testing on its own, lives
in a service rather than in a route handler.

The vendor, customer, rider and admin domains live in the
``app.services.vendor``, ``app.services.customer``, ``app.services.rider`` and
``app.services.admin`` packages; the aliases
below keep their modules importable under the flat ``*_service`` names every
endpoint uses — the package layout is an authoring convenience, not an
import-path migration.
"""

from app.services import (
    auth_service,
    category_service,
    community,
    idempotency,
    menu_service,
    notifications,
    oauth_service,
    otp_service,
    platform_settings,
    push_service,
    realtime,
    storage_service,
    support,
    token_service,
)
from app.services.admin import accounts as admin_account_service
from app.services.admin import ads as admin_ad_service
from app.services.admin import insights as admin_insights_service
from app.services.admin import invitations as admin_invitation_service
from app.services.admin import orders as admin_order_service
from app.services.admin import products as admin_product_service
from app.services.admin import riders as admin_rider_service
from app.services.admin import vendors as admin_vendor_service
from app.services.customer import account as account_service
from app.services.customer import cart as cart_service
from app.services.customer import chat as chat_service
from app.services.customer import discovery as discovery_service
from app.services.customer import orders as order_service
from app.services.customer import promos as promo_service
from app.services.customer import reviews as review_service
from app.services.rider import applications as rider_application_service
from app.services.rider import dispatch as dispatch_service
from app.services.rider import earnings as rider_earnings_service
from app.services.rider import jobs as rider_jobs_service
from app.services.rider import offers as rider_offer_service
from app.services.rider import roster as rider_roster_service
from app.services.rider import tracking as rider_tracking_service
from app.services.vendor import applications as vendor_application_service
from app.services.vendor import finance as vendor_finance_service
from app.services.vendor import insights as vendor_insights_service
from app.services.vendor import orders as vendor_order_service
from app.services.vendor import promotions as vendor_promotion_service
from app.services.vendor import storefront as vendor_service

__all__ = [
    "account_service",
    "admin_account_service",
    "admin_ad_service",
    "admin_insights_service",
    "admin_invitation_service",
    "admin_order_service",
    "admin_product_service",
    "admin_rider_service",
    "admin_vendor_service",
    "auth_service",
    "cart_service",
    "category_service",
    "community",
    "chat_service",
    "discovery_service",
    "dispatch_service",
    "idempotency",
    "menu_service",
    "notifications",
    "oauth_service",
    "order_service",
    "otp_service",
    "promo_service",
    "realtime",
    "review_service",
    "rider_application_service",
    "rider_earnings_service",
    "rider_offer_service",
    "rider_jobs_service",
    "rider_roster_service",
    "rider_tracking_service",
    "storage_service",
    "support",
    "platform_settings",
    "push_service",
    "token_service",
    "vendor_application_service",
    "vendor_finance_service",
    "vendor_insights_service",
    "vendor_order_service",
    "vendor_promotion_service",
    "vendor_service",
]
