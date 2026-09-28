# Customer API — ordering food

Everything the customer app does, from opening the home screen to reviewing a
delivered order. Base URL, auth headers and the response envelope are shared
with the rest of the platform — see [AUTH-API.md](AUTH-API.md) for those.

Screens are in `ui/food-ui/`; the mapping is in
[SCREEN-API-MAP.md](SCREEN-API-MAP.md).

- Base URL: `https://api.cheeringshop.online/api/v1`
- Money is **whole taka** on the wire. The database stores paisa; you never see it.
- Every response is `{"success": true, "data": …}` or `{"success": false, "error": {…}}`.

---

## 1. The shape of an order

Five calls, in this order. Nothing here is optional except the promo code and
the tip.

```
GET  /restaurants?lat=&lng=      →  pick a restaurant
GET  /restaurants/{id}/menu      →  pick dishes
POST /cart/items                 →  build the cart      (repeat)
GET  /checkout/summary           →  show the real bill
POST /orders                     →  commit
```

**The backend is the single source of truth for pricing.** Do not compute a
total client-side and display it. `GET /checkout/summary` returns every line of
the bill, and `POST /orders` re-runs the identical arithmetic — a database CHECK
constraint refuses any order whose `grand_total` does not equal the sum of its
parts. If your screen shows a different number than the summary returned, your
screen is wrong.

---

## 2. Discovery

`GET /home/feed` is one request per app launch: the category chip row, cuisine
chips, restaurants with live offers, nearby, and top rated. Send `lat`/`lng`
when you have them — without coordinates `nearby` comes back as an empty list
(not absent) and every `distance_km` is `null`.

### Categories — the chip row

`categories` on the feed is the row of chips under the search bar: Burger,
Pizza, Biryani. Each one is a **platform category** — a bucket vendors' menu
sections are filed under. A vendor who names a section "Burgers" has put their
restaurant behind the Burger chip; they never see the taxonomy, and you never
see their section names.

```json
{ "id": "…", "name": "Burger", "slug": "burger", "image_url": "https://…/burger.png", "restaurant_count": 14 }
```

Render `image_url` (null when the operator has not set one — show a placeholder,
not a broken image). `slug` is what you send back. Only categories at least one
visible restaurant sells under are ever returned, so a chip never opens onto an
empty screen. The feed carries the first twelve — pinned ones first, then by
`restaurant_count`; `GET /categories` returns the full list for an "all
categories" screen.

A tap opens one of two screens, and both take the slug:

| Screen | Call |
|---|---|
| Restaurants in the category | `GET /restaurants?category={slug}` — the normal list, with every other filter and sort available |
| Dishes in the category ("all burgers near me") | `GET /categories/{slug}/items?lat=&lng=` — paginated dishes across restaurants, each carrying its restaurant's id, name, open state and rating |

The restaurant list is exactly as long as the chip's `restaurant_count`: both
are computed from the same rule (a visible restaurant with an active section
under the category holding at least one live dish). Dishes come back orderable
first, then open kitchens, then nearest, then best rated — a sold-out dish from
a closed restaurant is still a true answer, so it is last rather than missing.

`GET /categories/{slug}` resolves a slug on its own, for deep links. Unlike the
list, an empty category comes back here with `restaurant_count: 0` rather than
404 — a shared link should open onto "nothing here yet". A slug that was merged
into another category keeps working and returns the survivor; a hidden or
unknown slug is 404.

`GET /search` now also returns `categories` matching the query, so typing "bur"
offers the Burger chip above the burger-named dishes.

The whole feature, including how a chip comes to exist, is in
[CATEGORIES.md](CATEGORIES.md).

All discovery endpoints are **public**. Send the bearer token anyway when the
user is signed in: it is what fills in `is_favorite` on each card. An expired
token is ignored rather than rejected, so browsing never breaks on a stale
session.

`GET /restaurants` is the Filter and Sort screen:

| Param | Values |
|---|---|
| `sort` | `distance` (default), `rating`, `delivery_fee`, `prep_time`. The fee only rises with distance, so `delivery_fee` orders like `distance` (by rating when unlocated) |
| `category` | a category `slug` from the chip row — see *Categories* above |
| `cuisine` | one cuisine name (restaurant-level tag; predates categories) |
| `is_open` | `true` / `false` — omit to get both |
| `max_delivery_fee`, `min_rating` | numbers. `max_delivery_fee` keeps restaurants whose card fee fits — in effect a distance ceiling. Unlocated, it matches everything at or above the base fee and nothing below it |
| `radius` | metres, capped at 25000 |
| `q` | name search |

Every card's `delivery_fee` is quoted for its `distance_km`, on the same tariff
checkout charges (see §4). Without `lat`/`lng` it is the base fee — the least any
address pays. Checkout re-quotes from the delivery address, and only there does
a free-delivery threshold apply.

A **closed** restaurant still appears unless you filter it out. Grey it — do not
hide it. Hiding makes customers think the restaurant left the platform.

---

## 3. Cart

One restaurant per cart. Adding a dish from somewhere else is a **409** telling
you which restaurant is currently in the cart; empty it first.

