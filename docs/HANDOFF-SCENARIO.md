# The handoff, as it actually happens

One order, two phones, one counter. This is the scenario the screens are built
for, with the API call that belongs to each moment.

**Cast.** Rahim ordered a burger. *Kitchen 12* is cooking it. *Jamil* is the
rider. Nobody chooses anybody — the platform assigns Jamil, the way foodpanda
does. The vendor never picks a rider and never sees the rider pool.

---

## The story

**Jamil clocks on.** He opens his app and flips the shift toggle. Until he does
this the platform will not give him work.

> `PATCH /rider/me/shift` `{"is_online": true}`

**Rahim orders.** A new ticket appears on the kitchen tablet — pushed, not
polled.

> Vendor: `WS /ws/vendor/live` → frame `order.placed`
> (fallback: `GET /vendor/orders?status=NEW`)

**The kitchen accepts.** They tap Accept and start cooking. *Invisibly, in the
same request, the platform assigns Jamil* — the nearest rider on shift. Nobody
on either screen is asked about this.

> Vendor: `POST /vendor/orders/{id}/accept` — no body

**A job appears on Jamil's phone.** Pickup address, dropoff address, what cash
to collect. He starts riding.

> Rider: `GET /rider/orders?tab=ACTIVE` (poll — there is no push for new jobs)
> Rider: `POST /rider/location` every 5 seconds while moving

**The food is ready.** The kitchen taps Mark as Ready. **This is the moment the
secret is created** — a random 4-digit code that did not exist a second ago.

> Vendor: `POST /vendor/orders/{id}/ready` — no body → response has `handoff_code`

**Both screens now show the same 4 digits.** Jamil's job screen shows it because
he is the one who has to prove who he is. The kitchen's screen shows it too, for
now — see *The temporary bit* below.

> Rider: `GET /rider/orders/{id}` → `handoff_code`
> Vendor: `GET /vendor/orders/{id}` → `handoff_code` (re-read on every mount)

**The exchange.** Jamil walks in. *"Order for Rahim — seven four two zero."* The
cashier types `7420` and taps Confirm. The bag goes over the counter.

> Vendor: `POST /vendor/orders/{id}/handoff` `{"rider_pin": "7420"}`

**The code dies.** It is destroyed on success and never works again. It vanishes
from both screens in the same instant.

**Jamil rides to Rahim.** Rahim watches him move on a map.

> Rider: `POST /rider/location` every 5 seconds
> Customer: `WS /ws/orders/{id}/live-tracking`

**Delivered.** Jamil takes the cash and taps Delivered. The order is complete,
COD flips to paid, and the kitchen's earnings move.

> Rider: `POST /rider/orders/{id}/deliver` — no body

---

## What is on each screen, at each moment

| Moment | Restaurant tablet | Rider phone |
|---|---|---|
| Order placed | New ticket in **New** tab | — |
| Accepted | Ticket moves to **Preparing** | Job card appears |
| Cooking | Prep timer | Route to restaurant |
| **Ready** | **Code `7420`** + "Hand this to your rider" | **Code `7420`** + "Read this to the vendor" |
| At the counter | **PIN input** + Confirm | Code, large and readable |
| Handed over | Ticket moves to **Complete** | Route to customer |
| Delivered | Earnings update | Job moves to **Completed** |

**The exchange is spoken.** There is no network call between the two phones. The
rider says four digits out loud; the vendor types them. That is the entire
protocol, and it is deliberate — a person saying a number they can only know by
being present is the proof.

---

## Screen → API

### Restaurant app

| Screen | Call |
|---|---|
| Order queue | `GET /vendor/orders?status=NEW\|PREPARING\|COMPLETE` |
| Live alerts | `WS /ws/vendor/live?token=…` |
| Order detail | `GET /vendor/orders/{id}` |
| Accept / Reject | `POST /vendor/orders/{id}/accept` · `POST …/reject` `{"reason"}` |
| Mark as Ready | `POST /vendor/orders/{id}/ready` → **`handoff_code`** |
| Handoff screen (on mount) | `GET /vendor/orders/{id}` → **`handoff_code`** |
| Confirm | `POST /vendor/orders/{id}/handoff` `{"rider_pin"}` |
| New code (after lockout) | `POST /vendor/orders/{id}/ready` again |
| Home totals | `GET /vendor/dashboard` |

### Rider app

| Screen | Call |
|---|---|
| Shift toggle | `PATCH /rider/me/shift` `{"is_online"}` |
| My jobs | `GET /rider/orders?tab=ACTIVE\|COMPLETE` |
| Job detail | `GET /rider/orders/{id}` → **`handoff_code`** while READY |
| Background, while moving | `POST /rider/location` `{lat, lng, heading?, speed_kph?}` |
| Delivered | `POST /rider/orders/{id}/deliver` |

### Customer app (for context)

| Screen | Call |
|---|---|
| Track order | `GET /orders/{id}/tracking` then `WS /ws/orders/{id}/live-tracking?token=…` |

---

## When it goes wrong

All on the vendor's Confirm button. Branch on `error.code`, never the message.

| What happened | HTTP | `error.code` | Screen does |
|---|---|---|---|
| Wrong digits | `400` | `INVALID_RIDER_PIN` | Clear input, show tries left from `details[0]`, stay open |
| 5 wrong tries | `409` | `INVALID_RIDER_PIN` | Lock input, offer **Get a new code** → call `ready` again |
| No rider yet | `409` | `CONFLICT` | "Waiting for a rider" — not the vendor's fault, not retryable |
| Order not READY | `409` | `CONFLICT` | Stale local state — re-fetch the order |
| Token expired (30 min) | `401` | — | Refresh and replay. **Must not spend a PIN try** |

---

## Rules for whoever builds this

**Never retry automatically.** Five tries exist in total and they are counted on
the server, across requests, sessions and app restarts. An auto-retry spends a
real person's budget without telling them. Disable the button while the request
is in flight — a double-tap costs two tries.

**Never cache the code.** No local storage, no long-lived store, no logs.
Re-fetch it from the order detail on every mount. It goes `null` the moment the
order leaves READY, and a cached copy would outlive the truth.

**The token is nested.** `data.tokens.access_token`, not `data.access_token`.

**Size the input from the data.** Four digits is a server setting. Drive the box
count off the length of the code you received.

### The temporary bit

The vendor currently sees the code *and* types it, which proves nothing — they
already know the answer. That is a leftover from before the rider app existed,
and it is scheduled to go: the field will be removed from the `ready` response
and the order detail, leaving the input alone.

**So build the input as the primary element and the code display as a separate
block you can delete.** When the field disappears, the screen should not need
rebuilding. Nothing else about the flow changes — the same call, the same
verification.

---

## Before you start testing

`409 "No rider is available to take this order"` is **not a client bug**. It
means no rider exists in that environment. Dispatch can only assign somebody who
is enrolled, verified and on shift. One call per environment, as an admin:

```http
POST /admin/riders
{"full_name":"Demo Rider","phone":"+8801799000001","vehicle_type":"MOTORCYCLE"}
```

Full reference: [VENDOR-API.md](VENDOR-API.md) §7 · [RIDER-API.md](RIDER-API.md)
