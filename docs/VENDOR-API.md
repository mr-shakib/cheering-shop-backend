# Cheering Shop — Vendor API

**For the mobile/frontend team building the restaurant app.** Covers the
storefront, the menu, the live order queue, the rider handoff, and earnings.

Base URL: `https://api.cheeringshop.online/api/v1`
Interactive docs: `https://api.cheeringshop.online/docs`

Signing up as a vendor is covered in [AUTH-API.md](AUTH-API.md) §11. Everything
in this document assumes you already hold a `VENDOR` access token.

Everything below is implemented and covered by tests. The customer ordering
flow that fills your queue is live, riders are dispatched automatically, and an
order now runs all the way to DELIVERED. What is still missing is real-time
push and the rider-side display of the handoff code — see
[Known limitations](#known-limitations).

---

## Contents

1. [Conventions](#1-conventions) — envelope, pagination, money
2. [Getting approved](#2-getting-approved) — the gate before anything works
3. [Storefront](#3-storefront) — profile, opening and closing
4. [Menu](#4-menu) — categories, items, variants, add-ons
5. [Order queue](#5-order-queue) — polling and filtering
6. [The order lifecycle](#6-the-order-lifecycle) — accept, reject, ready
7. [Handoff](#7-handoff) — the rider PIN
8. [Analytics](#8-analytics) — earnings and top sellers
9. [Images](#9-images) — presigned uploads
10. [Endpoint summary](#10-endpoint-summary)
11. [Dashboard & performance](#11-dashboard--performance) — the app's landing tabs
12. [Earnings & payouts](#12-earnings--payouts) — balance, withdraw, history
13. [Business hours](#13-business-hours) — the weekly schedule
14. [Promotions](#14-promotions) — offers, budgets, pause/end

---

## 1. Conventions

### The envelope

Identical to the auth API. Success:

```json
{ "success": true, "data": { ... }, "meta": { ... } }
```

Failure:

```json
{
  "success": false,
  "error": { "code": "CONFLICT", "message": "...", "details": ["..."] }
}
```

Branch on `error.code`, never on `error.message` — messages get reworded, codes
do not.

### Pagination

List endpoints take `?limit=&offset=`. `limit` defaults to 20 and is capped at
100. The `meta` block carries `total`, `limit`, `offset`, `page` and `has_more`.

### Money

**Every amount on the wire is in whole taka**, as a JSON number. The server
stores paisa internally and converts at the edge, so you never divide by 100.

Amounts come back with a decimal point — `180.0`, `319.5`, not `180` — because
they are decimals server-side. Parse them as floating point and format for
display; do not compare them against integers with a strict equality check.
Send them either way: `320` and `320.00` are both accepted.

### Ids

UUIDv4 strings. Path parameters are validated, so a malformed id is a `400`
before it reaches any handler.

### Your restaurant is implicit

No vendor endpoint takes a restaurant id. It is resolved from your token. Every
response still echoes `restaurant_id` — store it, because multi-outlet vendors
are a planned change and that field is how you will select between outlets
without a breaking API change.

An id belonging to another vendor returns `404`, not `403`. That is deliberate:
a `403` would confirm the record exists.

---

## 2. Getting approved

A vendor account works the moment it is registered. What does **not** work is
selling.

Three independent switches decide whether customers can order from you:

| Flag | Owner | Meaning |
|---|---|---|
| `is_verified` | Administrator | Your restaurant has been approved |
| `is_active` | Administrator | Not suspended by the platform |
| `status` | **You** | `OPEN` or `CLOSED` |

`GET /vendor/profile` returns all three plus **`is_accepting_orders`**, which is
simply all three being true. Render your "you are live" indicator from that one
field — computing it yourself is how a screen ends up claiming a pending
restaurant is open for business.

Until an administrator approves you:

- you **can** sign in, build your entire menu and upload images;
- you **cannot** appear in customer discovery or receive an order.

There is no queue-position endpoint and no push when approval happens. Signed
in, poll `GET /vendor/profile` on app resume; before credentials exist (the
partner-application flow collects no password), poll
`GET /vendor/applications/{no}?email=` — see [AUTH-API.md](AUTH-API.md) §11.
Approval and rejection are also emailed.

---

## 3. Storefront

### Read it

```http
GET /vendor/profile
```

Use this rather than the public `GET /restaurants/{id}` — that endpoint filters
on `is_active AND is_verified`, so it returns `404` for your own restaurant
until you are approved.

```json
{
  "success": true,
  "data": {
    "id": "a4c99d72-…",
    "name": "Test Kitchen",
    "slug": "test-kitchen",
    "status": "CLOSED",
    "is_verified": false,
    "is_active": true,
    "is_accepting_orders": false,
    "rating_avg": 0.0,
    "rating_count": 0,
    "delivery_fee_base": 60.0,
    "min_order_amount": 200.0,
    "avg_prep_time_mins": 20,
    "commission_rate": 0.15,
    "latitude": 23.7936,
    "longitude": 90.4064
  }
}
```

### Change it

```http
PATCH /vendor/profile
{ "name": "Test Kitchen & Grill", "min_order_amount": 70 }
```

PATCH semantics: a field you omit is untouched, and an explicit `null` clears
it. Send only what changed.

Three rules worth knowing before you build the form:

- **`delivery_fee_base` is read-only.** It comes back on the profile so you can
  show what your customers pay, but sending it is a `400`. Delivery is priced
  the same from every restaurant — ৳10 covering the first kilometre, then ৳8 per
  started kilometre — so it is platform policy, not a field on your form.
- **`latitude` and `longitude` move together.** Sending one alone is a `400`.
  Half an update would place the restaurant at a coordinate it has never
  occupied — and discovery indexes that point.
- **Unknown fields are rejected, not ignored.** `slug`, `is_verified`,
  `is_active`, `commission_rate` and `rating_avg` are not yours to set, and
  sending one returns `400` rather than silently doing nothing.
  `commission_rate` is read-only here by design — it is the platform's cut of
  your `item_total`, set by an administrator through
  `PATCH /admin/restaurants/{id}/commission` (AUTH-API.md §11.1b) and applied
  to future orders only, since each order records the commission it was
  actually charged. `slug` is frozen
  on purpose: it is your public URL, and regenerating it on every rename would
  break links and QR codes already in circulation.

### Open and close

```http
PATCH /vendor/store/status
{ "status": "OPEN" }
```

```json
{
  "success": true,
  "data": {
    "restaurant_id": "a4c99d72-…",
    "status": "OPEN",
    "is_accepting_orders": false,
    "message": "Saved, but your restaurant is still awaiting approval — customers cannot see or order from it yet"
  }
}
```

Setting `OPEN` before approval succeeds and has no effect. Show `message` —
it names whichever switch is still off.

**There are no scheduled opening hours.** This is a manual toggle and nothing
closes the store on your behalf. If your app has a "closes at 11pm" setting,
it is your client that must call this endpoint.

---

## 4. Menu

### Structure

```
Category  (Starters, Biryani, Drinks)
└── Item  (Chicken Biryani)
    ├── Variants  — REPLACE the price:  Half 180 / Full 320
    └── Add-ons   — ADD to the price:   Extra raita +30
```

That distinction is the one thing to get right. A variant's `price` **is** the
price the customer pays; `base_price` becomes a "from" display price the moment
an item has variants. An add-on's `price` is added on top.

### Build order

You must create a category first — items require a `category_id`.

```http
POST /vendor/menu/categories
{ "name": "Biryani", "sort_order": 1 }
```

```http
POST /vendor/menu/items
{
  "name": "Chicken Biryani",
  "category_id": "…",
  "base_price": 180,
  "is_veg": false,
  "prep_time_mins": 25,
  "variants": [
    { "name": "Half", "price": 180, "is_default": true },
    { "name": "Full", "price": 320 }
  ],
  "add_ons": [{ "name": "Extra raita", "price": 30 }]
}
```

Item, variants and add-ons are created in one transaction — all of it lands or
none of it does. At most one variant may be `is_default`; if you mark none, the
first becomes the default so your client always has something to preselect.

### Read it back

```http
GET /vendor/menu
```

Returns the whole tree: every category, every live item, with variants and
add-ons. **This is not the same as the public menu** — it includes inactive
categories and sold-out items, because an item that disappeared when it sold out
is one you can never switch back on.

`GET /vendor/menu/categories` returns just the categories with an `item_count`,
for a settings screen that does not need the items.

### Edit an item

```http
PATCH /vendor/menu/items/{id}
{ "base_price": 200 }
```

`variants` and `add_ons` are **replace-sets** when you send them, and are left
alone when you do not:

- send a variant **with** its `id` → updated in place
- send one **without** an `id` → created
- leave one out of the list → **deleted**

Send the id for anything you are keeping. Deleting a variant cascades into every
cart holding it, so a price edit that recreates its variants empties baskets;
one that reuses their ids does not.

### One variant or add-on at a time

The rule is short: **whole list → the item `PATCH` above; one row → these.**

The replace-set is a Save. For an "add size", "reprice this extra" or "remove
option" button, touch one row instead — and never send a partial list to the
item `PATCH` to do it, because everything you leave out is deleted.

```http
POST /vendor/menu/items/{id}/variants
{ "name": "Family", "price": 620 }
```

```http
POST /vendor/menu/items/{id}/add-ons
{ "name": "Extra cheese", "price": 40 }
```

`201` in both cases, and the body is the **whole item** — adding a variant can
change rows you did not send, so re-render from the response rather than
appending locally.

Optional fields: `is_available` (default `true`), `sort_order` (omit and it
appends after the current last one), and on a variant `is_default`.

```http
PATCH /vendor/menu/items/{id}/variants/{variant_id}
{ "price": 340 }
```

```http
PATCH /vendor/menu/items/{id}/add-ons/{add_on_id}
{ "name": "Extra raita (large)", "is_available": false }
```

PATCH semantics: an omitted field is left alone. Every field backs a NOT NULL
column, so there is nothing to clear — sending `null` leaves the value as it
was. Editing in place keeps the id, which is what stops a price change from
emptying the carts holding that option.

```http
DELETE /vendor/menu/items/{id}/variants/{variant_id}
DELETE /vendor/menu/items/{id}/add-ons/{add_on_id}
```

`200` with the updated item, for both PATCH and DELETE.

Four things worth knowing before you wire the buttons up:

- **These deletes are hard, unlike an item's.** `cart_items` cascades, so every
  cart line holding that variant — or that add-on — goes with it. To retire an
  option without emptying live baskets, `PATCH` that option to
  `is_available: false` instead: it stops being orderable and the lines survive.
- **The first variant on an item is always the default**, whatever you send,
  and a new `is_default: true` demotes the previous one. An item with variants
  and no default leaves the customer nothing preselected, and a variant's price
  is the real price. For the same reason `is_default: false` on the *current*
  default is a `400` — promote the replacement, which demotes this one for you.
- **Deleting the default promotes the next variant** in display order, for the
  same reason.
- **A duplicate name is a `409`**, not a silent second row: names are unique per
  item. So is exceeding 50 variants or 50 add-ons on one item.

A variant id that belongs to another item is a `404` — the item in the path
owns the row you are editing or deleting.

### The sold-out toggle

```http
PATCH /vendor/menu/items/{id}/status
{ "is_available": false }
```

Its own endpoint, with a one-field body, because it gets pressed dozens of times
a service from a list screen — use it rather than a full `PATCH`.

### Removing things

`DELETE /vendor/menu/items/{id}` is a soft delete: the item stops appearing
anywhere but its row survives, because order history and your analytics point at
it. Deleting an item that sold last month must not restate last month.

`DELETE /vendor/menu/categories/{id}` returns **`409`** while the category still
holds items — the underlying cascade would take every item with it. Move the
items, or `PATCH` the category to `is_active: false` to hide it and keep them.

### Reordering

```http
PATCH /vendor/menu/reorder
{
  "categories": [{ "id": "…", "sort_order": 0 }, { "id": "…", "sort_order": 1 }],
  "items": [{ "id": "…", "sort_order": 0 }]
}
```

Send the whole new order after a drag-and-drop. Every id is validated before
anything is written, so a payload containing one bad id changes nothing rather
than applying half of itself.

---

## 5. Order queue

```http
GET /vendor/orders?status=NEW&limit=20
```

Newest first. `status` accepts:

- **a tab name** — the three tabs of the Order screen, which is what you want
  99% of the time:

  | Tab | Send | Statuses behind it |
  | --- | --- | --- |
  | New(5) | `?status=NEW` | `PENDING` |
  | Preparing(2) | `?status=PREPARING` | `PREPARING` + `READY` |
  | Complete(21) | `?status=COMPLETE` | `PICKED_UP` + `DELIVERED` |

- **`ACTIVE`** — `PENDING`, `PREPARING` and `READY` in one filter: the whole
  kitchen screen, for the poll that drives the new-order alert
- one status — `?status=PICKED_UP`
- a list — `?status=PENDING,PREPARING` (tabs and statuses mix freely)

Two things worth knowing about the tabs:

- **`PREPARING` is the tab, not just the status.** A cooked order is still in
  the kitchen until a rider takes it, and the handoff code lives on that card,
  so `READY` rows stay in this tab. Ask for `?status=PREPARING` and you get
  both — no order can fall between two tabs the moment it is marked ready.
- **Cancelled and rejected orders are in no tab.** `COMPLETE` means the food
  reached a rider. Add them explicitly if your history screen wants them:
  `?status=COMPLETE,CANCELLED`.

Rows carry an `item_count` but **not the line items**. Fetch
`GET /vendor/orders/{id}` when the vendor opens an order — that returns every
line with its chosen variant, add-ons and notes, plus the delivery address and
the customer's contact number.

Every row also carries `seconds_to_auto_decline`, which is non-null only while
the order is `PENDING`. Drive your countdown from it rather than from a local
timer, so a backgrounded app resumes with the right number.

### Live push

`WS /ws/vendor/live?token=<access_token>` streams your restaurant's feed, so the
tablet learns about an order when it is placed rather than when it next polls.
That matters: the accept window is 60 seconds, and half of it can be gone before
a poll fires.

The restaurant is resolved from your token, never from a parameter — no vendor
can subscribe to a competitor's feed by editing a query string. Browsers cannot
set an `Authorization` header on a WebSocket handshake, so the token goes in the
query string and is validated **before** the socket is accepted.

Frames:

| `type` | When |
|---|---|
| `order.placed` | A customer placed an order with you. Carries the full order |
| `order.status` | An order moved — accept, reject, ready, handoff, delivered |
| `ping` | Keepalive every 25s. An idle socket through a proxy dies inside a minute |

Keep polling as a fallback. Publishing is best-effort by design: an order must
still be placed when Redis is unreachable, so a missed frame is possible and a
socket is an optimisation, not a source of truth.

---

## 6. The order lifecycle

```
PENDING ──accept──▶ PREPARING ──ready──▶ READY ──handoff──▶ PICKED_UP ──▶ DELIVERED
   │                    │
   └────reject──────────┴──▶ CANCELLED
```

Illegal jumps are rejected with `409` and the response lists what is actually
allowed from the current state. Trust that over any state machine you keep
client-side.

### Accept — you have **60 seconds**

```http
POST /vendor/orders/{id}/accept
```

An order left `PENDING` past its `auto_decline_at` is declined automatically.
Accepting clears the timer.

### Reject

```http
POST /vendor/orders/{id}/reject
{ "reason": "Out of chicken" }
```

Allowed while `PENDING` or `PREPARING` only — once a rider has the food it is no
longer the kitchen's to cancel.

**The customer is refunded, not rebooked.** The order is cancelled, a paid order
is marked `REFUNDED`, and that is the end of it. The backend does not silently
re-place the cart with another restaurant: a substitute has different prices, a
different menu and a different delivery time, so recreating "the same order"
would mean deciding on the customer's behalf what they are willing to pay and
wait for. If your UI promises "rebooking with a nearby vendor", that flow lives
in the **customer** app, built on discovery.

### Ready

```http
POST /vendor/orders/{id}/ready
```

`PREPARING → READY`. The response now carries **`handoff_code`** — the 4-digit
code the handoff screen displays. See below.

---

## 7. Handoff

Marking ready issues a **4-digit** code. Your handoff screen shows it ("Hand
this code to your rider"); the rider's app will show the same code, and when
they match, the vendor confirms:

```http
POST /vendor/orders/{id}/handoff
{ "rider_pin": "7420" }
```

Success moves the order to `PICKED_UP` and burns the code.

Where to read the code: `handoff_code` in the `ready` response, and again in
`GET /vendor/orders/{id}` **while the order is READY** — so an app restart
cannot strand a pickup. After pickup it is `null` everywhere.

**Reissuing a code.** Calling `POST /vendor/orders/{id}/ready` again on an order
that is already READY issues a fresh code and restores the full attempt budget.
That is the way out of the lockout below, and the only one: the order stays
READY, `ready_at` keeps its original value, and no status-history row is
written, because nothing changed status. Expect a new `handoff_code` in the
response and show that one.

**Who the rider is.** You do not choose. A rider is assigned automatically when
you accept the order — during the cooking window, so they have time to reach
you — and again at `ready` if nobody was on shift the first time. There is no
vendor endpoint to pick or change a rider; an operator does that from the admin
side when something goes wrong.

> Displaying the code to the vendor is a deliberate interim posture: with no
> rider app shipped yet, nothing else could receive it. When the rider app
> lands, proof-of-presence flips back to rider-side display by removing the
> field — the verification underneath does not change.

Failure modes to handle:

| Situation | Status | Code |
|---|---|---|
| Wrong PIN | `400` | `INVALID_RIDER_PIN` — `details` says how many tries remain |
| 5 incorrect attempts | `409` | `INVALID_RIDER_PIN` — locked; mark ready again to reissue |
| Order is not `READY` | `409` | `CONFLICT` |
| No rider assigned yet | `409` | `CONFLICT` |

The attempt cap is what actually protects a 4-digit code — 10,000 candidates
fall to brute force in seconds otherwise. Do not add a client-side retry loop.

---

## 8. Analytics

```http
GET /vendor/analytics?date_from=2026-08-01&date_to=2026-08-18
```

Defaults to the last 30 days. Returns `totals`, a `daily` series, `top_items`,
and a `status_breakdown`.

Two things to explain in your UI, because vendors ask:

- **Only `DELIVERED` orders count as earnings.** An in-flight or cancelled order
  is not revenue. Cancellations are still visible in `status_breakdown`, which
  counts every order placed in the window regardless of outcome.
- **`net_payout` is what you are owed**: `gross_sales` minus `commission`. The
  commission is the amount snapshotted on each order when it was placed, not
  today's rate — so renegotiating your rate never restates last month.

Days are grouped in UTC.

`GET /vendor/reviews` returns what customers wrote, newest first. Only the
restaurant rating and comment are exposed; the rider rating is about the
delivery and is not shown to you.

---

## 9. Images

The backend never handles image bytes. Ask for a URL, upload straight to
Cloudflare R2, then send us the resulting link.

```http
POST /uploads/presigned-url
{ "file_type": "image/jpeg" }
```

```json
{
  "success": true,
  "data": {
    "upload_url": "https://<account>.r2.cloudflarestorage.com/<bucket>/uploads/…/abc123.jpg?X-Amz-Signature=…",
    "public_url": "https://cdn.cheeringshop.online/uploads/…/abc123.jpg",
    "key": "uploads/…/abc123.jpg",
    "method": "PUT",
    "headers": { "Content-Type": "image/jpeg" },
    "expires_in": 900
  }
}
```

Then:

1. `PUT` the raw bytes to `upload_url` **with the exact `headers` returned**.
   The content type is part of the signature, so a mismatch is rejected by
   storage itself.
2. Send `public_url` back to us as `logo_url`, `cover_image_url` or an item's
   `image_url`.

**`upload_url` and `public_url` are different hosts, and neither substitutes for
the other.** `upload_url` is R2's S3 endpoint: it takes your PUT and then
expires. `public_url` is the CDN domain bound to the bucket, and is the only one
that serves reads — fetching the object from the upload host returns `401`. Send
us `public_url` and nothing else; do not try to reconstruct either URL yourself,
because the object key is server-generated.

`upload_url` is valid for 15 minutes. Allowed types are JPEG, PNG and WebP;
anything else is a `400`. A `503` means object storage is not configured on that
environment — treat it as "uploads unavailable here", not as a bug in your
request. Its `details` name the missing variables.

---

## 10. Endpoint summary

All require a `VENDOR` bearer token unless noted.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/vendor/profile` | vendor | Read my storefront |
| PATCH | `/vendor/profile` | vendor | Update my storefront |
| PATCH | `/vendor/store/status` | vendor | Open or close |
| GET | `/vendor/menu` | vendor | Full menu tree |
| GET | `/vendor/menu/categories` | vendor | Categories only |
| POST | `/vendor/menu/categories` | vendor | Create a category |
| PATCH | `/vendor/menu/categories/{id}` | vendor | Rename / reorder / deactivate |
| DELETE | `/vendor/menu/categories/{id}` | vendor | Delete an empty category |
| PATCH | `/vendor/menu/reorder` | vendor | Apply a drag-and-drop order |
| POST | `/vendor/menu/items` | vendor | Create an item |
| GET | `/vendor/menu/items/{id}` | vendor | Read one item |
| PATCH | `/vendor/menu/items/{id}` | vendor | Edit an item |
| DELETE | `/vendor/menu/items/{id}` | vendor | Remove an item (soft) |
| PATCH | `/vendor/menu/items/{id}/status` | vendor | Sold-out toggle |
| POST | `/vendor/menu/items/{id}/variants` | vendor | Add one variant |
| PATCH | `/vendor/menu/items/{id}/variants/{variant_id}` | vendor | Edit one variant |
| DELETE | `/vendor/menu/items/{id}/variants/{variant_id}` | vendor | Delete one variant |
| POST | `/vendor/menu/items/{id}/add-ons` | vendor | Add one add-on |
| PATCH | `/vendor/menu/items/{id}/add-ons/{add_on_id}` | vendor | Edit one add-on |
| DELETE | `/vendor/menu/items/{id}/add-ons/{add_on_id}` | vendor | Delete one add-on |
| GET | `/vendor/orders` | vendor | Order queue |
| GET | `/vendor/orders/{id}` | vendor | Order detail |
| POST | `/vendor/orders/{id}/accept` | vendor | Accept |
| POST | `/vendor/orders/{id}/reject` | vendor | Reject + refund |
| POST | `/vendor/orders/{id}/ready` | vendor | Mark ready, issue PIN |
| POST | `/vendor/orders/{id}/handoff` | vendor | Verify PIN, hand over |
| GET | `/vendor/analytics` | vendor | Earnings |
| GET | `/vendor/reviews` | vendor | Customer reviews |
| GET | `/vendor/reviews/summary` | vendor | Rating histogram |
| GET | `/vendor/dashboard` | vendor | Home + Overview in one call |
| GET | `/vendor/performance` | vendor | Acceptance / on-time rates |
| GET | `/vendor/reports/csv` | vendor | CSV download (text/csv, not JSON) |
| GET | `/vendor/earnings` | vendor | Balance + recent credits |
| GET | `/vendor/payouts` | vendor | Payout history |
| POST | `/vendor/payouts` | vendor | Withdraw money |
| GET | `/vendor/hours` | vendor | Business hours |
| PUT | `/vendor/hours` | vendor | Set business hours |
| GET | `/vendor/promotions` | vendor | My promotions with stats |
| POST | `/vendor/promotions` | vendor | Launch a promotion |
| GET | `/vendor/promotions/{id}` | vendor | Detail + 7-day chart |
| PATCH | `/vendor/promotions/{id}` | vendor | Pause / resume / end early |
| POST | `/uploads/presigned-url` | any | Image upload URL |
| GET | `/admin/payouts` | admin | Transfer work queue |
| POST | `/admin/payouts/{id}/complete` | admin | Confirm a transfer |
| POST | `/admin/payouts/{id}/fail` | admin | Bounce a transfer (auto-refunds) |
| GET | `/admin/riders` | admin | The dispatch pool, most idle first |
| POST | `/admin/riders` | admin | Enrol a rider |
| PATCH | `/admin/riders/{id}` | admin | Shift state and clearance |
| POST | `/admin/orders/{id}/assign-rider` | admin | Assign or reassign a rider |
| POST | `/admin/orders/{id}/deliver` | admin | Confirm a delivery the rider could not |

Vendor **registration** and login are in [AUTH-API.md](AUTH-API.md).

---

## 11. Dashboard & performance

### The landing tabs

```http
GET /vendor/dashboard
```

One call renders the Order tab's header and the whole Overview tab: the queue
chips (`queue.new`, `queue.preparing`, `queue.complete` — each counting exactly
what `GET /vendor/orders?status=<tab>` lists, so a chip cannot disagree with the
list under it — plus `queue.ready`, the handoff-waiting slice of `preparing`,
and `queue.completed_today`), today's delivered orders and earnings, the last-7-days chart (`last_7_days`,
always exactly 7 entries, zero-filled), `acceptance_rate`, the store toggle
state, and the five most recent orders. Call it on app resume instead of five
separate requests.

### Performance & ratings

```http
GET /vendor/performance?window_days=30
```

- `acceptance_rate` — accepted ÷ decided. Only orders the *vendor* decided
  count in the denominator: accept, reject, or timeout. A customer cancelling
  their own pending order does not dilute it.
- `on_time_rate` — orders marked READY within your own `avg_prep_time_mins`
  of acceptance. That is the only promise the system records, so it is the one
  measured.
- `rejections_this_week` — vendor rejections in the last 7 days.

**Rates are `null` until there is data — render a dash, not 0%.** A new vendor
has not failed at anything.

### Feedback

```http
GET /vendor/reviews/summary
```

The Feedback header: `rating_avg`, `rating_count` and `histogram` (keys "1"
through "5", zeroes included — the bars always sum to the count). The paginated
list behind it is `GET /vendor/reviews`.

### Report CSV

```http
GET /vendor/reports/csv?date_from=2026-08-01&date_to=2026-08-18
```

Returns **`text/csv`** with a `Content-Disposition: attachment` header — not
the JSON envelope. One row per DELIVERED order in the window (default last 30
days), same population as `/vendor/analytics`, so the spreadsheet's sums match
the tiles on the Report screen.

---

## 12. Earnings & payouts

### The balance

```http
GET /vendor/earnings
```

`available_balance` is **derived, never stored**:

```
lifetime delivered earnings (item_total − commission, per order)
− completed payouts
− processing payouts
```

A payout still PROCESSING is already deducted — money on its way out cannot be
withdrawn twice. `recent_transactions` lists the latest per-order credits for
the Earnings screen.

### Withdraw

```http
POST /vendor/payouts

{
  "amount": 1000,
  "method": "BKASH",              // BANK | BKASH | NAGAD | ROCKET
  "account_number": "01712447567",
  "account_name": "Karim Ahmed",
  "bank_name": null,              // required when method is BANK
  "branch_name": null
}
```

`201` returns the receipt fields the success screen shows — `reference`
("CHR64445654"), amount, method, destination, `status: "PROCESSING"`.

| Situation | Response |
|---|---|
| Amount below the minimum (100 taka) | `400` |
| Amount above `available_balance` | `400` |
| `BANK` without `bank_name` | `400` |

**No gateway is connected.** The request records the withdrawal; a person
executes the transfer and confirms it, at which point `GET /vendor/payouts`
shows `COMPLETED` — or `FAILED` with a `failure_reason`, which returns the
amount to the balance automatically. Say "on its way", not "sent".

Two simultaneous withdraw taps cannot both pass the balance check — creation
is serialised server-side.

---

## 13. Business hours

```http
GET /vendor/hours
PUT /vendor/hours
```

`PUT` replaces the whole week (the screen saves all seven days):

```json
{
  "mon": { "is_open": true,  "opens_at": "10:00", "closes_at": "22:00" },
  "fri": { "is_open": true,  "opens_at": "14:00", "closes_at": "23:00" },
  "sun": { "is_open": false }
}
```

Times are 24-hour `"HH:MM"`. An open day needs both times; `closes_at` earlier
than `opens_at` means trading past midnight and is accepted. `GET` returns
`is_configured: false` plus a default template until the first save.

**These hours are informational.** Customers will see them, but nothing opens
or closes the store from them — `PATCH /vendor/store/status` remains the only
real switch. Saving Sunday as closed does not close the store on Sunday.

---

## 14. Promotions

### Launch

```http
POST /vendor/promotions

{
  "discount_type": "PERCENTAGE",   // PERCENTAGE | FLAT | FREE_DELIVERY
  "discount_value": 20,            // percent for PERCENTAGE, taka for FLAT, omit for FREE_DELIVERY
  "min_order_amount": 400,
  "item_ids": null,                // null = whole menu; ids must be on YOUR menu
  "starts_at": null,               // defaults to now
  "ends_at": "2026-08-14T00:00:00Z",
  "budget_cap": 5000               // taka; redemption stops at the cap
}
```

The response carries a generated `code` (e.g. `KFC-8231` — customers can also
type it at checkout), a display `title` ("20% OFF"), and a `state`:
`SCHEDULED`, `ACTIVE`, `PAUSED` or `ENDED` — render the card's badge from that
one field.

### Read

`GET /vendor/promotions` lists every offer with `redemptions`, `budget_spent`
and `revenue_generated`. `GET /vendor/promotions/{id}` adds `last_7_days`, the
redemptions-per-day chart.

### Pause / end

```http
PATCH /vendor/promotions/{id}
{ "is_active": false }     // pause (reversible)
{ "end_now": true }        // end early (final)
```

Nothing else about a live promotion can change — repricing an offer customers
have already seen is a bait-and-switch. Ended promotions are immutable.

Promotions are redeemed at checkout, which is live, so a launched offer starts
accumulating real stats as soon as customers use it.

---

## Known limitations

Be aware of these when planning screens:

1. **A dropped socket is silent.** `WS /ws/vendor/live` pushes orders and
   status changes (§5), but publishing is best-effort — a Redis outage must not
   fail an order that is already placed. Keep a polling fallback on
   `GET /vendor/orders?status=ACTIVE`, and mind the 60-second accept window when
   choosing its interval.
2. **You still see the handoff code.** Riders now have their own API
   ([RIDER-API.md](RIDER-API.md)) and read the same code from their job screen,
   which is what makes typing it back proof of presence. Your copy of the field
   remains only because this app was built against it: removing `handoff_code`
   from the `ready` response and the order detail is the whole change whenever
   you are ready, and the verification underneath does not move. Until then,
   keep the code display separable from the input.
   `POST /vendor/orders/{id}/handoff` returns `409 "No rider is available to
   take this order"` only when no verified rider is on shift.
3. **No scheduled opening hours.** `status` is a manual toggle, and the
   business hours saved via `PUT /vendor/hours` (§13) are informational — a
   vendor who forgets to close stays open. Consider a client-side reminder.
4. **Refunds and payouts are recorded, not executed.** Rejecting a paid order
   sets `payment_status` to `REFUNDED`, and `POST /vendor/payouts` records a
   PROCESSING withdrawal — no payment gateway is connected, so in both cases a
   person moves the actual money and then confirms it.
5. **No push notification registration.** `POST /users/me/devices` is not built,
   so a backgrounded tablet learns nothing until it polls.
6. **Uploads need configuration.** `POST /uploads/presigned-url` returns `503`
   wherever the Cloudflare R2 variables are unset, which today includes local
   development. `GET /health/ready` reports storage status without you having
   to attempt an upload.
7. **One restaurant per vendor.** The API is shaped for multi-outlet support —
   hence `restaurant_id` on every response — but the schema currently enforces
   exactly one, and there is no endpoint to create a second.
8. **Promotion analytics are thin.** Redemptions are counted at checkout, but
   there is no per-customer breakdown or cohort view. Launching, pausing and
   reporting all work; `redemptions` and `budget_spent` stay zero until
   checkout ships, and the budget-cap cutoff is enforced there.

---

## Questions

Anything ambiguous, or a response that doesn't match this document: send the
`X-Request-ID` from the response and the exact request body.
