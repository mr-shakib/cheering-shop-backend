# Realtime sockets

Three plain WebSocket endpoints (not Socket.IO), one per app. Each one only
pushes JSON frames from the server to the app. The app never sends anything
over them; every action still goes through the REST API.

Base: `wss://api.cheeringshop.online/api/v1` (local: `ws://localhost:8000/api/v1`).
Auth is covered in [AUTH-API.md](AUTH-API.md).

**The socket is a speed-up, not the source of truth.** The server publishes
best-effort, so a frame can be lost. Each screen loads from REST first and
reloads after every reconnect.

---

## 1. At a glance

| App | Endpoint | Who may open it | What it carries |
|---|---|---|---|
| Vendor | `/ws/vendor/live` | The restaurant owner. The restaurant comes from the token | New orders, status changes, rider assigned and chat messages for that restaurant's orders |
| Customer | `/ws/orders/{order_id}/live-tracking` | The customer who placed the order | Rider position, status changes, rider assigned, chat messages |
| Rider (job) | `/ws/orders/{order_id}/live-tracking` | The rider carrying that order | Same channel as the customer |
| Rider (offers) | `/ws/rider/offers` | Any rider account | New delivery offers, food-ready offers, offers taken |

---

## 2. Connecting

Put the access token in the query string as `?token=`. WebSocket handshakes
cannot carry an `Authorization` header, so the header is not read here.

```
wss://api.cheeringshop.online/api/v1/ws/vendor/live?token=<access_token>
wss://api.cheeringshop.online/api/v1/ws/orders/<order_id>/live-tracking?token=<access_token>
wss://api.cheeringshop.online/api/v1/ws/rider/offers?token=<access_token>
```

- Use the same **access** token you send to the REST API. A refresh token is
  refused.
- The token is checked once, at the handshake. An open socket keeps working
  after the token expires (access tokens last 30 minutes). A reconnect needs a
  fresh token, so refresh it first if it has expired.

**A refused connection fails at the handshake with HTTP 403.** The server never
opens the socket, so the app sees a failed connect, not a close frame. In a
browser that is `onerror` then `onclose` with code `1006` and no reason. In
Flutter the `ready` future throws. The server logs the reason, but the app
cannot see it:

| Cause | Endpoint |
|---|---|
| No `token`, or an expired, malformed or refresh token | All three |
| The order does not exist, or it is not yours | `/ws/orders/{id}/live-tracking` |
| The account owns no restaurant | `/ws/vendor/live` |
| The account is not a rider | `/ws/rider/offers` |

The vendor cannot open an order's tracking socket. A customer and a rider can
only open orders they are on. A 403 on a token you know is fresh means you are
calling the wrong endpoint for that account, so do not retry it in a loop.

---

## 3. Messages from the server

Every frame is one JSON object with a `type` field. Switch on `type` and ignore
types you do not know, so new ones can be added without breaking old builds.

All three sockets also send `{"type":"ping"}` after 25 seconds of silence. It
keeps proxies from dropping the idle connection and needs no reply.

### 3.1 Vendor: `/ws/vendor/live`

| `type` | When | Fields |
|---|---|---|
| `order.placed` | A customer placed an order with this restaurant | `order`: a summary with `id`, `order_number`, `status`, `grand_total`, `payment_method`, `payment_status`, `estimated_delivery_at`, `scheduled_for`, `restaurant_id`, `restaurant_name`, `placed_at`. No items — load them with `GET /vendor/orders/{id}` |
| `order.status` | Any order of this restaurant changed status | See §3.3 |
| `order.rider_assigned` | A rider accepted one of this restaurant's orders, or support assigned one | `order_id`, `order_number`. Load the rider's name and photo with `GET /vendor/orders/{id}` |
| `chat.message` | Anyone on one of this restaurant's orders sent a chat message | Same as on the tracking socket (§3.2) |

```json
{
  "type": "order.placed",
  "order": {
    "id": "7b0c…",
    "order_number": 1042,
    "status": "PENDING",
    "grand_total": "350.00",
    "payment_method": "COD",
    "payment_status": "PENDING",
    "estimated_delivery_at": "2026-10-12T14:40:00+00:00",
    "scheduled_for": null,
    "restaurant_id": "…",
    "restaurant_name": "…",
    "placed_at": "2026-10-12T14:03:07.123456+00:00"
  }
}
```

