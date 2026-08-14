# Development workflow

How to test what exists and add what doesn't.

---

## The three layers of testing

They catch different failures. You want all three, in this order.

| Layer | Command | Runs against | Catches |
|---|---|---|---|
| **1. Unit + integration** | `make test` | Your machine, real Postgres + Redis | Logic bugs, broken constraints, spec drift |
| **2. Local smoke** | `make smoke` | A local HTTP server | Wiring, dependency-injection, envelope shape |
| **3. Production smoke** | `make smoke-prod` | The live deployment | TLS, Traefik routing, container env, network path |

Layer 3 exists because a green `make test` proves nothing about the deployment.
Passing tests with a misconfigured Traefik route look identical from your
laptop — right up until a client gets a 502.

---

## Testing what already exists

### 1. Automated suite

```bash
make up          # postgres + redis
make migrate
make test
```

39 tests. No mocked database — several behaviours under test (case-insensitive
email via `citext`, the 2FA CHECK constraint, OTP single-use) are enforced *by
Postgres*, and a mock would happily let a broken implementation pass.

Useful variants:

```bash
.venv/bin/pytest tests/test_auth_flows.py -v          # one file, verbose
.venv/bin/pytest -k "2fa" -v                          # matching tests only
.venv/bin/pytest -x                                   # stop at first failure
```

### 2. Local smoke test — the full journey

```bash
make dev         # services + migrations + server, one command
# in another terminal:
make smoke
```

27 checks, including the complete signup → login → 2FA enrol → TOTP verify →
token refresh → reuse-detection journey. Locally the OTP code is returned in the
response (`debug_code`), which is what makes the end-to-end run possible.

### 3. Production smoke test

```bash
make smoke-prod
```

15 checks. The OTP-dependent steps skip automatically, because a deployed
environment correctly withholds the code — and the script *asserts* that
withholding, so a misconfigured `ENVIRONMENT` fails the run.

### 4. By hand, in the browser

<https://srv1128440.hstgr.cloud/docs> — the interactive Swagger UI. Every
endpoint with its real request schema. Try `POST /auth/otp/send`, then
**Authorize** with the returned token to call protected routes.

> Only while `ENABLE_DOCS=true`. Turn it off before real users exist.

---

## Adding a new module

The loop, using Users & Addresses (#13–18) as the example.

### Step 1 — Start the environment

```bash
make dev
```

### Step 2 — Write the service layer first

Business logic goes in `app/services/`, not in the route handler. Handlers stay
thin: validate, delegate, shape the response. Anything touching more than one
table, or with a rule worth testing on its own, belongs in a service.

```
app/services/address_service.py
```

### Step 3 — Fill in the endpoint

The route already exists and returns 501. Replace the
`raise NotImplementedYetError()` with a call into your service.

```
app/api/v1/endpoints/addresses.py
```

Do **not** add or rename routes casually — `tests/test_route_inventory.py`
fails the build if the surface stops matching the spec. If a new endpoint is
genuinely needed, add it to `EXTENDED_ENDPOINTS` there with a written
justification, as `/auth/refresh` did.

### Step 4 — Add response schemas

```
app/schemas/address.py
```

Return `SuccessResponse[YourModel]` so OpenAPI documents the real payload and
your frontend can generate typed clients.

### Step 5 — Write tests alongside

```
tests/test_address_flows.py
```

Follow `test_auth_flows.py`: real database, no mocks, one test per *behaviour*
rather than per function. Test the things that would actually hurt — a user
reading another user's addresses, two defaults existing at once, an address
surviving deletion inside a historical order.

### Step 6 — Verify locally

```bash
make test         # must be green
make lint         # ruff + mypy
make smoke        # server-level sanity
```

If you touched a model, also:

```bash
.venv/bin/alembic check      # must say "No new upgrade operations detected"
```

Drift means the models and the database disagree — write a migration:

```bash
make revision m="add whatever"
make migrate
```

**Never edit migration `0001`.** It has already run on the production server;
changing it will not re-run there.

### Step 7 — Ship

```bash
git add -A
git commit -m "Add Users & Addresses module (#13-18)"
git push
```

Then Dokploy → your service → **Deploy**, and:

```bash
make smoke-prod
```

---

## Guard rails already in place

These fail the build rather than letting a mistake through:

| Test | Prevents |
|---|---|
| `test_route_inventory.py` | The API drifting from the spec's 47 endpoints, or undocumented routes appearing |
| `test_schema_parity.py` | `db/schema.sql` and migration 0001 diverging |
| `test_migration_drift.py` | Models and database disagreeing |
| `test_app_contract.py` | The response envelope, RBAC, or money conversion regressing |

---

## Conventions worth knowing before you write code

**Money is paisa.** `1059` on the wire is `105900` in the column. Convert only
in `app/core/money.py`. Never do money arithmetic with floats —
`int(10.55 * 100)` is `1054`.

**Vendor endpoints take `restaurant: VendorRestaurant`.** Never query
`Restaurant.owner_id` inline — see decision D1 in
[database-schema.md](database-schema.md).

**Let the database enforce invariants.** Cross-restaurant carts, role
mismatches, and orders whose totals do not add up are already rejected by
constraints. Your service layer produces the *friendly* error for something the
database has already made impossible — it is not the last line of defence.

**Errors are raised, not returned.** `raise NotFoundError("...")` — the
registered handlers turn it into the spec §2 envelope. Never construct an error
response by hand.

**Sessions do not auto-commit.** Endpoints call `await db.commit()` explicitly,
so transaction boundaries stay visible at the call site. That matters for the
multi-step flows in this spec (cart → order, handoff, default-address swap)
where a partial write would corrupt state.
