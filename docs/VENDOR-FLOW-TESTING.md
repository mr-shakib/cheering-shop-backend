# Vendor flow — end-to-end testing runbook

Every call below was executed against a live local server, in this order, and passed.
Base URL: `http://localhost:8000/api/v1`. Envelope: `{"success":true,"data":{...}}`.

**Read this first — three things will block you if you don't know them:**

1. **The customer side does not exist yet.** `GET /restaurants`, `/cart`, `/cart/items`,
   `/checkout/summary`, `POST /orders`, `/users/me/addresses`, favorites, tracking and the
   WebSockets all return **501 NOT_IMPLEMENTED**. There is no API path that creates an order,
   so step 6 seeds one with SQL.
2. **Riders are assigned automatically, but they have to exist first.** Accepting an order
   dispatches a rider from whoever is verified and on shift. Enrol one with
   `POST /admin/riders` before step 8 or the pool is empty and the handoff 409s.
3. **Nothing writes `DELIVERED`.** That status is only ever read. Since earnings are derived
   from delivered orders, a payout is untestable until you force the status in SQL.

Steps 1–5, 7 and 9 are pure API and are what you actually hand over. Steps 6, 8 and 10 are
scaffolding to work around the three gaps above.

---

## 0. Prerequisites

```bash
docker compose up -d postgres redis
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

With `ENVIRONMENT=local`, every OTP response carries the code back as `data.debug_code`,
so you never need an inbox. **This does not happen in staging or production.**

A shell helper for the SQL steps:

```bash
psql() { docker compose exec -T postgres psql -U crshop -d crshop -tAc "$1"; }
```

---

## 1. Create an administrator — once per environment

Deliberately not an API route. Approving vendors is gated on shell access, not on knowing a URL.

```bash
.venv/bin/python scripts/create_admin.py admin@crshop.test
# prompts for a password; minimum 12 characters
```

```http
POST /auth/login
{"email":"admin@crshop.test","password":"crshopadmin123456"}
```

{
  "success": true,
  "data": {
    "tokens": {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4MzA1NmJkYS1kM2Q5LTQ0OTAtOGFjZC0zNjg4NWM4M2MzMTYiLCJ0eXBlIjoiYWNjZXNzIiwiaWF0IjoxNzg3MjA4NjgwLCJleHAiOjE3ODcyMTA0ODAsImp0aSI6ImxNTjNFaDdxTTIzZmtaSUZnRHNBRVEiLCJyb2xlIjoiQURNSU4ifQ.cmdBuLVuBFuyf-pggvhDVE23aRkyGIbyYMBQW5fK9SA",
      "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4MzA1NmJkYS1kM2Q5LTQ0OTAtOGFjZC0zNjg4NWM4M2MzMTYiLCJ0eXBlIjoicmVmcmVzaCIsImlhdCI6MTc4NzIwODY4MCwiZXhwIjoxNzg5ODAwNjgwLCJqdGkiOiJNRXN6NUhGWUZTQ0RYQ1Z3THRWb1NBIn0.KSj8AuIHwiWzZXq2ad8A6rwEqOwnKp4qjD5KyMgwixc",
      "token_type": "Bearer",
      "expires_in": 1800
    },
    "user": {
      "id": "83056bda-d3d9-4490-8acd-36885c83c316",
      "role": "ADMIN",
      "email": "admin@crshop.test",
      "phone": null,
      "full_name": "Administrator",
      "avatar_url": null,
      "is_email_verified": true,
      "is_phone_verified": false
    }
  }
}

⚠️ **The token is nested.** Take it from `data.tokens.access_token`, not `data.access_token`.
Send it as `Authorization: Bearer <token>` from here on. Call this one **`ADMIN_TOKEN`**.

---

## 2. Vendor submits an application — public, no token

First, prove the owner controls the email address:

```http
POST /auth/otp/send
{"email":"chef@demo.test","role":"VENDOR"}
```
→ `data.debug_code` is your OTP. Feed it into the next call as `otp_code`.

```http
POST /vendor/applications
{"otp_code":"2153",
 "business":{"name":"Demo Biryani House","business_type":"RESTAURANT",
   "business_category":"Street Food","branch_count":1,"cuisine_types":["Bengali"]},
 "location":{"address_line":"12 Nikunja 2, Dhaka","area":"Nikunja 2",
   "latitude":23.8305,"longitude":90.4199},
 "owner":{"full_name":"Demo Owner","email":"chef@demo.test",
   "phone":"01711111111","national_id":"1990123456789"},
 "documents":{"shop_image":"https://x.test/shop.jpg","owner_nid":"https://x.test/nid.jpg",
   "menu_list":"https://x.test/menu.pdf","trade_license":null},
 "payout":{"method":"BKASH","account_name":"Demo Owner","account_number":"01711111111",
   "bank_name":null,"branch_name":null},
 "agreed_to_terms":true}