### 3.2 Customer and rider: `/ws/orders/{order_id}/live-tracking`

The first frame after connecting is always a snapshot, so a screen opened
mid-delivery can draw the map at once:

```json
{
  "type": "tracking.snapshot",
  "order_id": "7b0c…",
  "status": "PICKED_UP",
  "eta_minutes": 12,
  "rider_location": {
    "latitude": 23.7936,
    "longitude": 90.4064,
    "heading": 47,
    "speed_kph": 21.5,
    "updated_at": "2026-10-12T14:20:03.512000Z"
  },
  "live_tracking_available": true
}
```

| `type` | When | Fields |
|---|---|---|
| `tracking.snapshot` | Once, right after connecting | `order_id`, `status`, `eta_minutes` (null unless READY or PICKED_UP), `rider_location` (null when unknown), `live_tracking_available` |
| `rider.location` | About every 5 s while the order is READY or PICKED_UP and the rider app is reporting | `order_id`, `status`, `latitude`, `longitude`, `heading` (degrees from north, may be null), `speed_kph` (may be null), `recorded_at` |
| `order.status` | The order changed status | See §3.3 |
| `order.rider_assigned` | A rider accepted the order, or support assigned one | `order_id`, `order_number`. Call `GET /orders/{id}/tracking` for the rider's name, photo and vehicle |
| `chat.message` | Anyone on the order sent a chat message | `message`: `id`, `order_id`, `sender_role`, `sender_name`, `body`, `created_at`, `read_at` (see §3.5) |

`live_tracking_available: false` means nobody has heard from the rider
recently. Keep the socket open and keep the last known state; do not move the
dot. Positions resume with the next `rider.location` frame.

### 3.3 `order.status` — on both the vendor and tracking sockets

```json
{"type": "order.status", "order_id": "…", "status": "READY", "order_number": 1042}
```

Plus the extra field for that event:

| What happened | `status` | Extra field |
|---|---|---|
| Vendor accepted | `PREPARING` | `order_number` |
| Vendor rejected | `CANCELLED` | `order_number` |
| Vendor did not accept within 15 minutes | `CANCELLED` | `order_number` |
| Customer cancelled | `CANCELLED` | `cancelled_by: "CUSTOMER"` |
| Support cancelled | `CANCELLED` | `cancelled_by: "ADMIN"` |
| Vendor marked the food ready | `READY` | `order_number` |
| Vendor verified the rider's PIN | `PICKED_UP` | `picked_up_at` |
| Rider (or support) marked it delivered | `DELIVERED` | `delivered_at` |

### 3.4 Rider: `/ws/rider/offers`

One shared feed for every rider. Load the current list with `GET /rider/offers`
when the socket opens, then apply these frames to it:

| `type` | When | Fields |
|---|---|---|
| `offer.new` | A restaurant accepted an order that needs a rider | `order_id`, `order_number`, `restaurant_name`, `restaurant_latitude`, `restaurant_longitude`, `earning`, `delivery_type` (`STANDARD` or `PRIORITY`) |
| `offer.ready` | The food is ready and still has no rider | Same fields as `offer.new` |
| `offer.taken` | A rider accepted it, or support assigned one | `order_id`, `rider_id`. Remove the card |

An `offer.new` or `offer.ready` frame for an order already in the list should
update that card, not add a second one.

### 3.5 Parsing notes

- **Money is a string**: `grand_total` and `earning` arrive as `"350.00"`, like
  the REST API.
- **Timestamps are ISO 8601 in UTC**, with either a `Z` or a `+00:00` offset
  (`2026-10-12T14:20:03Z`, `2026-10-12T14:03:07.123456+00:00`). Dart's
  `DateTime.parse` and JavaScript's `new Date()` read both.
- **A `chat.message` frame has no `is_mine`**, because every party on the order
  receives the same frame. Compare `message.sender_role` (`CUSTOMER`, `RIDER`,
  `VENDOR`, `ADMIN`) with your own role to pick the side of the thread.
- **The sender gets their own chat message back** over the socket. Dedupe by
  `message.id`; the `POST /orders/{id}/messages` response already contains it.

---

## 4. What the app sends

