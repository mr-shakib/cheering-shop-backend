"""Everything the vendor app runs on, one module per screen domain.

* ``storefront``   — registration fast path, approval, profile, hours, OPEN/CLOSED
* ``applications`` — the partner application form and the admin decision
* ``orders``       — the order state machine: queue, accept/reject, handoff
* ``insights``     — read-only numbers: analytics, dashboard, reviews, CSV
* ``finance``      — earnings, the derived balance, payouts
* ``promotions``   — offers on top of promo_codes

``app.services`` re-exports these under their historical ``vendor_*_service``
names, which remains the way endpoints import them.
"""