```


{
  "success": true,
  "data": {
    "application_no": "PTN-76902",
    "status": "PENDING",
    "restaurant_id": "edf2ef20-7a6a-49cb-b386-00b5472107c3",
    "submitted_at": "2026-08-20T06:55:08.620364+00:00",
    "message": "Application submitted! We'll review it and get back to you within 2–3 business days by email."
  }
}

**201** → `{"application_no":"PTN-28912","status":"PENDING","restaurant_id":"0bef8dbf-…"}`

Keep **`application_no`** and **`restaurant_id`**.

- `business_type`: `RESTAURANT` | `GROCERY` | `PHARMACY`
- `payout.method`: `BANK` | `BKASH` | `NAGAD` | `ROCKET` — `bank_name`/`branch_name` are BANK-only
- `agreed_to_terms` must literally be `true`; `trade_license` may be `null`
- **No password field.** Submitting already creates the VENDOR user and the restaurant
  (unverified, CLOSED). Credentials get set in step 4.
- ⚠️ **`owner.phone` must be globally unique** — reusing one is a **409**
  `"This phone number is already registered to another account"`. Vary it per test run.

**Document uploads currently 503.** `POST /vendor/applications/uploads`
`{"file_type":"image/jpeg","file_name":"shop.jpg"}` returns `STORAGE_NOT_CONFIGURED`
because the Cloudflare R2 variables are blank in `.env` — the error `details` list
which ones. Pass any placeholder URL in `documents` meanwhile: nothing validates
that it resolves.

## 3. Applicant checks status — public

```http
GET /vendor/applications/PTN-28912?email=chef@demo.test
```

⚠️ **`?email=` is required** — without it you get a 400, not a 404.

---

## 4. Admin approves

```http
GET /admin/vendor-applications?status=PENDING&limit=20        # ADMIN_TOKEN
```

⚠️ The approve route takes the application's **UUID**, not the `PTN-…` number. The queue
listing gives it to you; from SQL it's:

```bash
psql "select id from vendor_applications where application_no='PTN-28912'"
```

```http
POST /admin/vendor-applications/{application_id}/approve      # ADMIN_TOKEN
{"note":"Docs verified"}
```

Approval only flips `is_verified` to true. The store stays **CLOSED** until the vendor opens
it themselves — approval must never surprise a kitchen with live orders.

To reject instead: `POST /admin/vendor-applications/{id}/reject` with `{"note":"reason"}` —
the note is emailed to the applicant.

---

## Values from this run

Everything below uses the real values produced in steps 1–4. Keep this list next to you —
each step tells you which one to paste where.

| What | Value |
|---|---|
| Swagger UI | http://localhost:8000/docs |
| Admin login | `admin@crshop.test` / `crshopadmin123456` |
| Vendor owner email | `bejobih170@neplis.com` |
| Vendor password (set in step 5) | `Passw0rd!23` |
| Application | `PTN-76902` — uuid `ae8102e8-3a38-48e0-a9c4-4f24bf286e74` |
| Restaurant id | `edf2ef20-7a6a-49cb-b386-00b5472107c3` |
| Vendor user id | `f4af4eac-c290-4787-8383-db7fef220920` |

### How to authorise in Swagger

1. Run the login endpoint and copy `data.tokens.access_token` from the response body.
2. Click the **Authorize** button (top right, padlock icon).
3. Paste **just the raw token** — no `Bearer` prefix, Swagger adds that itself.
4. **Authorize** → **Close**. The padlocks turn closed and every request now carries the header.

⚠️ **One token at a time.** Authorising with the vendor token replaces the admin token and
vice versa. Steps 6–9 and 11 need the **vendor** token; step 10c needs the **admin** token, so
you re-Authorize when you get there.

⚠️ **Tokens expire after 30 minutes.** When requests suddenly return 401, log in again and
re-Authorize — nothing else is wrong.

Each step below follows the same rhythm: find the endpoint, click **Try it out**, replace the
request body with the JSON given, click **Execute**, then read the response.

---

## 5. Vendor sets a password and signs in

The application form never asked for a password, so the first sign-in goes through the reset
flow. Three endpoints, in order. **No token needed for any of them.**

### 5a — `POST /auth/password/forgot`

```json
{"email":"bejobih170@neplis.com"}
```

Response:

```json
{"success":true,"data":{"message":"If the account exists, a reset code has been sent",
 "debug_code":"1067"}}
