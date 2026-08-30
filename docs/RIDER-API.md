# Rider API

Everything the rider app runs on: the job list, the job screen with its handoff
code, going on and off shift, and the delivery that finally completes an order.

Base URL `…/api/v1`. Envelope `{"success": true, "data": {…}}`; failures use
`{"success": false, "error": {"code", "message", "details"}}`. Every endpoint
below needs a `RIDER` access token.

> **How this fits.** The specification names a RIDER in its permission matrix,
> hangs `orders.rider_id` off every order and describes live GPS, but defines no
> endpoint a rider can call. That gap had one very concrete consequence:
> `PICKED_UP → DELIVERED` was the only transition nothing in the system could
> perform, so every order stopped one step short of done — and with it earnings,
> payouts and the customer's right to leave a review.

---

## Contents

1. [Getting a token](#1-getting-a-token)
2. [Going on shift](#2-going-on-shift)
3. [The job list](#3-the-job-list)
4. [One job — and the handoff code](#4-one-job--and-the-handoff-code)
5. [Delivering](#5-delivering)
6. [Endpoint summary](#6-endpoint-summary)
7. [Known limitations](#7-known-limitations)
8. [Live position](#8-live-position)
9. [What the customer sees](#9-what-the-customer-sees)

---

## 1. Getting a token

**There is no rider signup.** `/auth/otp/send` accepts `CUSTOMER` and `VENDOR`
only, deliberately — a public endpoint that mints couriers would let anyone join
the delivery fleet. An administrator enrols you with `POST /admin/riders` and
sets a password; you sign in like everybody else:

```http
POST /auth/login
{"email":"rider@crshop.test","password":"…"}
```

Take the token from **`data.tokens.access_token`** — nested, *not*
`data.access_token`. Send it as `Authorization: Bearer <token>`. It lasts 30
minutes; `POST /auth/refresh` renews it.

A forgotten password is reset by an administrator (`PATCH /admin/riders/{id}`
with `password`), not by you. `/auth/password/forgot` mails an OTP, and a
courier account is not something to hand back on the strength of an inbox.

---

## 2. Going on shift

Dispatch only ever assigns orders to riders who are **online and verified**.
Clocking on is what puts you in that pool:

```http
PATCH /rider/me/shift
{"is_online": true}
```

```json
{
  "success": true,
  "data": {
    "rider_id": "…",
    "is_online": true,
    "orders_in_flight": 0,
    "message": "You are on shift and can be assigned orders"
  }
}
```

Clocking off stops new assignments. It does **not** release orders you are
already carrying — those are in a bag on your motorcycle, and a flag in a
database does not bring them back. Finish them.

`is_verified` is not yours to set; an administrator clears you to carry food.

---

## 3. The job list

```http
GET /rider/orders?tab=ACTIVE&limit=20&offset=0
```

Two tabs, and only two:

| `tab` | Statuses | Order |
|---|---|---|
| `ACTIVE` | PENDING, PREPARING, READY, PICKED_UP | Oldest first — the job waiting longest is the one going cold |
| `COMPLETE` | DELIVERED | Newest first; this is a history, not a queue |

A cancelled order appears in neither. It is gone, and filing it under completed
would credit you with a delivery that never happened.

Each row carries both ends of the trip — restaurant name, address and
coordinates, then the delivery address and coordinates — plus:

| Field | Meaning |
|---|---|
| `collect_on_delivery` | Cash to take at the door. `grand_total` for COD, `0.00` otherwise |
| `ready_at` | When the food was ready. Null means it is still cooking |
| `picked_up_at` | When you took it |

---

## 4. One job — and the handoff code

```http
GET /rider/orders/{order_id}
```

Adds the restaurant's phone, the customer's name and delivery contact number,
any `special_instructions`, and:

```json
{ "handoff_code": "7420" }
```

**Read those four digits out at the counter.** The vendor types them back, and
that is what proves a real courier collected the order rather than someone who
walked in claiming to be one.

`handoff_code` is present **only while the order is READY**, and only to the
rider carrying it. After pickup there is nothing left to prove and it is null.

> The vendor currently sees the same code on their screen, because their app was
> built before this endpoint existed. That is scheduled to go: removing the field
> from the two vendor responses is the whole change, and the verification
> underneath does not move.

An order assigned to another rider returns **404**, not 403 — confirming an id
exists tells anyone enumerating them which orders are real.

---

## 5. Delivering

```http
POST /rider/orders/{order_id}/deliver
```

**No body.** `PICKED_UP → DELIVERED`.

```json
{
  "success": true,
  "data": {
    "order_id": "…",
    "status": "DELIVERED",
    "delivered_at": "2026-08-30T20:11:04Z",
    "payment_status": "PAID",
    "total_deliveries": 42,
    "message": "Delivered. The order is complete."
  }
}
```

A COD order becomes `PAID` here, because this is the moment the cash changes
hands — the one payment this platform genuinely executes. Prepaid methods are
left alone; flipping them would forge a capture that never happened.

Failure modes:

| Situation | Status | Code |
|---|---|---|
| Order is not `PICKED_UP` yet | `409` | `CONFLICT` — collect it from the restaurant first |
| Not your order | `404` | `NOT_FOUND` |
| Already delivered | `409` | `CONFLICT` |

If your phone is dead or the app will not open, an administrator can confirm the
delivery for you with `POST /admin/orders/{id}/deliver`. The status history
records who confirmed it, so an operator-confirmed delivery is visibly not the
same event as one you confirmed at the door.

---

## 6. Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/rider/orders` | rider | My jobs — ACTIVE or COMPLETE |
| GET | `/rider/orders/{id}` | rider | One job, plus the handoff code while READY |
| POST | `/rider/orders/{id}/deliver` | rider | `PICKED_UP → DELIVERED` |
| PATCH | `/rider/me/shift` | rider | Go on or off shift |
| POST | `/rider/location` | rider | Report a live position |
| POST | `/admin/orders/{id}/deliver` | admin | Confirm a delivery the rider could not |

Enrolment and dispatch are administrator endpoints, documented in
[VENDOR-API.md](VENDOR-API.md): `POST /admin/riders`, `GET /admin/riders`,
`PATCH /admin/riders/{id}`, `POST /admin/orders/{id}/assign-rider`.

---

## 7. Known limitations

1. **No rider earnings screen.** Deliveries are counted (`total_deliveries`) but
   what a rider is paid is not modelled at all — there is no per-delivery fee,
   no rider payout table, and no endpoint. Vendor payouts exist; rider payouts
   do not.
2. **You cannot decline a job.** Dispatch assigns and that is the assignment.
   Refusing, returning an order to the pool, and the penalties real platforms
   attach to both are not modelled. An operator reassigns with
   `POST /admin/orders/{id}/assign-rider`.
3. **No push for new jobs.** `WS /ws/orders/{id}/live-tracking` streams one
   order you already have; there is no channel that tells you a job was
   assigned. Poll `GET /rider/orders` for that.
4. **No proof-of-delivery capture.** No photo, no signature, no drop-off note —
   the delivery is the rider's word plus a timestamp.

---

## 8. Live position

While you are on shift, report where you are:

```http
POST /rider/location
{"latitude": 23.7936, "longitude": 90.4064, "heading": 47, "speed_kph": 18.5}
```

`heading` and `speed_kph` are optional — a phone that has just acquired a fix
has a position before it has a bearing, and holding the position back until it
does would blank the customer's map for no reason.

```json
{
  "success": true,
  "data": {
    "recorded_at": "2026-08-30T20:04:11Z",
    "orders_notified": 1,
    "trail_written": false,
    "next_ping_seconds": 5
  }
}
```

Send one every `next_ping_seconds`. The response is honest about what happened
to it, so the app can show a real "live" indicator rather than assuming one:

| Field | Meaning |
|---|---|
| `orders_notified` | How many of your customers received it over their socket |
| `trail_written` | Whether it also landed in the audit trail. **Usually false** — the trail is decimated to one point per 30s, and that is by design, not a dropped ping |

Your position is only forwarded to customers whose order is `READY` or
`PICKED_UP`. Before that you are not yet going anywhere on their behalf; after
delivery the journey is over and where you drive next is not their business.

Stop pinging when you clock off. A position nobody refreshes expires from Redis
after five minutes, and everything downstream then reports "no live position"
rather than showing a dot frozen where you were — a stopped courier and a quiet
app must not look the same on a map.

---

## 9. What the customer sees

`WS /ws/orders/{order_id}/live-tracking` — spec #33, now live. The customer and
you are the only two parties who may open it; the vendor has their own feed.

The first frame is a snapshot so a client joining mid-journey draws immediately:

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

After that the channel carries `rider.location` frames from your pings,
`order.status` frames as the order moves, and `{"type":"ping"}` keepalives every
25 seconds — an idle socket through a reverse proxy is usually killed inside a
minute, and a tablet that quietly lost its connection looks exactly like one
with nothing happening.

Pass the access token as a query parameter (`?token=…`): browsers cannot set an
`Authorization` header on a WebSocket handshake. It is validated **before** the
socket is accepted.
