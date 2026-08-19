# CR Shop — Backend

Food delivery backend implementing [`cr-shop-backend-api-specification.md`](cr-shop-backend-api-specification.md) v1.0.0.

FastAPI · PostgreSQL 16 + PostGIS · SQLAlchemy 2.0 (async) · Alembic · Redis · arq

---

## Status

| | |
|---|---|
| **Step 1** Stack alignment | Complete |
| **Step 2** Database schema | Complete — 25 tables, 21 invariant assertions passing |
| **Step 3** Project scaffolding | Complete — all 47 endpoints routed, zero model drift |
| **Step 4** API implementation | **Auth and Vendor modules complete** (35 endpoints, 129 tests). Discovery, cart and orders return `501 NOT_IMPLEMENTED` |

---

## Quick start

```bash
make install     # uv venv + dependencies
cp .env.example .env
# generate secrets:  openssl rand -hex 32   (one per secret in .env)

make up          # postgres + redis via docker compose
make migrate     # apply migration 0001
make run         # http://localhost:8000/docs
```

```bash
make test        # pytest — 39 tests, real Postgres + Redis
make smoke       # HTTP smoke test vs a local server (27 checks, full auth journey)
make smoke-prod  # HTTP smoke test vs the live deployment (15 checks)
make lint        # ruff + mypy
make verify-db   # the 21 schema invariant assertions
```

**Adding a module?** Read [docs/development-workflow.md](docs/development-workflow.md).
**Setting up OTP email?** Read [docs/email-setup-resend.md](docs/email-setup-resend.md).
**Frontend integrating auth?** Send them [docs/AUTH-API.md](docs/AUTH-API.md).
**Building the restaurant app?** Send them [docs/VENDOR-API.md](docs/VENDOR-API.md).

> **Host ports:** Postgres binds `5433` by default, not 5432, because 5432 is
> so often already taken. Override with `POSTGRES_HOST_PORT` in `.env`.

---

## Layout

```
app/
  core/          config, database, redis, security, errors, money, responses
  models/        SQLAlchemy models — a mirror of db/schema.sql
  schemas/
    requests/    request bodies, one module per domain (re-exported at package level)
    vendor/      vendor response models, same convention
  services/
    vendor/      the vendor domain: storefront, applications, orders, insights,
                 finance, promotions — aliased as vendor_*_service in app.services
    *_service.py auth, menu, OTP, tokens, storage, email
  api/
    deps.py      auth, RBAC, pagination, idempotency
    v1/
      router.py  aggregation
      endpoints/ one module per spec section
  workers/       arq background tasks
db/
  schema.sql              authoring source for the schema
  verify_constraints.sql  21 assertions that the DB REJECTS invalid data
migrations/      Alembic; 0001 embeds db/schema.sql verbatim
docs/
  database-schema.md      ER model, index strategy, decisions D1–D6
tests/
```

---

## Things that will bite you if you don't know them

**Money is stored in paisa, not taka.** `item_total: 1059` on the wire is
`105900` in the column. Conversion happens only in `app/core/money.py`. Never do
money arithmetic in floats — `int(10.55 * 100)` is `1054`.

**`passlib` does not work here.** The standard `passlib[bcrypt]` recipe imports
fine and then raises `MissingBackendError` at runtime, because bcrypt 5.0
removed the `__about__` attribute passlib 1.7.4 probes for. Passwords use
`argon2-cffi` directly.

**Redis is a hard dependency, not a cache.** It owns live rider position and
nearest-rider dispatch (decision D2). `/health/ready` returns 503 without it.

**Vendor endpoints must use the `VendorRestaurant` dependency.** Never query
`Restaurant.owner_id` inline — see decision D1 in
[docs/database-schema.md](docs/database-schema.md).

**Don't edit migration 0001.** `db/schema.sql` is the authoring source and
`tests/test_schema_parity.py` enforces that the two agree; but 0001 has already
been applied in every environment that exists, so schema changes need a *new*
migration.

**The database enforces more than you think.** Cross-restaurant carts, role
mismatches, and orders whose totals don't add up are rejected by constraints,
not just by service code. `db/verify_constraints.sql` proves it.

---

## Deploying

**Step-by-step walkthrough: [deploy/GO-LIVE.md](deploy/GO-LIVE.md)** — Hostinger
VPS + Dokploy, no domain required. Reference docs:
[deploy/DOKPLOY.md](deploy/DOKPLOY.md) (Dokploy) ·
[deploy/README.md](deploy/README.md) (bare Ubuntu).

