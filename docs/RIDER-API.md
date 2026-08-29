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
| POST | `/admin/orders/{id}/deliver` | admin | Confirm a delivery the rider could not |

Enrolment and dispatch are administrator endpoints, documented in
[VENDOR-API.md](VENDOR-API.md): `POST /admin/riders`, `GET /admin/riders`,
`PATCH /admin/riders/{id}`, `POST /admin/orders/{id}/assign-rider`.

---

## 7. Known limitations

1. **No live position.** Nothing reports where you are. `rider_profiles` has
   last-known coordinates and there is a partitioned `rider_location_pings`
   table waiting for them, but no endpoint writes either, so the customer's map
   shows your name and not your dot. `live_tracking_available` is honestly
   `false` rather than showing a courier who is not there.
2. **No rider earnings screen.** Deliveries are counted (`total_deliveries`) but
   what a rider is paid is not modelled at all — there is no per-delivery fee,
   no rider payout table, and no endpoint. Vendor payouts exist; rider payouts
   do not.
3. **You cannot decline a job.** Dispatch assigns and that is the assignment.
   Refusing, returning an order to the pool, and the penalties real platforms
   attach to both are not modelled. An operator reassigns with
   `POST /admin/orders/{id}/assign-rider`.
4. **No push.** `WS /ws/orders/{id}/live-tracking` is routed but returns 501,
   so a new job arrives when you poll for it.
5. **No proof-of-delivery capture.** No photo, no signature, no drop-off note —
   the delivery is the rider's word plus a timestamp.
