# Screen → API map

One row per mockup in `ui/`. Base URL and conventions are in
[VENDOR-API.md](VENDOR-API.md); the registration flow's request/response
examples are in [AUTH-API.md](AUTH-API.md) §11.

A screen with **client-side** means no network call: it renders static content
or data already fetched by an earlier screen.

## Vendor application form (`ui/Vendor application form/`)

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Onboarding.png | "Become a partner" landing | client-side | ⚪ client |
| Onboarding-1.png | Splash | client-side | ⚪ client |
| Onboarding-2.png | "Your partner account is ready" | client-side (arrival from the approval email) | ⚪ client |
| Business Information.png | Form step 1 | collected locally; sent at Review | 🟢 live |
| Location.png | Form step 2 (map pin) | collected locally; sent at Review | 🟢 live |
| Owner Information.png | Form step 3, "we'll send an OTP" | `POST /auth/otp/send` `{email, role: "VENDOR"}` | 🟢 live |
| Document.png | Upload shop image / NID / menu / licence | `POST /vendor/applications/uploads` per file, then PUT bytes to `upload_url` | 🟢 live |
| Review.png | Review & Submit | `POST /vendor/applications` (whole form + `otp_code`) | 🟢 live |
| Document-1.png | "Application submitted! #PTN-88291" | rendered from the submit response; later `GET /vendor/applications/{no}?email=` to poll status | 🟢 live |
| Login.png | Phone/email + password | `POST /auth/login` | 🟢 live |
| Login-1.png | Enter OTP | `POST /auth/password/forgot` (sends code) | 🟢 live |
| Login-2.png | Set Password | `POST /auth/password/reset` `{email, code, new_password}` | 🟢 live |

Admin console for this flow: `GET /admin/vendor-applications`,
`GET /admin/vendor-applications/{id}`, `POST …/{id}/approve`, `POST …/{id}/reject`.

## Coverage at a glance

84 rows across the three apps. Status is recorded per row rather than inferred
from the text: "no backend" and "one of the three things on this screen has no
backend" read almost identically to a rule, and the difference is exactly what a
reader needs. Check it when you change a row.

| Status | Rows | Means |
|---|---|---|
| 🟢 live | 70 | A real endpoint serves it |
| ⚪ client | 9 | No network call — static, or data an earlier screen already fetched |
| 🟠 partial | 3 | The screen renders, but part of what it promises is stubbed |
| 🔴 none | 2 | Nothing serves it |

**The amber and red rows are the point of this document.** Reels and the vendor
"Chat with us" screen have no backend at all. Track order renders, but the rider
dot is a `501` because no rider client reports a position, and Call Screen
returns `available: false` rather than a real phone number. Finding that out
here is cheaper than finding it out three days into the sprint.

An interactive version of this table — filterable, with a gaps-only view — is
published as an Artifact; this file is its source.

## Customer app (`ui/food-ui/`)

Full request/response detail is in [CUSTOMER-API.md](CUSTOMER-API.md).

### Browse

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Food.png | Home dashboard | `GET /home/feed?lat=&lng=` (one call: cuisines, offers, nearby, top rated) | 🟢 live |
| Food-1.png, Food-2.png | Feed scrolled | same response, rendered further | 🟢 live |
| Scroll.png | Restaurant carousel | `GET /restaurants?lat=&lng=` | 🟢 live |
| Category listing (Pizza).png | One cuisine | `GET /restaurants?cuisine=Pizza` | 🟢 live |
| Filter and Short.png | Filter + sort sheet | `GET /restaurants` with `sort`, `min_rating`, `max_delivery_fee`, `is_open` | 🟢 live |
| Search.png | Empty search | client-side (recent searches are local) | ⚪ client |
| Search results.png | Results | `GET /search?q=` — returns restaurants **and** dishes | 🟢 live |
| Restuarent Details.png | Storefront header | `GET /restaurants/{id}` (`promotions` drives the offer ribbon) | 🟢 live |
| Restuarent Details-1.png | Menu list | `GET /restaurants/{id}/menu` | 🟢 live |
| Restuarent Details-2.png | Menu, scrolled to a category | same response; category jump is client-side | 🟢 live |
| My favorite.png | Empty state | `GET /users/me/favorites`, zero rows | 🟢 live |
| My favorite-1.png | Saved list | `GET /users/me/favorites`; heart → `POST /users/me/favorites/{id}` | 🟢 live |
| Schedule Order.png | Delivery-time sheet | `GET /restaurants/{id}/schedule`; Confirm carries the slot into `scheduled_for` | 🟢 live |
| Share Details.png | Share sheet | client-side (OS share; no backend) | ⚪ client |
| Reels.png | Video feed | **no backend** — not in the spec, nothing serves it | 🔴 none |

