# Admin console

A minimal browser app for administrators, served by the API itself at
**`/admin/`** (for example `http://localhost:8000/admin/` locally, or
`https://api.cheeringshop.online/admin/` in production). There is no build
step: it is three static files in `app/static/admin/` and it calls `/api/v1`
on the same origin, so it needs no CORS entry and ships inside the existing
Docker image.

## What it does today

One job: **approving vendors after they register.** Both registration paths are
covered, one tab each.

| Tab | Backed by | Actions |
|---|---|---|
| Vendor applications | `GET /admin/vendor-applications?status=` | Review the full form (business, owner, documents, payout), then `approve` or `reject` with a note. Rejection requires a note because it is emailed to the applicant. Filter by Pending / Approved / Rejected. |
| Restaurants awaiting approval | `GET /admin/restaurants/pending` | Restaurants created through the fast path (`role: "VENDOR"` at sign-up). Approve with `POST /admin/restaurants/{id}/verify`. |

## Signing in

Use an `ADMIN` account. Create one on the server with:

```bash
.venv/bin/python scripts/create_admin.py
```

The login form handles the 2FA challenge if the admin has enabled it. A
non-admin account is refused client-side after login and never reaches the
console. The access token is held in `sessionStorage` for the tab's lifetime;
there is no refresh flow yet, so after the token expires you sign in again.

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
4. **Check.** `https://admin.cheeringshop.online/` shows the sign-in form;
   `https://admin.cheeringshop.online/health` returns the API health JSON;
   `https://api.cheeringshop.online/` still 404s and `/admin/` there still
   works.

On the bare-metal Caddy deployment the same variable feeds Caddy's site block
(`ADMIN_DOMAIN`), so setting `ADMIN_UI_HOST` in `.env` is enough there too.

## Adding to it

- Add screens by editing `index.html` / `admin.js`; every admin endpoint is
  listed under **[EXTENDED]** in `app/api/v1/endpoints/admin.py` (riders,
  payouts, commission).
- Keep scripts and styles in files, not inline. The console runs under a
  Content-Security-Policy of `default-src 'self'` (see
  `SecurityHeadersMiddleware`), so inline `<script>` blocks and `onclick=`
  handlers will not execute. `tests/test_admin_app.py` guards this.
- Any new mount outside `/api/v1` must be added to `INFRA_PATHS` in
  `tests/test_route_inventory.py`, or the inventory test will flag it as an
  undocumented endpoint.
