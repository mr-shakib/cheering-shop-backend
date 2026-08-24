# Screen → API map

One row per mockup in `ui/`. Base URL and conventions are in
[VENDOR-API.md](VENDOR-API.md); the registration flow's request/response
examples are in [AUTH-API.md](AUTH-API.md) §11.

A screen with **client-side** means no network call: it renders static content
or data already fetched by an earlier screen.

## Vendor application form (`ui/Vendor application form/`)

| Screen file | What it is | API |
|---|---|---|
| Onboarding.png | "Become a partner" landing | client-side |
| Onboarding-1.png | Splash | client-side |
| Onboarding-2.png | "Your partner account is ready" | client-side (arrival from the approval email) |
| Business Information.png | Form step 1 | collected locally; sent at Review |
| Location.png | Form step 2 (map pin) | collected locally; sent at Review |
| Owner Information.png | Form step 3, "we'll send an OTP" | `POST /auth/otp/send` `{email, role: "VENDOR"}` |
| Document.png | Upload shop image / NID / menu / licence | `POST /vendor/applications/uploads` per file, then PUT bytes to `upload_url` |
| Review.png | Review & Submit | `POST /vendor/applications` (whole form + `otp_code`) |
| Document-1.png | "Application submitted! #PTN-88291" | rendered from the submit response; later `GET /vendor/applications/{no}?email=` to poll status |
| Login.png | Phone/email + password | `POST /auth/login` |
| Login-1.png | Enter OTP | `POST /auth/password/forgot` (sends code) |
| Login-2.png | Set Password | `POST /auth/password/reset` `{email, code, new_password}` |

Admin console for this flow: `GET /admin/vendor-applications`,
`GET /admin/vendor-applications/{id}`, `POST …/{id}/approve`, `POST …/{id}/reject`.

## Customer app (`ui/food-ui/`)

Full request/response detail is in [CUSTOMER-API.md](CUSTOMER-API.md).

### Browse

| Screen file | What it is | API |
|---|---|---|
| Food.png | Home dashboard | `GET /home/feed?lat=&lng=` (one call: cuisines, offers, nearby, top rated) |
| Food-1.png, Food-2.png | Feed scrolled | same response, rendered further |
| Scroll.png | Restaurant carousel | `GET /restaurants?lat=&lng=` |
| Category listing (Pizza).png | One cuisine | `GET /restaurants?cuisine=Pizza` |
| Filter and Short.png | Filter + sort sheet | `GET /restaurants` with `sort`, `min_rating`, `max_delivery_fee`, `is_open` |
| Search.png | Empty search | client-side (recent searches are local) |
| Search results.png | Results | `GET /search?q=` — returns restaurants **and** dishes |
| Restuarent Details.png | Storefront header | `GET /restaurants/{id}` (`promotions` drives the offer ribbon) |
| Restuarent Details-1.png | Menu list | `GET /restaurants/{id}/menu` |
| Restuarent Details-2.png | Menu, scrolled to a category | same response; category jump is client-side |
| My favorite.png | Empty state | `GET /users/me/favorites`, zero rows |
| My favorite-1.png | Saved list | `GET /users/me/favorites`; heart → `POST /users/me/favorites/{id}` |
| Schedule Order.png | Delivery-time sheet | `GET /restaurants/{id}/schedule`; Confirm carries the slot into `scheduled_for` |
| Share Details.png | Share sheet | client-side (OS share; no backend) |
| Reels.png | Video feed | **no backend** — not in the spec, nothing serves it |

### Cart and checkout

| Screen file | What it is | API |
|---|---|---|
| Empty Cart.png | Nothing added | `GET /cart` returns an empty cart, not a 404 |
| Cart.png | Lines + quantities | `GET /cart`; +/−/remove → `POST /cart/items` (`quantity: 0` removes) |
| Order Modify.png | Edit a line's options | `POST /cart/items` with the new `variant_id` / `add_on_ids` |
| Checkout.png | Address, payment, bill | `GET /checkout/summary?address_id=&promo_code=&tip=` |
| Checkout-1.png | Promo applied | same call; a bad code returns the bill plus `promo_error` |
| Address.png | Address picker + add | `GET/POST /users/me/addresses`; star → `PATCH …/{id}/default` |
| Order Complete.png | "Order placed" | rendered from `POST /orders` (send an `Idempotency-Key`) |

### After ordering

| Screen file | What it is | API |
|---|---|---|
| Order.png | Order list | `GET /orders?status_filter=ACTIVE` |
| Order-1.png | Empty history | same call, zero rows |
| Order Details.png | Receipt + timeline | `GET /orders/{id}` |
| Preparing food.png | Status while cooking | `GET /orders/{id}/tracking` (poll — no push yet) |
| Ride Assign.png | "Arriving in 12 mins" + steps | `GET /orders/{id}/tracking` (`timeline` draws the dots, `eta_minutes` the header) |
| Track order.png | Map | `GET /orders/{id}/tracking` for the endpoints and ETA. **The rider dot is not implemented** — `rider_location` is null and `WS /ws/orders/{id}/live-tracking` is a 501, because no rider client reports a position |
| Message.png | Chat with the rider | `GET/POST /orders/{id}/messages` |
| Call Screen.png | Calling | `POST /orders/{id}/call` — returns `available: false`; no telephony provider is configured |
| Review.png | Rate the order | `POST /orders/{id}/reviews` (DELIVERED only, one per order) |
| Profile.png | Account | `GET /users/me`; edit → `PUT /users/me/profile` |