**A line is one configuration**: an item, its variant, and its add-ons with
their quantities. The same dish can sit in the cart several times with
different add-ons (a plain burger and a burger with extra cheese are two lines).

**Adding from the item sheet** — `POST /cart/items` with `mode: "add"`:

```json
{
  "menu_item_id": "…",
  "variant_id": "…",
  "add_ons": [{"add_on_id": "…", "quantity": 2}],
  "quantity": 1,
  "mode": "add",
  "notes": "extra spicy"
}
```

- `mode: "add"` adds `quantity` to an identical line, or creates it. The
  default `mode: "set"` sets the line's quantity instead (`0` removes it).
- If the dish **has variants, `variant_id` is required** — a 400 lists the
  choices. There is no silent default: defaulting to the cheapest is how a
  customer ends up charged for a small when the screen said large.
- **Add-on quantities.** Each add-on on the menu has `max_quantity`: `1` means
  on/off (a checkbox); more means a stepper, e.g. "Extra cheese, up to 3".
  Send `add_ons: [{add_on_id, quantity}]`; the older `add_on_ids` list still
  works, and repeating an id there counts it again. Over the limit is a 400.
  An add-on's quantity is **per unit**: 2 burgers each with 2× cheese is
  4 cheeses, priced (burger + 2 × cheese) × 2.

**The cart screen's buttons** — address the line by the `id` from `GET /cart`,
so nothing else has to be sent again:

| Button | Call |
|---|---|
| + / − | `PATCH /cart/items/{line_id}` `{"quantity": 3}` (`0` removes) |
| Bin | `DELETE /cart/items/{line_id}` |

Removing the last line deletes the cart.

Each line returns `add_ons` (`id`, `name`, `unit_price`, `quantity`),
`add_on_names` ready to print ("Extra cheese ×2"), `add_ons_total` (per unit)
and `line_total`. Orders keep the same: each order line lists its add-ons with
the price charged and the quantity.

**Prices are recomputed on every read.** The cart stores what was chosen, never
what it cost. A vendor's price change shows up before the customer commits, and
`is_available: false` on a line means the vendor turned it off — grey it and
block checkout until it is removed.

**Hidden and featured dishes.** A dish the platform has hidden does not appear
anywhere: not in the menu, search, category lists or cart. A cart line for one
simply drops out, the same way a deleted dish does. Menu items carry
`is_featured: true` when the platform is promoting them; show a badge if the
design has one.

---

## 4. Checkout and placing the order

`GET /checkout/summary?address_id=…&promo_code=…&tip=20` returns the full bill:

| Field | Notes |
|---|---|
| `item_total` | sum of the lines |
| `delivery_fee` | ৳10 base covering the first km, then ৳8 per **started** km. Identical from every restaurant |
| `packaging_fee` | flat, per order |
| `tax_amount` | on food only — never on delivery, fees or tip |
| `platform_fee` | service fee |
| `discount` | applied **after** tax, so a promo never reduces tax remitted |

Delivery worked through, since rounding surprises people: **1.0 km → ৳10**,
**1.2 km → ৳18** (one started km beyond the free one), **3.0 km → ৳26**,
**5.0 km → ৳42**. Started kilometres, not rounded ones — 1.2 km of overage is
two kilometres of a rider's time.
| `tip` | as sent |
| `grand_total` | the sum of the above, minus discount |

A **bad promo code does not fail this call.** The bill returns with
`promo_error` explaining why nothing was applied — show that string. At
`POST /orders` the same bad code is a hard **400**, because by then the customer
is committing to a total.

`POST /orders` takes `payment_method`, `address_id`, and optionally
`promo_code`, `tip`, `special_instructions`, `scheduled_for`.

**Send an `Idempotency-Key` header.** A retry with the same key replays the
original response instead of placing a second order — which is exactly what
happens on a flaky mobile connection when the response is lost. Reusing a key
with a *different* body is a 409, as is a genuine double-submit while the first
is still running.

The cart is cleared in the same transaction as the order is created.

---

## 5. Scheduled delivery

`GET /restaurants/{id}/schedule` returns date tabs and 10-minute windows,
generated from the restaurant's business hours. Slots inside the lead time come
back with `is_available: false` rather than being omitted — render them greyed.

Pass the chosen slot's `starts_at` as `scheduled_for` on `POST /orders`. It is
re-validated server-side against the same lead time, so a stale sheet is a 400
rather than an order the kitchen cannot make.

A scheduled order has **no 60-second vendor countdown**: the timer starts when
the kitchen is asked, not when the customer books.

---

## 6. Orders, tracking and chat

`GET /orders?status_filter=ACTIVE` is the Order tab — `ACTIVE` means PENDING,
PREPARING, READY or PICKED_UP in one filter.

`GET /orders/{id}/tracking` bootstraps the map: status, the timeline that draws
the dots on Ride Assign, both endpoints of the journey, and `eta_minutes`.