### Cart and checkout

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Empty Cart.png | Nothing added | `GET /cart` returns an empty cart, not a 404 | 🟢 live |
| Cart.png | Lines + quantities | `GET /cart`; +/−/remove → `POST /cart/items` (`quantity: 0` removes) | 🟢 live |
| Order Modify.png | Edit a line's options | `POST /cart/items` with the new `variant_id` / `add_on_ids` | 🟢 live |
| Checkout.png | Address, payment, bill | `GET /checkout/summary?address_id=&promo_code=&tip=` | 🟢 live |
| Checkout-1.png | Promo applied | same call; a bad code returns the bill plus `promo_error` | 🟢 live |
| Address.png | Address picker + add | `GET/POST /users/me/addresses`; star → `PATCH …/{id}/default` | 🟢 live |
| Order Complete.png | "Order placed" | rendered from `POST /orders` (send an `Idempotency-Key`) | 🟢 live |

### After ordering

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Order.png | Order list | `GET /orders?status_filter=ACTIVE` | 🟢 live |
| Order-1.png | Empty history | same call, zero rows | 🟢 live |
| Order Details.png | Receipt + timeline | `GET /orders/{id}` | 🟢 live |
| Preparing food.png | Status while cooking | `GET /orders/{id}/tracking` (poll — no push yet) | 🟢 live |
| Ride Assign.png | "Arriving in 12 mins" + steps | `GET /orders/{id}/tracking` (`timeline` draws the dots, `eta_minutes` the header) | 🟢 live |
| Track order.png | Map | `GET /orders/{id}/tracking` for the endpoints and ETA. **The rider dot is not implemented** — `rider_location` is null and `WS /ws/orders/{id}/live-tracking` is a 501, because no rider client reports a position | 🟠 partial |
| Message.png | Chat with the rider | `GET/POST /orders/{id}/messages` | 🟢 live |
| Call Screen.png | Calling | `POST /orders/{id}/call` — returns `available: false`; no telephony provider is configured | 🟠 partial |
| Review.png | Rate the order | `POST /orders/{id}/reviews` (DELIVERED only, one per order) | 🟢 live |
| Profile.png | Account | `GET /users/me`; edit → `PUT /users/me/profile` | 🟢 live |


## Vendor app (`ui/full vendor/`)

### Order tab

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Home.png | Queue, New tab + chips + store toggle | `GET /vendor/dashboard` (chips, toggle state) + `GET /vendor/orders?status=PENDING`; toggle → `PATCH /vendor/store/status` | 🟢 live |
| Home-1.png | Preparing tab, "Mark as Ready" | `GET /vendor/orders?status=PREPARING`; button → `POST /vendor/orders/{id}/ready` | 🟢 live |
| Home-7.png | Empty queue state | same queue calls, zero rows | 🟢 live |
| Home-8.png | Order Details (items, 0:42 countdown, call) | `GET /vendor/orders/{id}` (`seconds_to_auto_decline` drives the countdown); call → `POST /orders/{id}/call` | 🟢 live |
| Home.png Accept / Reject buttons | Decide an order | `POST /vendor/orders/{id}/accept` / `…/reject` | 🟢 live |
| Home-4.png | Reject reasons list | `POST /vendor/orders/{id}/reject` `{reason}` (chips are client copy; note: the backend refunds + notifies, it does **not** rebook — soften that sentence) | 🟢 live |
| Home-2.png | "Hand this code to your rider" | `handoff_code` from the ready response or `GET /vendor/orders/{id}` while READY; Confirm → `POST /vendor/orders/{id}/handoff` `{rider_pin}` | 🟢 live |
| Home-3.png | Order completed (+৳680 today) | handoff response + `GET /vendor/dashboard` (`today_orders`, `today_earnings`) | 🟢 live |
| Home-5.png | Timeout / auto-declined | order arrives as CANCELLED in the queue; screen itself client-side | 🟢 live |
| Home-6.png | New-order push banner | no push yet — poll `GET /vendor/orders?status=ACTIVE` (see VENDOR-API.md Known limitations 2 & 6) | 🟢 live |
| Order.png | Overview tab | `GET /vendor/dashboard` (earnings, orders, rating, acceptance, 7-day chart, recent orders) | 🟢 live |

