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
    auth,
    cart,
    comms,
    discovery,
    favorites,
    orders,
    rider,
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

# Users, addresses, favorites — /users/me/* literals before any {id} routes
api_router.include_router(users.router)
api_router.include_router(addresses.router)
api_router.include_router(favorites.router)

# Public discovery
api_router.include_router(discovery.router)

# Customer commerce
api_router.include_router(cart.router)
api_router.include_router(orders.router)
api_router.include_router(tracking.router)
api_router.include_router(comms.router)

# Vendor onboarding (public) before vendor operations — /vendor/applications/*
# literals must register ahead of anything else under /vendor
api_router.include_router(vendor_applications.router)
api_router.include_router(vendor.router)

# Rider app
api_router.include_router(rider.router)

# Administration
api_router.include_router(admin.router)

# System
api_router.include_router(uploads.router)

# Real-time channels
api_router.include_router(ws.router)
