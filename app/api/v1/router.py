"""v1 router aggregation.

Include order matters. `discovery` declares `/restaurants/{restaurant_id}` and
`favorites` declares `/users/me/favorites/{restaurant_id}`; more specific
prefixes are registered before catch-all path parameters so a literal segment is
never swallowed by a `{param}` on an earlier route.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    addresses,
    admin,
    admin_accounts,
    admin_ads,
    admin_community,
    admin_content,
    admin_insights,
    admin_invitations,
    admin_invite_accept,
    admin_notifications,
    admin_orders,
    admin_products,
    admin_riders,
    admin_settings,
    admin_support,
    admin_vendors,
    auth,
    cart,
    comms,
    community,
    content,
    discovery,
    favorites,
    notifications,
    orders,
    promotion_events,
    rider,
    rider_applications,
    support,
    tracking,
    uploads,
    users,
    vendor,
    vendor_applications,
    ws,
)

api_router = APIRouter()

# Authentication & security
api_router.include_router(auth.router)
api_router.include_router(admin_invite_accept.router)

# Users, addresses, favorites — /users/me/* literals before any {id} routes
api_router.include_router(users.router)
api_router.include_router(addresses.router)
api_router.include_router(favorites.router)

# Public discovery
api_router.include_router(discovery.router)
api_router.include_router(content.router)
api_router.include_router(promotion_events.router)

# Customer commerce
api_router.include_router(cart.router)
api_router.include_router(orders.router)
api_router.include_router(tracking.router)
api_router.include_router(comms.router)

# Vendor onboarding (public) before vendor operations — /vendor/applications/*
# literals must register ahead of anything else under /vendor
api_router.include_router(vendor_applications.router)
api_router.include_router(vendor.router)

# Rider app, and its public application form
api_router.include_router(rider.router)
api_router.include_router(rider_applications.router)

# Administration — admin_riders before admin: /admin/riders/live is a literal
# that admin.py's PATCH /admin/riders/{rider_id} must never shadow.
api_router.include_router(admin_riders.router)
api_router.include_router(admin.router)
api_router.include_router(admin_orders.router)
api_router.include_router(admin_accounts.router)
api_router.include_router(admin_vendors.router)
api_router.include_router(admin_products.router)
api_router.include_router(admin_insights.router)
api_router.include_router(admin_settings.router)
api_router.include_router(admin_support.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(admin_invitations.router)
api_router.include_router(admin_ads.router)
api_router.include_router(admin_community.router)
api_router.include_router(admin_content.router)

# Help & support, inbox and devices — any signed-in role
api_router.include_router(support.router)
api_router.include_router(notifications.router)
api_router.include_router(community.router)

# System
api_router.include_router(uploads.router)

# Real-time channels
api_router.include_router(ws.router)