### Menu tab

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Menu.png | Menu list, availability toggles | `GET /vendor/menu`; toggle → `PATCH /vendor/menu/items/{id}/status` (search/chips filter client-side) | 🟢 live |
| Menu-13.png | Add new item ("You receive ৳425") | `POST /vendor/menu/items`; fee math from `commission_rate` in `GET /vendor/profile`; photo → `POST /uploads/presigned-url` | 🟢 live |
| Menu-14.png | Product Variants | `variants` array on item create/update | 🟢 live |
| Menu-15.png | Add Ones (add-ons) | `add_ons` array on item create/update | 🟢 live |
| Menu-18.png | "Item added" success | rendered from the create response | 🟢 live |
| Menu-16.png | Category list (drag to reorder) | `GET /vendor/menu/categories`; drag → `PATCH /vendor/menu/reorder`; edit → `PATCH /vendor/menu/categories/{id}` | 🟢 live |
| Menu-17.png | Add category sheet | `POST /vendor/menu/categories` | 🟢 live |
| Edit menu.png | Store Profile edit | `PATCH /vendor/profile`; photo → `POST /uploads/presigned-url` | 🟢 live |

### Profile tab

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Menu-1.png | Profile menu | client-side navigation | ⚪ client |
| Menu-7.png | Store Profile view | `GET /vendor/profile`; Change Password → `POST /users/me/password` | 🟢 live |
| Menu-11.png | Earnings & payouts | `GET /vendor/earnings` | 🟢 live |
| Menu-12.png | Payout History | `GET /vendor/payouts` | 🟢 live |
| Menu-8.png | Performance & ratings | `GET /vendor/performance` | 🟢 live |
| Menu-9.png | Promotions list | `GET /vendor/promotions` | 🟢 live |
| Menu-10.png | New Promotion form | `POST /vendor/promotions` | 🟢 live |
| Withdraw-5.png | "Your promotion is live" | rendered from the create response | 🟢 live |
| Withdraw-6.png | Promotion Details (+ pause/end) | `GET /vendor/promotions/{id}`; buttons → `PATCH /vendor/promotions/{id}` `{is_active}` / `{end_now}` | 🟢 live |
| Menu-2.png | Business Hour | `GET /vendor/hours` | 🟢 live |
| Menu-3.png | Edit hours | `PUT /vendor/hours` (whole week) | 🟢 live |
| Menu-4.png | Report (+ CSV) | `GET /vendor/analytics?date_from&date_to`; button → `GET /vendor/reports/csv` (text/csv download) | 🟢 live |
| Menu-5.png | Feedback (4.3★ histogram) | `GET /vendor/reviews/summary` + `GET /vendor/reviews` (filter chips are client-side — reviews have no tags) | 🟢 live |
| Menu-19.png | Commission Details | `commission_rate` from `GET /vendor/profile` | 🟢 live |
| Menu-6.png | Support | Call = phone dial, FAQ = static content; "Chat with us" has **no backend yet** | 🟠 partial |
| Message.png | Chat | **no backend yet** (rider/customer chat mockup; needs its own module) | 🔴 none |

### Withdraw flow

| Screen file | What it is | API | Status |
| --- | --- | --- | --- |
| Withdraw.png | Bank vs mobile wallet | client-side navigation | ⚪ client |
| Withdraw-1.png | bKash / Nagad / Rocket | client-side (`method` value for the request) | ⚪ client |
| Withdraw-2.png | Amount + destination form | balance from `GET /vendor/earnings`; submit → `POST /vendor/payouts` | 🟢 live |
| Withdraw-3.png | Confirm | client-side (same request on Confirm) | ⚪ client |
| Withdraw-4.png | "Payout Successful!" receipt | rendered from the payout response (`reference` = the transaction id) | 🟢 live |

Admin side of payouts: `GET /admin/payouts`, `POST /admin/payouts/{id}/complete`,
`POST /admin/payouts/{id}/fail`.