`rider` names who is bringing it once a rider has accepted the order (an
`order.rider_assigned` frame on the tracking socket says when) — name,
photo, rating and vehicle, never a phone number (`POST /orders/{id}/call`
bridges the two of you without either side learning the other's).

**`rider_location` is live while the order is READY or PICKED_UP**, and `null`
otherwise. Before READY the rider is not yet travelling on your behalf; after
delivery the journey is over. It is also `null` whenever the rider's app has
gone quiet — `live_tracking_available` tells you which case you are in, and a
dot frozen where a courier was ten minutes ago would read as someone who had
stopped moving, so the absence is reported rather than papered over.

### Live tracking

`WS /ws/orders/{id}/live-tracking?token=<access_token>` streams the journey.
Browsers cannot set an `Authorization` header on a WebSocket handshake, so the
token goes in the query string; it is validated before the socket is accepted.
Only you and your rider may open it.

The first frame is a snapshot, so a screen opened mid-journey draws immediately:

```json
{
  "type": "tracking.snapshot",
  "order_id": "…",
  "status": "PICKED_UP",
  "eta_minutes": 12,
  "rider_location": {"latitude": 23.7936, "longitude": 90.4064, "heading": 47},
  "live_tracking_available": true
}
```

Then: `rider.location` frames roughly every five seconds while the rider is
moving, `order.status` frames as the order advances, and `{"type":"ping"}`
keepalives every 25 seconds. Keep the HTTP call as your fallback — publishing is
best-effort, so a socket is an optimisation rather than a source of truth.

`POST /orders/{id}/cancel` works **only while PENDING**. After the vendor
accepts, food is being cooked and the answer is a 409.

`GET`/`POST /orders/{id}/messages` is the Message screen. The order *is* the
thread: opening it marks the counterparty's messages read, and the channel
closes a day after delivery. `POST /orders/{id}/call` returns
`available: false` — no telephony provider is connected, and it will never
return a raw phone number.

---

## 7. Reviews

`POST /orders/{id}/reviews` — one per order, and only once **DELIVERED**. The
restaurant's rating is recomputed from the reviews table in the same
transaction.

---

## 8. Endpoint summary

Auth column: **public** needs no token, **customer** needs a CUSTOMER token,
**any** accepts any signed-in role.

| Method | Path | Auth | What |
|---|---|---|---|
| GET | `/home/feed` | public | Dashboard: category chips, cuisines, offers, nearby, top rated |
| GET | `/categories` | public | Every browse category with restaurants under it |
| GET | `/categories/{slug}` | public | One category, for deep links |
| GET | `/categories/{slug}/items` | public | Dishes in a category, across restaurants |
| GET | `/restaurants` | public | Filtered + sorted list (`category=` for a chip) |
| GET | `/restaurants/{id}` | public | Details, with live offers |
| GET | `/restaurants/{id}/menu` | public | Categorised menu, variants, add-ons |
| GET | `/restaurants/{id}/schedule` | public | Bookable delivery slots |
| GET | `/search` | public | Restaurants, dishes and categories |
| GET | `/cart` | customer | Current cart, live prices |
| POST | `/cart/items` | customer | Add / update / remove a line |
| PATCH | `/cart/items/{line_id}` | customer | Change a line's quantity |
| DELETE | `/cart/items/{line_id}` | customer | Remove a line |
| GET | `/checkout/summary` | customer | The full bill |
| POST | `/orders` | customer | Place the order |
| GET | `/orders` | customer | Order history |
| GET | `/orders/{id}` | customer | Receipt + timeline |
| POST | `/orders/{id}/cancel` | customer | Cancel, PENDING only |
| GET | `/orders/{id}/tracking` | any | Map bootstrap |
| GET | `/orders/{id}/messages` | any | Chat thread |
| POST | `/orders/{id}/messages` | any | Send a message |
| POST | `/orders/{id}/call` | any | Masked call (not configured) |
| POST | `/orders/{id}/reviews` | customer | Review a delivered order |
| GET | `/users/me/addresses` | any | Saved addresses, default first |
| POST | `/users/me/addresses` | any | Save one |
| PUT | `/users/me/addresses/{id}` | any | Replace one |
| DELETE | `/users/me/addresses/{id}` | any | Delete one |
| PATCH | `/users/me/addresses/{id}/default` | any | Set default |
| GET | `/users/me/favorites` | any | My Favorites |
| POST | `/users/me/favorites/{id}` | any | Toggle the heart |

---

## 9. Known limitations

1. **No live rider position.** See §6. Status, timeline and ETA are real; the
   moving dot is not implemented because nothing produces the data.
2. **Payment is recorded, not taken.** `payment_status` is `PENDING` on every
   new order regardless of `payment_method`. No gateway is connected.
3. **Masked calling is not configured.** `POST /orders/{id}/call` returns
   `available: false`.
4. **No push notifications.** `POST /users/me/devices` does not exist, so the
   app learns about status changes by polling or by holding the vendor
   WebSocket.
5. **Reels has no backend.** The screen exists in `ui/food-ui/`; nothing serves
   it.
6. **Slot capacity is not modelled.** Every open window is bookable, because
   nothing tracks kitchen throughput. A busy restaurant can be over-booked.