```

👉 **Copy `data.debug_code`.** It appears only because `ENVIRONMENT=local`; in staging and
production the field is absent and the code arrives by email.

### 5b — `POST /auth/password/reset`

```json
{"email":"bejobih170@neplis.com","code":"1067","new_password":"Passw0rd!23"}
```

Replace `1067` with the code from 5a.

⚠️ **Exactly these three fields.** The password field is `new_password`, not `password`, and
there is no `full_name` or `restaurant` here — that account and its storefront already exist
from the application. Sending the registration body gives you
`"new_password: Field required"`.

⚠️ **The code must come from 5a.** The OTP you spent submitting the application is single-use
and purpose-scoped; reusing it fails.

### 5c — `POST /auth/login`

```json
{"email":"bejobih170@neplis.com","password":"Passw0rd!23"}
```

👉 Copy **`data.tokens.access_token`** — nested, *not* `data.access_token` — and Authorize with
it as described above. This is your **vendor token** for steps 6–9 and 11.

---

## 6. Open the store and build a menu — vendor token

Approval only set `is_verified`. **The store is still CLOSED** until you open it.

### 6a — `PATCH /vendor/store/status`

```json
{"status":"OPEN"}
```

`OPEN` or `CLOSED`.

### 6b — `GET /vendor/profile`

No body. Confirm `"id"` is `edf2ef20-7a6a-49cb-b386-00b5472107c3` and `"is_verified": true`.

### 6c — `PATCH /vendor/profile`

```json
{"description":"Best kacchi in Nikunja","delivery_fee_base":40,"min_order_amount":200,"avg_prep_time_mins":25}
```

Every field is optional — send only what you're changing. Sending `is_verified`, `is_active`,
`commission_rate`, `slug` or `rating_avg` is a **400**, not a silent no-op: those are the
platform's levers, not the vendor's.

### 6d — `PUT /vendor/hours`

**PUT, not PATCH** — all seven days every time, because the screen always saves the whole week.

```json
{"mon":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "tue":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "wed":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "thu":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "fri":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "sat":{"is_open":true,"opens_at":"10:00","closes_at":"23:00"},
 "sun":{"is_open":false,"opens_at":null,"closes_at":null}}
```

24-hour `HH:MM`. A day with `is_open: true` must carry both times. `closes_at` earlier than
`opens_at` is legal — it means the store runs past midnight.

### 6e — `POST /vendor/menu/categories`

An item cannot exist without a category.

```json
{"name":"Biryani","sort_order":0}
```

👉 **Copy `data.id`** — this is your **category id**, needed in 6f.

### 6f — `POST /vendor/menu/items`

Paste the category id from 6e into `category_id`:

```json
{"name":"Mutton Kacchi","category_id":"PASTE_CATEGORY_ID","description":"Basmati, mutton, alu",
 "base_price":320,"is_veg":false,"prep_time_mins":20,
 "variants":[{"name":"Half","price":320,"is_default":true},
             {"name":"Full","price":560}],
 "add_ons":[{"name":"Borhani","price":40},
            {"name":"Extra Alu","price":30}]}
