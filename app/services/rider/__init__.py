"""The rider domain — assignment and the roster it draws from.

The specification defines a RIDER role, ``orders.rider_id``, live GPS and rider
earnings, but never a way for a rider to arrive on an order. Nothing in the
codebase wrote ``rider_id``, and that single gap made
``POST /vendor/orders/{id}/handoff`` unreachable: ``ck_orders_rider_required``
forbids a PICKED_UP order without a rider, so the handoff refused every real
order rather than violate the constraint. The vendor app could issue a PIN and
never spend it.

* ``dispatch`` — who gets the order, and the seam a real dispatcher replaces
* ``roster``   — the rider accounts an administrator maintains
* ``jobs``     — the rider app's own screens, including the delivery that
  finally moves an order to DELIVERED

``app.services`` re-exports these as ``dispatch_service``,
``rider_roster_service`` and ``rider_jobs_service``, matching the
``vendor_*_service`` convention.
"""
