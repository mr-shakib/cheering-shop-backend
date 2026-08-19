"""Business logic layer.

Endpoints stay thin: validate, delegate here, shape the response. Anything that
touches more than one table, or that has a rule worth testing on its own, lives
in a service rather than in a route handler.

The vendor domain lives in the ``app.services.vendor`` package; the aliases
below keep its modules importable under the flat ``vendor_*_service`` names
every endpoint uses — the package layout is an authoring convenience, not an
import-path migration.
"""

from app.services import (
    auth_service,
    menu_service,
    otp_service,
    storage_service,
    token_service,
)
from app.services.vendor import applications as vendor_application_service
from app.services.vendor import finance as vendor_finance_service
from app.services.vendor import insights as vendor_insights_service
from app.services.vendor import orders as vendor_order_service
from app.services.vendor import promotions as vendor_promotion_service
from app.services.vendor import storefront as vendor_service

__all__ = [
    "auth_service",
    "menu_service",
    "otp_service",
    "storage_service",
    "token_service",
    "vendor_application_service",
    "vendor_finance_service",
    "vendor_insights_service",
    "vendor_order_service",
    "vendor_promotion_service",
    "vendor_service",
]