```

👉 **Copy `data.id`** — this is your **item id**, needed in step 7.

All prices are **whole taka** (stored internally as paisa). Variants *replace* the base price;
add-ons *add* to it.

On `PATCH /vendor/menu/items/{id}`, `variants` and `add_ons` are **replace-sets**: include an
`id` to edit a row in place, omit `id` to create one, and **anything you leave out is deleted**,
cascading into every cart holding it. Omit both keys entirely for a price-only edit.

Also available: `GET /vendor/menu`, `GET /vendor/menu/categories`,
`PATCH|DELETE /vendor/menu/categories/{id}`, `GET|PATCH|DELETE /vendor/menu/items/{id}`,
`PATCH /vendor/menu/items/{id}/status` with `{"is_available":false}`, and
`PATCH /vendor/menu/reorder` with `{"categories":[{"id":"…","sort_order":0}],"items":[]}`.

---

## 7. 🔧 Get an order into the queue — terminal, not Swagger

No API creates an order. `POST /orders`, `/cart/items` and `/checkout/summary` are scaffolded
and return **501**, so the order must be inserted into the database directly. This is the one
step Swagger cannot do.

### 7a — create the customer in Swagger

**`POST /auth/otp/send`**

```json
{"email":"cust1@demo.test","role":"CUSTOMER"}
```

👉 Copy `data.debug_code`.

**`POST /auth/otp/verify`**

```json
{"email":"cust1@demo.test","code":"PASTE_DEBUG_CODE","password":"Passw0rd!23","full_name":"Demo Customer"}
```

👉 Copy **`data.user.id`** — the **customer id**.

### 7b — insert the order in a terminal

Paste your customer id and item id into the two marked places:

```bash
psql() { docker compose exec -T postgres psql -U crshop -d crshop -tAc "$1"; }

CUSTOMER=PASTE_CUSTOMER_ID
ITEM=PASTE_ITEM_ID
RESTAURANT=edf2ef20-7a6a-49cb-b386-00b5472107c3

