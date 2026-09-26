# Admin API

What the admin panel runs on, screen by screen, for every screen in
`admin_screen/`. The last section lists what a deployment needs configured and
the one screen element that has no data yet.

Base URL `…/api/v1`. Envelope `{"success": true, "data": {…}, "meta": {…}}`;
failures use `{"success": false, "error": {"code", "message", "details"}}`.
Every endpoint below needs an `ADMIN` access token. Any other role gets `403`.

**Conventions**

- **Money is whole taka, as a JSON number** (`1779.0`). It is never paisa, and
  there is no currency symbol.
- **Order IDs.** Show `order_number` as `ORD-{order_number}`. Use `id` (a UUID)
  in URLs.
- **Lists** take `limit` (default 20, max 100) and `offset`. `meta` carries
  `total`, `page` and `has_more`, which is everything *Page 1 of 10* needs.
- **Dates** in filters are calendar days (`2026-08-15`), inclusive, in UTC.
- **Export.** The Orders, Customers and Active Vendors lists accept
  `format=csv` with the same filters. The response is a file download of up to
  5000 rows.
- **Business type** is `RESTAURANT`, `GROCERY` or `PHARMACY`, which the UI shows
  as Food / Grocery / Medicine. It is `null` for a restaurant that was created
  without a partner application.

---

## Contents

