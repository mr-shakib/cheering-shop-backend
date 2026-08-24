"""Customer-facing services.

One module per domain, the same convention as `services.vendor`. Endpoints
import these through the aliases in `app.services` — never by direct module
path — so the split stays an authoring detail rather than an import contract.
"""

from app.services.customer import (
    account,
    cart,
    chat,
    discovery,
    orders,
    promos,
    reviews,
)

__all__ = ["account", "cart", "chat", "discovery", "orders", "promos", "reviews"]