ORDER=$(psql "insert into orders
  (customer_id,restaurant_id,status,item_total,delivery_fee,commission_amount,
   grand_total,payment_method,delivery_address_text,delivery_latitude,delivery_longitude,
   auto_decline_at)
  values ('$CUSTOMER','$RESTAURANT','PENDING',64000,4000,6400,68000,'COD',
   '5 Nikunja 2, Dhaka',23.8310,90.4205, now()+interval '1 hour')
  returning id" | head -1)

psql "insert into order_items
  (order_id,menu_item_id,item_name,unit_price,add_ons_total,quantity,line_total)
  values ('$ORDER','$ITEM','Mutton Kacchi',32000,0,2,64000)"

echo "order id = $ORDER"
```

👉 **Copy the printed order id** — you paste it into Swagger throughout step 8.

Amounts are in **paisa**: 2 × ৳320 = ৳640 = `64000`. Three things that will bite:

- `head -1` is required — psql prints its `INSERT 0 1` tag on the line *after* the returned id,
  and feeding that into a UUID column fails with `invalid input syntax for type uuid`.
- `grand_total` must equal
  `item_total + delivery_fee + packaging_fee + tax_amount + platform_fee + tip − discount`.
- `line_total` must equal `(unit_price + add_ons_total) × quantity`.

---

## 8. Work the order — vendor token, back in Swagger

### 8a0 — enrol a rider first, as admin

Accepting an order dispatches a rider automatically, and dispatch can only pick somebody
who exists, is verified and is on shift. One call, once per environment:

```http
POST /admin/riders                                       # ADMIN_TOKEN
{"full_name":"Demo Rider","phone":"+8801799000001","vehicle_type":"MOTORCYCLE"}
```

Both `is_online` and `is_verified` default to true, so that rider is immediately
dispatchable. `GET /admin/riders?online_only=true` shows the pool. Skip this and everything
below still works up to 8e, which then has nobody to hand the food to.

Re-Authorize with the **vendor** token before continuing.

### 8a — `GET /vendor/orders`

Set the `status` parameter to `ACTIVE` (= PENDING + PREPARING + READY). It also takes an Order
tab — `NEW`, `PREPARING` (= PREPARING + READY) or `COMPLETE` (= PICKED_UP + DELIVERED) — a single
status, or a comma-separated list. Your seeded order should appear under `NEW`.

Rows carry a line *count*, not the lines themselves.

### 8b — `GET /vendor/orders/{order_id}`

Paste the order id from 7b. This is the full order: items, customer, address.

### 8c — `POST /vendor/orders/{order_id}/accept`

**No body** — just the path parameter. PENDING → PREPARING, and this cancels the auto-decline.

To refuse instead: `POST /vendor/orders/{order_id}/reject` with `{"reason":"Out of stock"}`.

### 8d — `POST /vendor/orders/{order_id}/ready`

**No body.** PREPARING → READY.

👉 **This is where the handoff PIN is issued** — read `data.handoff_code` from the response,
e.g. `7696`. `GET /vendor/orders/{id}` re-displays it while the order is READY, so a restart
can't strand a pickup.

### 8e — `POST /vendor/orders/{order_id}/handoff`

```json
{"rider_pin":"7696"}
```

This returns **200** as long as a rider was dispatched when you accepted at 8c. If you
skipped 8a0 you get `409 "No rider is available to take this order"` — enrol one and reassign:

```http
POST /admin/riders                                       # ADMIN_TOKEN
{"full_name":"Demo Rider","phone":"+8801799000001","vehicle_type":"MOTORCYCLE"}

POST /admin/orders/{order_id}/assign-rider               # ADMIN_TOKEN
{}
```

An empty body means "dispatch picks"; pass `{"rider_id":"…"}` to name one. Then re-Authorize
as the vendor and hit **Execute** on the handoff again.

A wrong PIN is capped by an attempt counter rather than by the comparison: after
`HANDOFF_MAX_ATTEMPTS` failures the PIN is dead. **Call `POST /vendor/orders/{id}/ready`
again** — on an already-READY order it issues a fresh code and restores the budget.

---

## 9. 🔧 Force delivery — terminal

Nothing in the API writes `DELIVERED`.

```bash
psql "update orders set status='DELIVERED', delivered_at=now() where id='$ORDER'"
psql "select status from orders where id='$ORDER'"     # → DELIVERED
```

Do this before step 10: the balance is a query, not a column —
`Σ(item_total − commission_amount)` over DELIVERED orders, minus every payout not FAILED.
Without a delivered order the balance is zero and no payout can succeed.

---

## 10. Money and insights — back in Swagger

### 10a — `GET /vendor/earnings`

No body. Expect `"available_balance": 576.0` — ৳640 of items minus ৳64 commission.
**If it reads `0.0`, step 9 didn't take.**

### 10b — `POST /vendor/payouts`

```json
{"amount":100,"method":"BKASH","account_number":"01711111111","account_name":"Demo Owner"}
```

→ **201**. 👉 Copy `data.id` — the **payout id** for 10c.

Before a delivered order exists this is a **400**,
`"Insufficient balance: 0.00 taka available"` — the correct answer, not a bug.
`method`: `BANK` | `BKASH` | `NAGAD` | `ROCKET`; `bank_name` and `branch_name` are BANK-only.
Destination details are per-request, not read from the application's saved payout block.

### 10c — admin settles it

The payout lands as `PROCESSING`; no gateway moves money, so a human confirms the transfer.

**Re-Authorize as admin first** — `POST /auth/login` with:

```json
{"email":"admin@crshop.test","password":"crshopadmin123456"}
```

Copy `data.tokens.access_token`, click **Authorize**, replace the vendor token with it.

Then **`GET /admin/payouts`** with `status=PROCESSING` to see the queue, and
**`POST /admin/payouts/{payout_id}/complete`** with an empty body:

```json
{}
```

To bounce it instead: `POST /admin/payouts/{payout_id}/fail` with `{"reason":"…"}` — the amount
returns to the balance by arithmetic, with no compensating write.

👉 **Re-Authorize with the vendor token** before continuing to 10d or step 11.

### 10d — the read-only screens

All GET, no body, all working:

`GET /vendor/dashboard` · `GET /vendor/analytics` · `GET /vendor/performance` ·
`GET /vendor/reviews` · `GET /vendor/reviews/summary` · `GET /vendor/reports/csv` ·
`GET /vendor/earnings` · `GET /vendor/payouts`

`analytics` takes optional `date_from` / `date_to` parameters and defaults to the last 30 days.
It counts DELIVERED orders only and uses each order's `commission_amount` snapshot, so changing
a vendor's commission rate never rewrites historical earnings.

---

## 11. Promotions — vendor token, independent of the order flow

### `POST /vendor/promotions`

```json
{"discount_type":"PERCENTAGE","discount_value":15,"max_discount":100,
 "min_order_amount":300,"item_ids":null,"starts_at":null,
 "ends_at":"2030-01-01T00:00:00Z","budget_cap":5000}
```

👉 Copy `data.id` for the detail and update calls.

`discount_type`: `PERCENTAGE` | `FLAT` | `FREE_DELIVERY`. `discount_value` is percent 1–100 for
PERCENTAGE, whole taka for FLAT, and **omitted entirely** for FREE_DELIVERY. `max_discount` is
PERCENTAGE-only. `item_ids: null` means the whole menu. `ends_at` is required; `starts_at`
defaults to now.

### `GET /vendor/promotions` · `GET /vendor/promotions/{promotion_id}`

No body.

### `PATCH /vendor/promotions/{promotion_id}`

```json
{"is_active":false}
```

or, to end it early and irreversibly:

```json
{"end_now":true}
```

Only those two fields are writable — changing the discount under customers who already saw the
offer would be a bait-and-switch.

---

## Appendix — the one-call shortcut for a *new* vendor

**This is an alternative to steps 2–5, not part of them.** It does not apply to
`bejobih170@neplis.com`, who already came through the application flow. Use it when you just
want a working vendor account fast, without the application and admin approval.

**`POST /auth/otp/send`**

```json
{"email":"chef2@demo.test","role":"VENDOR"}
```

**`POST /auth/register/vendor`** — paste the `debug_code` into `code`:

```json
{"email":"chef2@demo.test","code":"PASTE_DEBUG_CODE","password":"Passw0rd!23",
 "full_name":"Demo Owner",
 "restaurant":{"name":"Demo Biryani House","description":"Kacchi + more",
   "phone":"01722222222","address_line":"12 Nikunja 2, Dhaka",
   "latitude":23.8305,"longitude":90.4199,"cuisine_types":["Bengali"]}}
```

Returns tokens immediately — Authorize and jump straight to step 6. The restaurant it creates
is *unverified*, which matters only for customer-facing discovery; every vendor endpoint works
regardless. Use a **different phone number** than any existing account.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `"Authorization header missing"` | Not authorised in Swagger, or the token was pasted with a `Bearer ` prefix. Paste the raw token only. |
| 401 after it was working | Token expired (30 min). Log in again and re-Authorize. |
| 404 `"No restaurant is registered to this vendor account"` | You're authorised as admin or customer on a `/vendor/*` route. Re-Authorize with the vendor token. |
| `"new_password: Field required"` on reset | You sent the `register/vendor` body. `/auth/password/reset` takes only `email`, `code`, `new_password`. |
| Reset code rejected | You reused the application's OTP. Codes are single-use — get a fresh one from `/auth/password/forgot`. |
| `RATE_LIMITED` on `/vendor/applications` | 5 submissions per hour **per IP**. Clear it: `docker compose exec -T redis redis-cli DEL rl:vendorapp:submit:127.0.0.1` |
| `RATE_LIMITED` on login or OTP | Wipe every counter: `docker compose exec -T redis redis-cli --scan --pattern 'rl:*' \| tr -d '\r' \| while read -r k; do docker compose exec -T redis redis-cli DEL "$k" >/dev/null; done` |
| 409 `"phone number is already registered"` | `owner.phone` is globally unique. Change it per test run. |
| `invalid input syntax for type uuid` | A psql `returning id` captured without `head -1`. |
| `available_balance` is `0.0` | No DELIVERED order — step 9 didn't run. |

---

## What you can and cannot hand over

| Area | State |
|---|---|
| Auth — OTP, register, login, 2FA, reset, refresh, logout | ✅ working |
| Vendor applications — submit, status, admin approve/reject | ✅ working |
| Vendor storefront, hours, menu, orders, insights, payouts, promotions | ✅ working |
| Admin — application queue, restaurant verify, payout queue | ✅ working |
| Document uploads | ⚠️ 503 — Cloudflare R2 variables unset in `.env` |
| Handoff `READY → PICKED_UP` | ✅ working — needs a rider enrolled via `POST /admin/riders` |
| Rider roster and assignment (admin) | ✅ working |
| `DELIVERED`, and therefore earnings and payouts | ⚠️ reachable only via SQL |
| Customer — discovery, cart, checkout, place order, addresses, favorites | ❌ **501** |
| Rider app — a rider signing in, seeing the job, delivering | ❌ does not exist |
| Tracking, messaging, WebSockets | ❌ **501** |

Two behaviours worth stating in the handover doc: a menu item or order belonging to another
vendor returns **404, never 403**, so nobody can probe for another vendor's records; and no
vendor endpoint accepts a restaurant id — ownership always comes from the token.
