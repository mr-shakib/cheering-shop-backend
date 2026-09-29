# Admin console

The browser app administrators run the platform from: every screen in
`admin_screen/`. The API serves it at **`/admin/`** (for example
`http://localhost:8000/admin/` locally, or
`https://api.cheeringshop.online/admin/` in production), and at the root of its
own subdomain when `ADMIN_UI_HOST` is set. It calls `/api/v1` on the same
origin, so it needs no CORS entry.

The source is `admin-web/`: React 19, TypeScript, Vite, Tailwind CSS 4,
TanStack Query, React Router, Recharts, and Leaflet with OpenStreetMap tiles.
The API documentation it is built against is [ADMIN-API.md](ADMIN-API.md).

## Running it

| Task | Command |
|---|---|
| Install dependencies (once) | `make admin-install` |
| Develop, with hot reload | `make run` in one terminal, `make admin-dev` in another, then open `http://localhost:5173/admin/`. Vite proxies `/api` to `:8000`. |
| Build what the API serves | `make admin-build`. Typechecks, then writes `app/static/admin/`, so `make run` serves it at `:8000/admin/`. |
| Deploy | Nothing extra. The Dockerfile's first stage builds the console with Node, and the image carries only the built files. |

`app/static/admin/` is build output and is gitignored. A checkout that has not
built the console still starts the API; `/admin/` answers 503 with the build
command until `make admin-build` has run.

Needs Node 20.19 or newer (the Docker stage uses Node 24).

## Signing in

Use an `ADMIN` account. Create the first one on the server with:

```bash
.venv/bin/python scripts/create_admin.py admin@example.com
```