1. [Signing in](#1-signing-in)
2. [Overview](#2-overview)
3. [Orders](#3-orders)
4. [Customers](#4-customers)
5. [Vendors](#5-vendors)
6. [Products](#6-products)
7. [Commission](#7-commission)
8. [Riders](#8-riders)
9. [Category](#9-category)
10. [Finance](#10-finance)
11. [Search bar](#11-search-bar)
12. [Support Ticket and Live Chat](#12-support-ticket-and-live-chat)
13. [Community](#13-community)
14. [Advertisement](#14-advertisement)
15. [Live Tracking](#15-live-tracking)
16. [Notification](#16-notification)
17. [Settings](#17-settings)
18. [Inviting administrators](#18-inviting-administrators)
19. [Endpoint summary](#19-endpoint-summary)
20. [Deployment and gaps](#20-deployment-and-gaps)

---

## 1. Signing in

| Screen | Call |
|---|---|
| Sign In | `POST /auth/login` `{"email","password"}`. Take `data.tokens.access_token`. If the account is not `ADMIN`, refuse it in the UI. |
| Forgot Password | `POST /auth/password/forgot` `{"email"}` emails a code. |
| OTP Authentication | Keep the code in the UI. There is no separate verify call. |
| New password | `POST /auth/password/reset` `{"email","code","new_password"}` |
| Header (name, avatar) | `GET /users/me` |
| Settings → Logout | `POST /auth/logout` `{"refresh_token"}` |
| Sign up for admin | Opened from an invitation link; see §18 |

Full details, including 2FA and token refresh, are in [AUTH-API.md](AUTH-API.md).
The first admin account is created on the server with
`scripts/create_admin.py`.

## 2. Overview

`GET /admin/dashboard` returns the whole screen except the chart:

- `revenue_today`, `orders_today`: each has `{value, previous, change_pct}`.
  They compare **today with yesterday**, both as whole UTC days. `change_pct` is
  `null` when yesterday was zero, so show no arrow in that case. Revenue counts
  delivered orders only.
- `active_riders` (riders on shift) and `online_vendors` (verified and OPEN).
- `pending_approvals`: `{total, vendors, riders}`. `vendors` matches the count
  in `GET /admin/restaurants/pending`; `riders` is the rider applications
  waiting for review.
- `live_orders`: `{new, preparing, on_delivery, cancelled_today, avg_delivery_minutes}`.
- `support_tickets`: `{open, urgent}` — open counts OPEN and PENDING tickets.
- `recent_orders`: the latest eight, in the same shape as an Orders row.

**Revenue chart:** `GET /admin/analytics/revenue?range=7d|30d|12m`. Every
bucket is present and zero-filled, and each point carries a ready-made axis
`label` (`Sat`, `14 Aug`, `Aug 2026`).

## 3. Orders

`GET /admin/orders` returns every order, newest first. The filters combine:

| Query | Meaning |
|---|---|
| `status` | One status, a comma list, or a tab: `NEW`, `PREPARING` (includes READY), `COMPLETE`, `ACTIVE` |
| `payment_method` | `COD`, `WALLET`, `BKASH`, `CARD` |
| `date_from`, `date_to` | Placed on or between these days |
| `q` | Order number (`ORD-48210`, `#48210` or `48210`), customer name or phone, vendor name |
| `customer_id`, `restaurant_id`, `rider_id` | One party's orders. Every profile's Order tab uses this. |

Statuses are `PENDING`, `PREPARING`, `READY`, `PICKED_UP`, `DELIVERED` and
`CANCELLED`. There is no `ACCEPTED`: when a vendor accepts an order it moves
straight to `PREPARING`.

**The order drawer:** `GET /admin/orders/{id}` returns `timeline` (each event
has an actor), `customer`, `vendor`, `rider`, `money` (including
`commission_amount` and `vendor_payout`), `payment`, `items`, and
`rider_location`. `rider_location` is only present while the rider is live on
the order, and includes `distance_to_dropoff_km`.

Use `actions` to decide which drawer buttons are enabled:

| Button | Enabled when | Call |
|---|---|---|
| Assign rider | `actions.can_assign_rider` | `POST /admin/orders/{id}/assign-rider` `{"rider_id"}`. Omit `rider_id` to let dispatch choose. |
| Cancel order | `actions.can_cancel` | `POST /admin/orders/{id}/cancel` `{"reason"}` |
| Refund order | `actions.can_refund` | `POST /admin/orders/{id}/refund` `{"reason"}` |
| Call Customer | always | Dial `customer.delivery_contact_phone` (the number on this order), falling back to `customer.phone` |

- **Cancel** works on PENDING, PREPARING and READY orders only. Once a rider
  has the food, the order can only be delivered (`409` otherwise). A paid order
  is refunded as part of cancelling. The customer and the vendor tablet are told
  immediately.
- **Refund** works on any order whose `payment.status` is `PAID`. It does not
  cancel the order. It records who refunded, when, and why
  (`payment.refunded_*`). No payment gateway is connected yet, so a refund
  records that the money is owed back; the transfer itself happens outside the
  platform.

## 4. Customers

- **List:** `GET /admin/customers?q=&status=ACTIVE|BLOCKED`. Each row has
  `order_count`, `total_spent` (delivered orders only) and `is_active`
  (`false` shows as Blocked).
- **Details:** `GET /admin/customers/{id}` returns the profile, the
  `default_address`, and `stats` with `total_orders`, `delivered_orders`,
  `cancelled_orders`, `total_spent` and `average_order`. The Recent orders
  table is `GET /admin/orders?customer_id={id}`.
- **Block or unblock:** `PATCH /admin/users/{id}/status` `{"is_active": false}`.
  This works for customers and riders. Blocking takes effect on the account's
  next request, and the account is signed out everywhere. A blocked rider is
  also taken off shift. Vendors get `409`: suspend them with
  `POST /admin/restaurants/{id}/verify` `{"is_verified": false}` instead, which
  also removes their store from the customer app.

## 5. Vendors

**Active Vendors:** `GET /admin/vendors`, highest revenue first. The query
takes these filters:

| Query | Meaning |
|---|---|
| `status` | `ACTIVE` (the default), `SUSPENDED` or `ALL` |
| `q` | Store name or phone |
| `business_type` | The Category dropdown |
| `min_rating` | The Rating dropdown |

Rows carry `order_count`, `revenue`, `rating_avg` and `product_count`.

**Vendor Details tabs:**

| Tab | Call |
|---|---|
| Header + Store Info | `GET /admin/vendors/{id}`: owner, NID, `documents` (kind → URL), `business_hours`, `avg_prep_time_mins`, `min_order_amount`, `delivery_fee_base`, `commission_rate` |
| Products | `GET /admin/products?restaurant_id={id}`. **Add Product** is `POST /admin/vendors/{id}/products` (§6). |
| Order | `GET /admin/orders?restaurant_id={id}` |
| Review | `GET /admin/vendors/{id}/reviews`: `summary` (average, count, 1–5 `histogram`) and one page of `reviews`, paginated by `meta` |
| Withdrawal (tiles) | `GET /admin/vendors/{id}/finance`: `total_earning`, `total_commission`, `total_payout`, `pending_amount`, `available_balance` |
| Withdrawal (table) | `GET /admin/payouts?restaurant_id={id}&status=` |

The **Contact Vendor** button dials the `phone` field from the vendor details
response.

To change a vendor's commission, call `PATCH /admin/restaurants/{id}/commission`
`{"commission_rate": 0.15}`.

**Application (the review queue):** `GET /admin/vendor-applications` takes:

| Query | Meaning |
|---|---|
| `status` | `PENDING` (the default), `APPROVED` or `REJECTED` |
| `q` | Store name, owner name, phone or application number |
| `business_type` | The All Type dropdown |

The detail and decision calls are `GET …/{id}`, `POST …/{id}/approve` and
`POST …/{id}/reject` `{"note"}`. The rejection note is emailed to the
applicant.

**Vendor Withdrawal:** `GET /admin/payouts` returns `PROCESSING` payouts by
default, oldest first. The query takes these filters:

| Query | Meaning |
|---|---|
| `status` | `PROCESSING` (the default), `COMPLETED` or `FAILED` |
| `restaurant_id` | One vendor's payouts |
| `q` | Payout reference or vendor name |
| `date_from`, `date_to` | Requested on or between these days |

Each row includes `restaurant_name`. The action buttons map to these calls:

| Button | Call |
|---|---|
| Mark Paid | `POST /admin/payouts/{id}/complete` |
| Transfer failed | `POST /admin/payouts/{id}/fail` `{"reason"}` returns the amount to the vendor's balance |
| Mark Unpaid | `POST /admin/payouts/{id}/reopen` `{"reason"}` |

**Mark Unpaid** takes a `COMPLETED` payout back to `PROCESSING`, for a
transfer marked paid by mistake or one that bounced afterwards. The row
records who reopened it, when and why (`reopened_at`, `reopen_reason`), and it
goes back into the queue to be paid again. The vendor's balance does not
change, because pending payouts are already deducted from it the same way
paid ones are. Only a `COMPLETED` payout can be reopened (`400` otherwise).

## 6. Products

**Product List:** `GET /admin/products` returns every product across all
vendors, featured first, then A to Z. The query takes these filters:

| Query | Meaning |
|---|---|
| `q` | Product or store name |
| `restaurant_id` | One vendor's products (the vendor profile's Products tab) |
| `category_id` | One browse category (the Edit category drawer's product list) |
| `business_type` | The Type badge |
| `status` | `ACTIVE`, `HIDDEN` (hidden by an admin) or `UNAVAILABLE` (sold out, the vendor's switch) |
| `featured` | `true` or `false` |

Each row carries `status`, `is_featured`, the `platform_category` and the
vendor's `section_name`, and `commission` (see §7).

There is no stock column. Stock is not tracked anywhere yet.

**Product drawer:** `GET /admin/products/{id}` adds `description`, `variants`,
`add_ons`, and the Pricing card: `base_price`, `commission.rate`,
`commission_amount` and `net_amount` (what the vendor keeps on the base price).

**Edit (Done Editing / Save Changes), Hide Product, Featured:**
`PATCH /admin/products/{id}`. It takes anything the vendor can edit (`name`,
`description`, `image_url`, `base_price`, `variants`, `add_ons`, …) plus these
admin-only fields:

| Field | Effect |
|---|---|
| `commission_rate` | This product's own rate, e.g. `0.15`. `null` clears it. |
| `is_hidden` | `true` removes the product from the customer app: menu, search, categories and cart. The vendor still sees it, flagged `is_hidden`, and cannot change it. |
| `is_featured` | The Featured button. Featured products come first in the admin list and carry `is_featured` in the customer menu. |
| `platform_category_id` | Move the product under another browse category. |

Omitted fields are left alone. Edits follow the same rules as the vendor app:
a bad price or an unknown field is a `400`.

**Delete:** `DELETE /admin/products/{id}` removes the product from every menu.
Past orders keep it. To take a product down without deleting it, hide it
instead.

**Add Product** (the vendor profile's Products tab):
`POST /admin/vendors/{restaurant_id}/products`. The body is the same as the
vendor's own `POST /vendor/menu/items`, with two differences:

- Place the product with `platform_category_id` (a browse category) instead of
  `category_id` (a menu section). Send exactly one of the two.
- It may also carry `commission_rate` and `is_featured`.

**How categories hold products.** A browse category holds products through
the vendors' menu sections. Moving or adding a product to a category puts it
in that restaurant's section for the category. If the restaurant has no such
section, one is created, named after the category, and the vendor will see it
in their menu. A product cannot be taken out of a category without putting it
in another, so the Edit category drawer's delete icon should move the product
rather than remove it.

## 7. Commission

Commission can be set at three levels, and all three stay available:

| Level | Where it is set |
|---|---|
| Product | `PATCH /admin/products/{id}` `{"commission_rate"}` |
| Category | `POST/PATCH /admin/categories/{id}` `{"commission_rate"}` |
| Restaurant | `PATCH /admin/restaurants/{id}/commission` `{"commission_rate"}` |

Rates are fractions: `0.15` means 15%. A `null` product or category rate means
"not set at this level".

Each product is charged at the **most specific rate that is set**: its own
rate, else its category's, else the restaurant's. An order with products at
different rates is charged per line. Every product response shows the rate it
is charged at, where that rate comes from, and every level's value:

```json
"commission": {
  "rate": 0.10,
  "source": "CATEGORY",
  "product_rate": null,
  "category_rate": 0.10,
  "restaurant_rate": 0.15
}
```

An order records its commission when it is placed. Changing a rate at any
level affects new orders only.

## 8. Riders

**What a rider earns.** Each order a rider delivers pays them its
`delivery_fee` and `tip` in full. Admins can add incentives on top. A rider's
balance works like a vendor's: everything earned, minus withdrawals that are
paid or on their way. A failed withdrawal goes back to the balance.

**Active Rider:** `GET /admin/riders`, riders on shift first, then the least
busy. The query takes these filters:

| Query | Meaning |
|---|---|
| `q` | Name, phone or email |
| `vehicle_type` | The Category dropdown (`CYCLE`, `BIKE`, `MOTORCYCLE`, …) |
| `min_rating` | The Rating dropdown |
| `status` | `ACTIVE`, `SUSPENDED` (not cleared to ride) or `BLOCKED` |
| `online_only` | Only riders on shift |

Rows carry `live_status` (`ONLINE`/`OFFLINE`), `phone`, `vehicle_type`,
`total_deliveries`, `rating_avg` and `avatar_url`.

**Rider Details tabs:**

| Tab | Call |
|---|---|
| Header + Personal Info | `GET /admin/riders/{id}`: identity, `date_of_birth`, `national_id`, `documents` (kind → URL), `delivered_orders`, `cancelled_orders`, and `earnings` (the today / week / month / total tiles) |
| Earning | `GET /admin/riders/{id}/earnings`: `summary` (totals by delivery fees, tips and incentives) and one page of `days`, paginated by `meta` |
| Order | `GET /admin/orders?rider_id={id}` |
| Withdrawal | `GET /admin/rider-payouts?rider_id={id}&status=` |

| Action | Call |
|---|---|
| Edit Personal Info | `PATCH /admin/riders/{id}` with any of `full_name`, `vehicle_type`, `license_number`, `date_of_birth`, `national_id`, `documents` |
| Suspend Rider | `PATCH /admin/riders/{id}` `{"is_verified": false}` stops dispatch using them; `PATCH /admin/users/{id}/status` `{"is_active": false}` blocks the account entirely |
| Grant an incentive | `POST /admin/riders/{id}/incentives` `{"amount", "reason"}` — added to the balance at once |

**Rider Withdrawal:** `GET /admin/rider-payouts` takes the same filters as
Vendor Withdrawal (`status` defaulting to `PROCESSING`, plus `rider_id`, `q`,
`date_from`, `date_to`), and rows carry `rider_name` and `rider_avatar_url`.

| Button | Call |
|---|---|
| Mark Paid | `POST /admin/rider-payouts/{id}/complete` |
| Transfer failed | `POST /admin/rider-payouts/{id}/fail` `{"reason"}` |
| Mark Unpaid | `POST /admin/rider-payouts/{id}/reopen` `{"reason"}` |

These behave exactly like the vendor payout buttons (§5).

**Rider Application:** riders apply from the rider app
(`POST /rider-applications`, see [RIDER-API.md](RIDER-API.md)). No account
exists until an admin approves.

| Screen | Call |
|---|---|
| List | `GET /admin/rider-applications?status=PENDING&q=&vehicle_type=` — oldest first |
| Application Details | `GET /admin/rider-applications/{id}` |
| Approve | `POST /admin/rider-applications/{id}/approve` `{"password"?, "note"?}` |
| Reject | `POST /admin/rider-applications/{id}/reject` `{"note"}` |

Approving creates the rider account, cleared to ride but off shift, with the
application's documents and photo on the profile. Include a `password` to let
the rider sign in straight away; otherwise set one later with
`PATCH /admin/riders/{id}` `{"password"}`. The applicant is emailed either
way. Approval is a `409` if the email or phone already belongs to another
account. A rejection note is emailed as the reason.

## 9. Category

`GET/POST /admin/categories`, `PATCH/DELETE /admin/categories/{id}`,
`POST /admin/categories/{id}/merge`. These are documented in
[CATEGORIES.md](CATEGORIES.md). Upload images first with
`POST /uploads/presigned-url` and send the returned `public_url`.

The Category screen's additions:

| Screen element | How |
|---|---|
| Restaurant / Store tabs | `GET /admin/categories?kind=RESTAURANT` or `kind=STORE`. Set a category's tab with `kind` on create or `PATCH`. |
| Search | `q` matches the name and aliases |
| A to Z | `sort=name` (`-name` is Z to A) |
| Total Product | `product_count` on each row |
| Commission | `commission_rate` on create or `PATCH`; `null` clears it (§7) |
| Product List in the drawers | `GET /admin/products?category_id={id}`. Add or move a product with `PATCH /admin/products/{id}` `{"platform_category_id"}`. |

## 10. Finance

`GET /admin/finance/summary?days=30` returns four stat cards. Each is
`{value, previous, change_pct}` and compares the last `days` days with the
same number of days before that:

| Card | Meaning |
|---|---|
| `gmv` | Sum of what customers paid |
| `commission_revenue` | The platform's commission |
| `delivery_revenue` | Delivery fees collected, which are paid on to the riders |
| `net_revenue` | Commission + platform fees: what the platform keeps. Delivery fees and tips go to riders (§8), so they are not in it. |

`revenue_by_service` is the donut chart: GMV per business type, with
`share_pct`.

**Transaction details:** `GET /admin/finance/transactions?date_from=&date_to=&q=`
lists delivered orders as payments, newest first. Each row has
`payment_reference` (the gateway's ID; `null` for COD), the vendor, the
customer and the `amount`.

The revenue chart is the same `GET /admin/analytics/revenue` as on Overview.
All money here counts **delivered** orders only.

## 11. Search bar

`GET /admin/search?q=` needs at least 2 characters. It returns up to five hits
each for `orders`, `customers`, `vendors` and `riders`, each hit as
`{id, title, subtitle}`. Orders match by number only.

## 12. Support Ticket and Live Chat

Customers, vendors and riders open tickets from their apps. A ticket's
`status` says whose turn it is:

| Status | Meaning |
|---|---|
| `OPEN` | Waiting on support: a new ticket, or the user just replied |
| `PENDING` | Support replied; waiting on the user |
| `RESOLVED` | Support considers it done. The user replying reopens it. |
| `CLOSED` | Final. Nobody can reply. |

**Support Ticket / the Live Chat list:** `GET /admin/support/tickets`, most
recent activity first. It takes `status` (any of the four, or `ACTIVE` for
open + pending), `priority`, `type`, `unread=true` and `q` (ticket number such
as `TCK-8800`, subject, user name or phone). `meta.counts` has the number per
status plus `unread` and `urgent`, for the chips and "12 pending".

Rows carry `code` (`TCK-8800`), `subject`, `type`, `priority`, `status`,
`user` (name, role, phone, photo), `order_number`, `unread` (the red dot) and
`last_message_preview`.

**Live Chat — one ticket:** `GET /admin/support/tickets/{id}` returns the
ticket plus `messages`, oldest first. `kind: "MESSAGE"` rows are the
conversation; `kind: "EVENT"` rows are the History panel ("Ticket created",
"Assigned to …", "Marked closed"). Opening a ticket clears its red dot.

| Action | Call |
|---|---|
| Send a reply | `POST /admin/support/tickets/{id}/messages` `{"body", "attachments": [{"url", "name"}]}` |
| Close | `PATCH /admin/support/tickets/{id}` `{"status": "CLOSED"}` |
| Priority / assign | `PATCH /admin/support/tickets/{id}` `{"priority": "HIGH"}` or `{"assigned_to": "<admin id>"}` (`null` unassigns) |

Replying moves an `OPEN` ticket to `PENDING`, and the first reply on an
unassigned ticket assigns it to you. Upload attachments first with
`POST /uploads/presigned-url`. There is no push channel for the console yet:
poll the open ticket every few seconds.

## 13. Community

Customers post short updates (text, up to four images, an optional restaurant
tag) and can report posts. See [APP-SHARED-API.md](APP-SHARED-API.md).

**Moderation list:** `GET /admin/community/posts`, most reported first. The
query takes `status` (`LIVE` by default, `REPORTED`, `REMOVED` or `ALL`),
`sort` (`reports` or `recent`), `q` (post text or author name) and
`author_id`. Rows carry `author`, `body`, `report_count`, `author_is_active`
and, once removed, `removed_at` and `removal_reason`.

| Button | Call |
|---|---|
| Delete | `POST /admin/community/posts/{id}/remove` `{"reason"}`. The post leaves every feed; it stays on record. |
| Ban user | `PATCH /admin/users/{author.id}/status` `{"is_active": false}` |

## 14. Advertisement

The campaigns are vendor promotions: the offers behind the home feed's
"promoted" row.

`GET /admin/advertisements` returns them newest first, with `status`
(`SCHEDULED`, `ACTIVE`, `PAUSED` or `ENDED`), `q` (vendor name or code) and
`restaurant_id` filters. Each row has `restaurant_name`, `campaign` (the offer,
e.g. `20% OFF`), `budget`, `spent`, `impressions`, `clicks`, `redemptions`,
`revenue` and `status`. `meta.active` is the header's "7 active campaigns".

`PATCH /admin/advertisements/{id}` `{"status": "PAUSED" | "ACTIVE" | "ENDED"}`
pauses, resumes or ends a campaign. `ENDED` is final. The vendor sees the
change in their app.

Impressions and clicks come from the customer app reporting the promoted
cards it shows and the ones tapped (`POST /promotions/events`). They count only
while a campaign is live.

## 15. Live Tracking

`GET /admin/riders/live` returns every rider on shift, with:

| Field | Meaning |
|---|---|
| `status` | `AVAILABLE` (no orders), `HEADING_TO_PICKUP` (assigned, food not collected) or `DELIVERING` |
| `latitude`, `longitude` | The live position, only when `has_live_location` is true |
| `orders` | What the rider holds: order number, customer, restaurant and `distance_to_dropoff_km` |

Filter with `?status=` for the chips. A rider who has not reported a position
recently shows with `has_live_location: false` and no coordinates, rather than
at an old spot. Poll every 10–15 seconds while the map is open. **Call rider**
dials `phone`.

## 16. Notification

**List:** `GET /admin/notifications?status=&audience=`, newest first. Rows carry
`title`, `type`, `audience`, `status` (`SCHEDULED`, `SENT`, `FAILED`,
`CANCELLED`), `scheduled_for`, `sent_at`, `recipient_count` (in-app inboxes
reached) and `push_sent_count` (devices reached).

**Create New notification:** `POST /admin/notifications`:

```json
{
  "title": "50% off all orders",
  "message": "Order your favourite food and get 50% off delivery.",
  "type": "PROMOTION",
  "audience": "CUSTOMER",
  "scheduled_for": "2026-10-01T18:00:00+06:00"
}
```

`type` is `PROMOTION`, `ALERT` or `UPDATE`; `audience` is `CUSTOMER`,
`VENDOR`, `RIDER` or `ALL`. Leave out `scheduled_for` for **Send Now**: the
notification lands in every recipient's in-app inbox and is pushed to their
phones before the call returns. A scheduled notification is sent within a
minute of its time, and can be withdrawn with
`POST /admin/notifications/{id}/cancel` until then.

`push_enabled: false` on a campaign means push is not configured on the
server (§20). The notification still reaches every inbox.

## 17. Settings

`GET /admin/settings` returns the effective values; `PATCH /admin/settings`
changes them. Omitted fields are left alone, and `null` puts a field back to
the server default. Fields still on the default are listed in
`using_server_defaults`.

| Card | Fields |
|---|---|
| General | `app_name`, `support_email`, `support_phone` |
| Delivery settings | `delivery_base_fee` (covers the first `delivery_free_km`), `delivery_per_km_fee`, `delivery_min_fee` — whole taka |
| Commission settings | `restaurant_commission_rate` (Food), `grocery_commission_rate` (Shop), `pharmacy_commission_rate` (Medicine) — fractions, `0.18` = 18% |
| Dynamic pricing | `rain_surcharge`, `heatwave_fee`, `high_demand_fee`, each `{"amount", "active"}` |

- **Delivery fees and active surcharges** apply to the next checkout. The fee is
  base + per-km, raised to the minimum if below it, plus every **active**
  surcharge. The screen's amounts do nothing until `active` is true, so add a
  switch next to each.
- **The commission rates** are what a *new* vendor of that type starts on.
  Existing vendors keep their rate; change one with
  `PATCH /admin/restaurants/{id}/commission` (§7).

**Logout** is `POST /auth/logout`.

## 18. Inviting administrators

An admin invites someone by email; the invitee opens the emailed link, which
shows the **Sign up for admin** screen.

| Step | Call |
|---|---|
| Invite | `POST /admin/invitations` `{"email", "full_name"?}` — `409` if the address already has an account |
| List | `GET /admin/invitations` — each `PENDING`, `ACCEPTED`, `EXPIRED` or `REVOKED` |
| Revoke | `POST /admin/invitations/{id}/revoke` |
| Sign-up screen loads | `GET /auth/admin-invitations/{token}` — the email to show (read-only) |
| Sign up | `POST /auth/admin-invitations/accept` `{"token", "full_name", "password"}` — returns `{tokens, user}` like `/auth/login` |

The link is `ADMIN_INVITE_URL` with the token filled in (§20), so the screen
reads the token from its URL. A link works once and expires after
`ADMIN_INVITE_TTL_HOURS` (72 by default). Inviting the same address again
cancels the earlier link. An unknown, used, revoked or expired token is `404`
either way.

---

## 19. Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/dashboard` | admin | Overview cards, live orders, recent orders |
| GET | `/admin/analytics/revenue` | admin | Revenue chart — 7d, 30d or 12m |
| GET | `/admin/search` | admin | Top search bar |
| GET | `/admin/orders` | admin | Every order, filterable; `format=csv` exports |
| GET | `/admin/orders/{id}` | admin | The order drawer |
| POST | `/admin/orders/{id}/cancel` | admin | Cancel (refunds a paid order) |
| POST | `/admin/orders/{id}/refund` | admin | Record a refund on a paid order |
| POST | `/admin/orders/{id}/assign-rider` | admin | Assign or reassign a rider |
| POST | `/admin/orders/{id}/deliver` | admin | Confirm a delivery the rider could not |
| GET | `/admin/customers` | admin | Customer list; `format=csv` exports |
| GET | `/admin/customers/{id}` | admin | Customer details and statistics |
| PATCH | `/admin/users/{id}/status` | admin | Block or unblock a customer or rider |
| GET | `/admin/vendors` | admin | Active vendors; `format=csv` exports |
| GET | `/admin/vendors/{id}` | admin | Vendor details — Store Info |
| GET | `/admin/vendors/{id}/reviews` | admin | Vendor reviews and rating histogram |
| GET | `/admin/vendors/{id}/finance` | admin | Vendor money tiles |
| GET | `/admin/restaurants/pending` | admin | Unverified restaurants |
| POST | `/admin/restaurants/{id}/verify` | admin | Approve or suspend a restaurant |
| PATCH | `/admin/restaurants/{id}/commission` | admin | Set a restaurant's commission |
| GET | `/admin/vendor-applications` | admin | Application queue |
| GET | `/admin/vendor-applications/{id}` | admin | Application details |
| POST | `/admin/vendor-applications/{id}/approve` | admin | Approve an application |
| POST | `/admin/vendor-applications/{id}/reject` | admin | Reject with a note |
| GET | `/admin/payouts` | admin | Vendor withdrawals |
| POST | `/admin/payouts/{id}/complete` | admin | Mark a withdrawal paid |
| POST | `/admin/payouts/{id}/fail` | admin | Bounce a withdrawal back to the balance |
| POST | `/admin/payouts/{id}/reopen` | admin | Mark Unpaid — back to the queue |
| GET | `/admin/products` | admin | Every product, filterable |
| GET | `/admin/products/{id}` | admin | The product drawer |
| PATCH | `/admin/products/{id}` | admin | Edit, hide, feature, set commission, recategorise |
| DELETE | `/admin/products/{id}` | admin | Delete a product |
| POST | `/admin/vendors/{id}/products` | admin | Add a product to a vendor's menu |
| GET | `/admin/riders` | admin | Rider roster |
| POST | `/admin/riders` | admin | Enrol a rider |
| PATCH | `/admin/riders/{id}` | admin | Shift, clearance, password, personal info |
| GET | `/admin/riders/live` | admin | Live Tracking — riders on shift with positions |
| GET | `/admin/riders/{id}` | admin | Rider details |
| GET | `/admin/riders/{id}/earnings` | admin | Rider earnings by day |
| POST | `/admin/riders/{id}/incentives` | admin | Grant an incentive |
| GET | `/admin/rider-payouts` | admin | Rider withdrawals |
| POST | `/admin/rider-payouts/{id}/complete` | admin | Mark a rider withdrawal paid |
| POST | `/admin/rider-payouts/{id}/fail` | admin | Bounce a rider withdrawal |
| POST | `/admin/rider-payouts/{id}/reopen` | admin | Mark Unpaid |
| GET | `/admin/rider-applications` | admin | Rider application queue |
| GET | `/admin/rider-applications/{id}` | admin | Rider application details |
| POST | `/admin/rider-applications/{id}/approve` | admin | Approve — creates the rider |
| POST | `/admin/rider-applications/{id}/reject` | admin | Reject with a note |
| GET | `/admin/categories` | admin | Browse categories |
| POST | `/admin/categories` | admin | Create a category |
| PATCH | `/admin/categories/{id}` | admin | Edit, approve, hide, pin |
| DELETE | `/admin/categories/{id}` | admin | Delete an unused category |
| POST | `/admin/categories/{id}/merge` | admin | Merge into another category |
| GET | `/admin/finance/summary` | admin | Finance cards and service split |
| GET | `/admin/finance/transactions` | admin | Transaction details |
| GET | `/admin/support/tickets` | admin | Support queue with counts |
| GET | `/admin/support/tickets/{id}` | admin | A ticket, its thread and history |
| POST | `/admin/support/tickets/{id}/messages` | admin | Reply as support |
| PATCH | `/admin/support/tickets/{id}` | admin | Close, prioritise, assign |
| GET | `/admin/community/posts` | admin | Community moderation queue |
| POST | `/admin/community/posts/{id}/remove` | admin | Remove a post |
| GET | `/admin/advertisements` | admin | Vendor ad campaigns |
| PATCH | `/admin/advertisements/{id}` | admin | Pause, resume or end a campaign |
| GET | `/admin/notifications` | admin | Notification campaigns |
| POST | `/admin/notifications` | admin | Send now or schedule |
| POST | `/admin/notifications/{id}/cancel` | admin | Cancel a scheduled notification |
| GET | `/admin/settings` | admin | Platform settings |
| PATCH | `/admin/settings` | admin | Change platform settings |
| GET | `/admin/invitations` | admin | Administrator invitations |
| POST | `/admin/invitations` | admin | Invite an administrator |
| POST | `/admin/invitations/{id}/revoke` | admin | Revoke an invitation |
| GET | `/auth/admin-invitations/{token}` | public | Read an invitation (Sign up for admin) |
| POST | `/auth/admin-invitations/accept` | public | Accept and sign in |

---

## 20. Deployment and gaps

**Configure for production:**

| Setting | Why |
|---|---|
| The arq worker running (`make worker`) | Sends scheduled notifications (every minute). **Send Now** works without it. |
| `FCM_SERVICE_ACCOUNT_JSON` | The Firebase service-account key JSON, inline. Without it notifications reach in-app inboxes but no phone is pushed. The apps must register their device with `POST /users/me/devices`. |
| `ADMIN_INVITE_URL` | The invitation link, e.g. `https://admin.cheeringshop.online/accept-invite?token={token}`. Point it at the console's Sign up for admin screen. |
| `RESEND_API_KEY` | Already required; invitations and rider application decisions are emailed. |

**Not built:** the vendor Products tab's **Stock** column. Nothing tracks
stock.
