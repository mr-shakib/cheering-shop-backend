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

`GET /home/feed` is one request per app launch: cuisine chips, restaurants with
live offers, nearby, and top rated. Send `lat`/`lng` when you have them —
without coordinates `nearby` comes back as an empty list (not absent) and every
`distance_km` is `null`.

All discovery endpoints are **public**. Send the bearer token anyway when the
user is signed in: it is what fills in `is_favorite` on each card. An expired
token is ignored rather than rejected, so browsing never breaks on a stale
session.

`GET /restaurants` is the Filter and Sort screen:

| Param | Values |
|---|---|
| `sort` | `distance` (default), `rating`, `delivery_fee`, `prep_time` |
| `cuisine` | one cuisine name |
| `is_open` | `true` / `false` — omit to get both |
| `max_delivery_fee`, `min_rating` | numbers |
| `radius` | metres, capped at 25000 |
| `q` | name search |

A **closed** restaurant still appears unless you filter it out. Grey it — do not
hide it. Hiding makes customers think the restaurant left the platform.

---

## 3. Cart

One restaurant per cart. Adding a dish from somewhere else is a **409** telling
you which restaurant is currently in the cart; empty it first.

`POST /cart/items` is add, update *and* remove:

```json
{ "menu_item_id": "…", "variant_id": "…", "add_on_ids": ["…"], "quantity": 2, "notes": "extra spicy" }
```

- `quantity: 0` removes the line. Removing the last line deletes the cart.
- If the dish **has variants, `variant_id` is required** — a 400 lists the
  choices. There is no silent default: defaulting to the cheapest is how a
  customer ends up charged for a small when the screen said large.
- Same item + same variant + same add-ons = the same line, so tapping "+" twice
  increments rather than duplicating.

**Prices are recomputed on every read.** The cart stores what was chosen, never
what it cost. A vendor's price change shows up before the customer commits, and
`is_available: false` on a line means the vendor turned it off — grey it and
block checkout until it is removed.

---

## 4. Checkout and placing the order

`GET /checkout/summary?address_id=…&promo_code=…&tip=20` returns the full bill:

| Field | Notes |
|---|---|
| `item_total` | sum of the lines |
| `delivery_fee` | restaurant base + per-km beyond the first km |
| `packaging_fee` | flat, per order |
| `tax_amount` | on food only — never on delivery, fees or tip |
| `platform_fee` | service fee |
| `discount` | applied **after** tax, so a promo never reduces tax remitted |
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

> **`rider_location` is always `null` today and `live_tracking_available` is
> `false`.** There is no rider app, so nothing reports a position. This is
> deliberate rather than unfinished — an interpolated dot would show a courier
> who is not there. `WS /ws/orders/{id}/live-tracking` returns **501** for the
> same reason. Everything else on the tracking screen is real.

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
| GET | `/home/feed` | public | Dashboard: cuisines, offers, nearby, top rated |
| GET | `/restaurants` | public | Filtered + sorted list |
| GET | `/restaurants/{id}` | public | Details, with live offers |
| GET | `/restaurants/{id}/menu` | public | Categorised menu, variants, add-ons |
| GET | `/restaurants/{id}/schedule` | public | Bookable delivery slots |
| GET | `/search` | public | Restaurants and dishes |
| GET | `/cart` | customer | Current cart, live prices |
| POST | `/cart/items` | customer | Add / update / remove a line |
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