After that, invite administrators from **Settings → Administrators**. The
invitation email links to the console's *Sign up for admin* screen
(`/accept-invite?token=…`); `ADMIN_INVITE_URL` must point there (see
[ADMIN-API.md §20](ADMIN-API.md#20-deployment-and-gaps)). In development the
invitation list offers **Copy link**, because the API returns the token there
when it is not running in production.

- The sign-in form handles the 2FA challenge if the admin has enabled it.
- A non-admin account is refused, and its tokens are revoked on the way out.
- **Remember me** keeps the session in `localStorage` across browser restarts;
  without it the session lasts as long as the tab (`sessionStorage`).
- The access token refreshes itself. Refreshes are serialised across tabs with
  a Web Lock, because the refresh token rotates and presenting a used one
  revokes the whole session.
- **Forgot password** is the three-step flow: email, 4-digit code, new
  password.

## What is where

| Sidebar | Screens |
|---|---|
| Overview | Stat cards, revenue chart, live orders, recent orders. Refreshes every 30 seconds. |
| Order | Every order with filters and CSV export. A row opens the order drawer: timeline, parties, money, and the Assign rider / Cancel / Refund / Confirm delivery actions the API enables for that order. |
| Customers | List and export; the details page blocks or unblocks the account. |
| Vendor → Active Vendors | List and export, **Add Vendor**, and the vendor profile: Store Info, Products (with **Add Product**), Order, Review, Withdrawal. **Edit** changes any field, including business hours and the map pin. The ⋮ menu sets commission, hides the store from discovery, or suspends/approves it. |
| Vendor → Application | The partner-application queue, and **Unverified stores**: fast-path sign-ups and suspended stores. |
| Vendor / Rider → Withdrawal | The payout queues: Mark Paid, Failed (money returns to the balance), Mark Unpaid. |
| Rider → Active Rider | Roster, **Add Rider**, and the rider profile: Personal Info, Earning, Order, Withdrawal. The ⋮ menu grants incentives, sets the sign-in password, takes the rider off shift, or blocks the account. |
| Rider → Application | Applications from the rider app; approving creates the account. |
| Product | Every product. The drawer edits it, sets its commission and category, and hides, features or deletes it. |
| Category | The Restaurant and Store chips. The **Needs review** filter is the queue of chips vendors created, which stay hidden until you approve or keep them hidden. The drawer edits, moves products between categories, and merges. See [CATEGORIES.md](CATEGORIES.md). |
| Support Ticket / Live Chat | The ticket queue, and the conversation with history, priority, resolve and close. An open conversation polls every 5 seconds; there is no push channel for the console. |
| Community / Reels | Post moderation and user bans; reels posted, hidden or deleted for any restaurant. |
| Finance | GMV, net, commission and delivery revenue for a period, the revenue split by service, and delivered-order transactions. |
| Advertisement / App Banners | Vendor promotions (pause, resume, end), and the image, GIF and Lottie banners the apps show. |
| Live Tracking | Riders on shift on a map, polled every 12 seconds. A rider without a recent position is listed without a pin. |
| Notification | Campaign history, and composing a notification to send now or schedule. |
| Settings | Platform settings (each card saves on its own), administrator invitations, change password, sign out. |

The top bar searches orders, customers, vendors and riders. The bell lists
what is waiting on an administrator: approvals, orders no rider has taken,
open and urgent tickets.

## Uploads

Images, documents, videos and Lottie files are uploaded straight from the
browser to R2 with `POST /admin/uploads/presigned-url`. Two things must be set
for that to work from a deployed console:

1. **The R2 settings** (`R2_*`, see [storage-setup-r2.md](storage-setup-r2.md)).
   The console's Content-Security-Policy lists the bucket's upload endpoint and
   public domain, derived from those settings, in `connect-src`.
2. **CORS on the bucket** allowing `PUT` from the console's origin (the API
   host, and the admin subdomain if you use one), with the `Content-Type`
   header. Without it the upload fails with "Could not reach the storage
   server".

## Security

The console runs under a Content-Security-Policy with no `unsafe-inline` or
`unsafe-eval` (`SecurityHeadersMiddleware.admin_ui_csp`):

- Scripts and styles are same-origin files; `index.html` may not contain
  inline script or style (`tests/test_admin_app.py` checks it).
- Images, videos and map tiles may come from any `https:` origin; the API and
  the storage origins are the only places it can send requests.
- Lottie banners use lottie-web's *light* build, which never evaluates code.
  The full build would need `unsafe-eval`.

`index.html` and other un-fingerprinted files are served `Cache-Control:
no-cache`, so a deploy takes effect on the next load. Files under `assets/`
have a content hash in their name and are cached for a year.

## Deploying on its own subdomain

The console needs no separate host. The API process serves it, so a subdomain
is one DNS record, one Dokploy domain and one environment variable:

1. **DNS.** Add an A record `admin.cheeringshop.online` → the VPS IP (the same
   IP as the API host). Wait until `dig +short admin.cheeringshop.online`
   answers before the next step, or Let's Encrypt validation fails.
2. **Dokploy.** Project → the compose service → **Domains → Add Domain**:

   | Field | Value |
   |---|---|
   | Host | `admin.cheeringshop.online` |
   | Service | `api` |
   | Container Port | `8000` |
   | HTTPS | on, Let's Encrypt |

   This is a second domain on the same `api` service, next to the existing
   API host. Do not create a new service.
3. **Environment.** In the same service's Environment tab add

   ```
   ADMIN_UI_HOST=admin.cheeringshop.online
   ```

   then **Deploy**. `AdminHostMiddleware` serves the console at `/` for
   requests carrying that Host header and leaves `/api/…` and `/health` alone,
   so the console talks to the API on its own origin. No CORS change.
4. **Check.** `https://admin.cheeringshop.online/` shows the sign-in form, and
   so does a reload on any console page, such as `/orders`;
   `https://admin.cheeringshop.online/health` returns the API health JSON;
   `https://api.cheeringshop.online/` still 404s and `/admin/` there still
   works.

On the bare-metal Caddy deployment the same variable feeds Caddy's site block
(`ADMIN_DOMAIN`), so setting `ADMIN_UI_HOST` in `.env` is enough there too.

## Adding to it

- A screen is a component under `admin-web/src/features/`, registered in
  `src/router.tsx` (each route is its own lazily loaded chunk) and linked from
  `src/components/layout/Sidebar.tsx`.
- API calls live in `admin-web/src/api/`, one module per area, typed from the
  Pydantic response models in `app/schemas/`. The endpoints do not declare
  response models in OpenAPI, so keep those types in step by hand when a
  schema changes.
- Shared UI is in `src/components/ui/`: tables, pagination, drawers, dialogs,
  the confirm dialog (use it for anything that moves money or reaches a user),
  file upload, the searchable picker, and badges. Status labels and colours for
  every API enum are in `src/lib/vocab.ts`.
- List filters live in the URL (`useListParams`), so a reload or a shared link
  keeps them.
- `npm run typecheck` in `admin-web/` checks types without building.
- Any new mount outside `/api/v1` must be added to `INFRA_PATHS` in
  `tests/test_route_inventory.py`, or the inventory test will flag it as an
  undocumented endpoint.