## Vendor app (`ui/full vendor/`)

### Order tab

| Screen file | What it is | API |
|---|---|---|
| Home.png | Queue, New tab + chips + store toggle | `GET /vendor/dashboard` (chips, toggle state) + `GET /vendor/orders?status=PENDING`; toggle → `PATCH /vendor/store/status` |
| Home-1.png | Preparing tab, "Mark as Ready" | `GET /vendor/orders?status=PREPARING`; button → `POST /vendor/orders/{id}/ready` |
| Home-7.png | Empty queue state | same queue calls, zero rows |
| Home-8.png | Order Details (items, 0:42 countdown, call) | `GET /vendor/orders/{id}` (`seconds_to_auto_decline` drives the countdown); call → `POST /orders/{id}/call` |
| Home.png Accept / Reject buttons | Decide an order | `POST /vendor/orders/{id}/accept` / `…/reject` |
| Home-4.png | Reject reasons list | `POST /vendor/orders/{id}/reject` `{reason}` (chips are client copy; note: the backend refunds + notifies, it does **not** rebook — soften that sentence) |
| Home-2.png | "Hand this code to your rider" | `handoff_code` from the ready response or `GET /vendor/orders/{id}` while READY; Confirm → `POST /vendor/orders/{id}/handoff` `{rider_pin}` |
| Home-3.png | Order completed (+৳680 today) | handoff response + `GET /vendor/dashboard` (`today_orders`, `today_earnings`) |
| Home-5.png | Timeout / auto-declined | order arrives as CANCELLED in the queue; screen itself client-side |
| Home-6.png | New-order push banner | no push yet — poll `GET /vendor/orders?status=ACTIVE` (see VENDOR-API.md Known limitations 2 & 6) |
| Order.png | Overview tab | `GET /vendor/dashboard` (earnings, orders, rating, acceptance, 7-day chart, recent orders) |

### Menu tab

| Screen file | What it is | API |
|---|---|---|
| Menu.png | Menu list, availability toggles | `GET /vendor/menu`; toggle → `PATCH /vendor/menu/items/{id}/status` (search/chips filter client-side) |
| Menu-13.png | Add new item ("You receive ৳425") | `POST /vendor/menu/items`; fee math from `commission_rate` in `GET /vendor/profile`; photo → `POST /uploads/presigned-url` |
| Menu-14.png | Product Variants | `variants` array on item create/update |
| Menu-15.png | Add Ones (add-ons) | `add_ons` array on item create/update |
| Menu-18.png | "Item added" success | rendered from the create response |
| Menu-16.png | Category list (drag to reorder) | `GET /vendor/menu/categories`; drag → `PATCH /vendor/menu/reorder`; edit → `PATCH /vendor/menu/categories/{id}` |
| Menu-17.png | Add category sheet | `POST /vendor/menu/categories` |
| Edit menu.png | Store Profile edit | `PATCH /vendor/profile`; photo → `POST /uploads/presigned-url` |

### Profile tab

| Screen file | What it is | API |
|---|---|---|
| Menu-1.png | Profile menu | client-side navigation |
| Menu-7.png | Store Profile view | `GET /vendor/profile`; Change Password → `POST /users/me/password` |
| Menu-11.png | Earnings & payouts | `GET /vendor/earnings` |
| Menu-12.png | Payout History | `GET /vendor/payouts` |
| Menu-8.png | Performance & ratings | `GET /vendor/performance` |
| Menu-9.png | Promotions list | `GET /vendor/promotions` |
| Menu-10.png | New Promotion form | `POST /vendor/promotions` |
| Withdraw-5.png | "Your promotion is live" | rendered from the create response |
| Withdraw-6.png | Promotion Details (+ pause/end) | `GET /vendor/promotions/{id}`; buttons → `PATCH /vendor/promotions/{id}` `{is_active}` / `{end_now}` |
| Menu-2.png | Business Hour | `GET /vendor/hours` |
| Menu-3.png | Edit hours | `PUT /vendor/hours` (whole week) |
| Menu-4.png | Report (+ CSV) | `GET /vendor/analytics?date_from&date_to`; button → `GET /vendor/reports/csv` (text/csv download) |
| Menu-5.png | Feedback (4.3★ histogram) | `GET /vendor/reviews/summary` + `GET /vendor/reviews` (filter chips are client-side — reviews have no tags) |
| Menu-19.png | Commission Details | `commission_rate` from `GET /vendor/profile` |
| Menu-6.png | Support | Call = phone dial, FAQ = static content; "Chat with us" has **no backend yet** |
| Message.png | Chat | **no backend yet** (rider/customer chat mockup; needs its own module) |

### Withdraw flow

| Screen file | What it is | API |
|---|---|---|
| Withdraw.png | Bank vs mobile wallet | client-side navigation |
| Withdraw-1.png | bKash / Nagad / Rocket | client-side (`method` value for the request) |
| Withdraw-2.png | Amount + destination form | balance from `GET /vendor/earnings`; submit → `POST /vendor/payouts` |
| Withdraw-3.png | Confirm | client-side (same request on Confirm) |
| Withdraw-4.png | "Payout Successful!" receipt | rendered from the payout response (`reference` = the transaction id) |

Admin side of payouts: `GET /admin/payouts`, `POST /admin/payouts/{id}/complete`,
`POST /admin/payouts/{id}/fail`.
