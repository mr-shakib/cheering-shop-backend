# Shared app API: support, notifications, community

Features every app uses, whether customer, vendor or rider: help & support,
the notification inbox and push registration, the community feed, and
promoted-card tracking.

Base URL `…/api/v1`. Envelope `{"success": true, "data": {…}, "meta": {…}}`;
failures use `{"success": false, "error": {"code", "message", "details"}}`.
Everything except `POST /promotions/events` needs a signed-in user's access
token (any role except `ADMIN`).

---

## 1. Help & support

A user opens a ticket; support replies in the admin console; both sides write
in the same thread.

```http
POST /support/tickets
{
  "subject": "Rider was rude",
  "type": "RIDER_COMPLAINT",
  "message": "The rider was very rude when delivering my order.",
  "order_id": "…",
  "attachments": [{"url": "https://…/screenshot.png", "name": "screenshot.png"}]
}
```

- `type` is one of `ORDER_ISSUE`, `RIDER_COMPLAINT`, `VENDOR_COMPLAINT`,
  `PAYMENT`, `REFUND`, `ACCOUNT`, `OTHER`.
- `order_id` is optional, and must be an order you placed, delivered or
  cooked (`404` otherwise).
- Upload attachments first with `POST /uploads/presigned-url`, then send the
  `public_url` with a file name.

The response is the ticket with its `code` (`TCK-8800`, show it to the user)
and `messages`. Messages with `kind: "EVENT"` are history lines ("Ticket
created", "Marked resolved"); show them smaller, or not at all.

| Call | Use |
|---|---|
| `GET /support/tickets` | The user's tickets, most recent activity first. `unread: true` means support replied since the user last looked. |
| `GET /support/tickets/{id}` | One thread. Opening it clears `unread`. |
| `POST /support/tickets/{id}/messages` `{"body", "attachments"}` | Reply |

`status` is `OPEN` (waiting on support), `PENDING` (support replied; waiting
on you), `RESOLVED` or `CLOSED`. Replying to a `RESOLVED` ticket reopens it. A
`CLOSED` ticket refuses replies with `409`; open a new ticket. Poll the open
thread every few seconds while it is on screen.

## 2. Notifications

**The inbox.** Everything the platform sends lands here, whether or not the
phone received a push.

| Call | Use |
|---|---|
| `GET /notifications` | Newest first. `meta.unread` is the badge count. Each item has `title`, `message`, `type` (`PROMOTION`, `ALERT`, `UPDATE`), `is_read`. |
| `POST /notifications/{id}/read` | Mark one read when opened |
| `POST /notifications/read-all` | Clear the badge |

**Push.** Register the device's Firebase Cloud Messaging token after sign-in,
and again whenever Firebase issues a new one:

```http
POST /users/me/devices
{"fcm_token": "…", "platform": "ANDROID"}
```

`platform` is `IOS`, `ANDROID` or `WEB`. Calling it again with the same token
is harmless. On sign-out, call `DELETE /users/me/devices/{fcm_token}` so the
next person on the phone does not get your notifications.

A push carries `data.campaign_id` and `data.type`. Tapping it should open the
inbox.

## 3. Community

Short posts about food and places.

| Call | Use |
|---|---|
| `GET /community/posts` | The feed, newest first. Each post has `author`, `body`, `image_urls`, `restaurant` (tag, optional), `is_mine`, `reported_by_me`. |
| `POST /community/posts` `{"body", "image_urls"?, "restaurant_id"?}` | Post. Up to 4 images, uploaded first via `/uploads/presigned-url`. |
| `DELETE /community/posts/{id}` | Delete your own post |
| `POST /community/posts/{id}/report` `{"reason"?}` | Report a post. Once per user; you cannot report your own. |

Removed posts disappear from the feed. A user banned by the platform can no
longer post or use the app at all.

## 4. Promoted cards (customer app)

The home feed's `promoted` row shows restaurants running a promotion. Report
which of those cards were shown and which were tapped. The counts appear on
the admin Advertisement screen:

```http
POST /promotions/events
{"impressions": ["<restaurant id>", "…"], "clicks": ["<restaurant id>"]}
```

No sign-in needed. Batch the events and send them every few seconds rather
than once per card; up to 50 ids of each kind per call. A card shown twice in
one batch counts once.

---

## 5. Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/support/tickets` | user | Open a ticket |
| GET | `/support/tickets` | user | My tickets |
| GET | `/support/tickets/{id}` | user | One ticket and its thread |
| POST | `/support/tickets/{id}/messages` | user | Reply |
| GET | `/notifications` | user | My inbox, with the unread count |
| POST | `/notifications/{id}/read` | user | Mark one read |
| POST | `/notifications/read-all` | user | Mark all read |
| POST | `/users/me/devices` | user | Register for push |
| DELETE | `/users/me/devices/{token}` | user | Stop push to this device |
| GET | `/community/posts` | user | Community feed |
| POST | `/community/posts` | user | Post |
| DELETE | `/community/posts/{id}` | user | Delete my post |
| POST | `/community/posts/{id}/report` | user | Report a post |
| POST | `/promotions/events` | public | Promoted-card impressions and clicks |