```bash
# 1. Pre-flight: the schema needs PG>=15 + these extensions. Check FIRST.
psql "$DATABASE_URL" -c "SHOW server_version;" \
  -c "SELECT name FROM pg_available_extensions
      WHERE name IN ('postgis','citext','pg_trgm');"

# 2. Behind a reverse proxy, set the proxy's address or subnet:
FORWARDED_ALLOW_IPS=172.16.0.0/12     # never "*" on a public host
ENVIRONMENT=staging                    # or production
ENABLE_DOCS=false                      # optional; unset = on except in production
```

The container runs `alembic upgrade head` on start via `docker-entrypoint.sh`,
so a fresh database is migrated automatically. **With more than one replica, run
migrations as a one-shot job instead** — concurrent upgrades contend on the
version table.

Deployed environments automatically: hide dependency versions and connection
errors from `/health/ready`, and never echo OTP codes in responses.

---

## Verification performed

Everything below was executed, not assumed:

- Migration 0001 applied to PostgreSQL 16 / PostGIS 3.4 → 25 tables, 4 partitions, 94 indexes, 10 enums
- `db/verify_constraints.sql` → **21/21 invariant assertions pass**, including both cross-restaurant cart bypass attempts
- Geospatial discovery profiled at 50,002 restaurants → `Bitmap Index Scan on ix_restaurants_location`, 0.035 ms
- `alembic check` → **no drift** between ORM models and the migrated schema
- `pytest` → **36/36 pass** against real Postgres + Redis (no mocks), including refresh-token reuse detection and TOTP-at-rest encryption
- `ruff check` → clean
- Deploy path exercised in a container against an **empty** database:
  `alembic upgrade head` ran on start (33 tables), uvicorn came up with
  `--proxy-headers`, and with `ENVIRONMENT=staging` the readiness probe hid
  versions, OTP responses carried no code, and `/auth/login` returned
  `401 x10 → 429`
- Server booted; `/health/ready` reaches live PostGIS 3.4 and Redis 7.4.9
- Auth flow exercised over HTTP: OTP issue → 429 on resend → verify → session →
  RBAC 403 for a customer on a vendor endpoint
- OpenAPI documents every routed operation — 47 spec endpoints plus the `[EXTENDED]` set, each justified in `tests/test_route_inventory.py`

---

## Known spec discrepancies

Found while implementing. The endpoint **total** of 47 is correct, but:

1. **No endpoint redeems a refresh token.** §1 mandates an access/refresh pair;
   §3 defines no `/auth/refresh`. As specified, every user is silently logged
   out when their 30-minute access token expires. Added as `[EXTENDED]` and
   tracked separately in `tests/test_route_inventory.py`.
2. **§11's method breakdown contradicts §5's table.** §11 says GET 21 / POST 20 /
   PUT 2 / PATCH 3 / DELETE 1 — which sums to 47 and therefore leaves no room for
   the 2 WebSocket endpoints it also counts. Counting §5 directly gives
   **GET 15 / POST 23 / PUT 2 / PATCH 3 / DELETE 2 / WS 2**. There are two
   DELETEs (#8, #17), not one.
3. **§10's cart claim is not true as written.** It says the single-restaurant
   rule is enforced at database level by `restaurant_id` on `Cart`. That alone
   does not prevent a `CartItem` referencing another restaurant's menu item.
   See docs §3.1 for the composite-FK fix that does.
4. **§6 omits `OrderItem`.** Orders had totals but no line items.

## Still unresolved (spec §12)

- Route polylines: server-side Directions API vs client-side straight-line
- Payment webhooks for bKash/Visa redirect flows — `orders.payment_status` and
  `payment_reference` are ready to receive them, but no `payment_transactions`
  ledger exists yet
- ~~Vendor rejection: auto-rebook with a nearby vendor, or refund and suggest?~~
  **Resolved: refund and suggest.** `POST /vendor/orders/{id}/reject` cancels the
  order and marks a paid one `REFUNDED`; it does not re-place the cart
  elsewhere. A substitute restaurant has different prices, a different menu and
  a different delivery time, so recreating "the same order" would mean deciding
  on the customer's behalf what they will pay and wait for — and charging
  someone for food they did not choose is the worse failure mode. The recovery
  flow belongs in the customer app, on top of discovery. Revisit if product
  wants automatic matching.