Nothing. The sockets are listen-only and the server ignores anything the app
writes to them. There is no subscribe message and no pong to send.

Every action stays on REST. Some of those calls are what make frames appear on
other screens:

| REST call | Frame it triggers |
|---|---|
| `POST /orders` | `order.placed` on the vendor socket |
| `POST /vendor/orders/{id}/accept` | `order.status` to vendor and customer, `offer.new` to riders |
| `POST /vendor/orders/{id}/ready` | `order.status` to vendor and customer, `offer.ready` to riders |
| `POST /rider/offers/{id}/accept` (or support assigns a rider) | `offer.taken` to riders, `order.rider_assigned` to vendor and customer |
| `POST /rider/location` | `rider.location` to the customer of each order the rider is carrying |
| `POST /orders/{id}/messages` | `chat.message` to vendor, customer and rider |

---

## 5. Staying connected

Assume the socket will drop: mobile networks and proxies cut connections
without a close frame. The app is responsible for noticing and reconnecting.

**When to hold each socket open**

- Vendor: the whole time the vendor app is in the foreground and logged in.
- Customer: while the Track Order or chat screen of an active order is open.
  Close it yourself once a `DELIVERED` or `CANCELLED` status arrives; the server
  keeps it open.
- Rider: `/ws/rider/offers` while on shift. The tracking socket for a job is
  optional; the rider app already knows its own position.

**Reconnect rules**

1. If no frame (not even a `ping`) has arrived for 60 seconds, treat the socket
   as dead. Close it and reconnect.
2. Back off between attempts: 1 s, 2 s, 4 s, up to 30 s, with a little random
   jitter. Reset after a successful connect.
3. If the handshake fails, refresh the access token once and try again. If it
   still fails, it is a 403: stop retrying and fall back to polling the REST
   endpoint.
4. After every successful connect, reload the screen from REST:
   `GET /vendor/orders`, `GET /orders/{id}` and `GET /orders/{id}/messages`, or
   `GET /rider/offers`. Frames sent while you were offline are not replayed.

**Socket versus push notification**

The socket only lives while the app is in the foreground; the OS closes it in
the background. Push notifications (FCM) cover the background case for new
orders, status changes, delivery offers and chat messages — register the device
with `POST /users/me/devices` ([APP-SHARED-API.md](APP-SHARED-API.md) §2). When
the app comes back to the foreground, reconnect and reload from REST. While the
socket is live, the app can choose to hide the system banner for a push that
the screen is already showing.

---

## 6. Example code

Any standard WebSocket client works; no Socket.IO library is needed.

### 6.1 Flutter (`web_socket_channel`)

```dart
final uri = Uri.parse(
  'wss://api.cheeringshop.online/api/v1/ws/orders/$orderId/live-tracking',
).replace(queryParameters: {'token': accessToken});

final channel = WebSocketChannel.connect(uri);
try {
  await channel.ready; // throws when the server refuses the handshake (403)
} catch (_) {
  return scheduleReconnect();
}

channel.stream.listen(
  (raw) {
    final frame = jsonDecode(raw as String) as Map<String, dynamic>;
    switch (frame['type']) {
      case 'tracking.snapshot':
        drawMap(frame);
      case 'rider.location':
        moveRider(frame['latitude'], frame['longitude'], frame['heading']);
      case 'order.status':
        setStatus(frame['status']);
      case 'order.rider_assigned':
        reloadTracking(); // GET /orders/{id}/tracking
      case 'chat.message':
        addMessage(frame['message']); // dedupe by id, use sender_role
    }
  },
  onDone: scheduleReconnect, // also fires when the connection drops
  onError: (_) => scheduleReconnect(),
);
```

### 6.2 Testing by hand

1. Log in as a vendor and copy the `access_token`.
2. Connect with Postman (New → WebSocket) or from a terminal:
   `websocat "wss://api.cheeringshop.online/api/v1/ws/vendor/live?token=<access_token>"`.
3. Place an order for that restaurant from the customer app. An `order.placed`
   frame appears. Accept it and an `order.status` frame with `PREPARING`
   follows.
4. Leave it idle: a `{"type":"ping"}` arrives every 25 seconds.
5. A connection that fails straight away means the token or the account is
   wrong for that endpoint (see §2).
