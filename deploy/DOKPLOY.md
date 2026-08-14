# Deploying CR Shop with Dokploy

> **Just want to deploy?** Follow **[GO-LIVE.md](GO-LIVE.md)** — a click-by-click
> walkthrough from nothing to a working HTTPS API, no domain purchase needed.
> This file is the reference behind it: why each choice was made, and what to do
> when something breaks.

Use this guide when **Dokploy is already installed** on the VPS. For a bare
Ubuntu box with nothing on it, use [README.md](README.md) instead.

> **Do not run both.** Dokploy runs Traefik on ports 80/443. The bare-metal
> compose file runs Caddy on the same ports, and only one process can bind a
> port — you would get `bind: address already in use`, and possibly break
> routing for anything Dokploy already serves. `docker-compose.dokploy.yml`
> deliberately contains **no reverse proxy and publishes no ports**.

---

## Why Dokploy rather than raw Ubuntu

It is already installed and holding 80/443, so raw compose is not an option
without uninstalling it. That aside, it genuinely earns its place here:

| | Dokploy | Raw compose |
|---|---|---|
| TLS certificates | Traefik, automatic | Caddy, automatic |
| Deploy on git push | Built in | `deploy.sh` by hand |
| Logs / metrics / rollback | Web UI | `docker logs`, no rollback |
| Env var management | Encrypted, in UI | a `chmod 600` file |
| Scheduled backups | Built in | cron + `backup.sh` |
| Non-terminal access | Yes | SSH only |

The last row matters more than it looks: a frontend teammate can check whether
the API is up without you handing out SSH keys.

---

## Step 1 — Point DNS

Create an **A record**: `api.yourdomain.com` → your VPS IPv4.

Do this before adding the domain in Dokploy. Let's Encrypt validates over HTTP,
so issuance fails until the name resolves — and Let's Encrypt rate-limits
**5 failures per hostname per hour**.

Verify: `dig +short api.yourdomain.com`

---

## Step 2 — Push the code to Git

Dokploy deploys from a repository. Locally:

```bash
git init
git add -A
git commit -m "Initial commit"
gh repo create cr-shop-backend --private --source=. --push
```

Private repo: Dokploy → **Settings → Git** → connect GitHub (or add a deploy
key).

**Confirm `.gitignore` is doing its job before you push** — `.env`,
`deploy/.env.production` and `.venv/` must never leave your machine:

```bash
git status --porcelain | grep -E '\.env|\.venv' && echo "STOP — secrets staged"
```

---

## Step 3 — Create the service in Dokploy

**Project → Create Service → Compose**

| Field | Value |
|---|---|
| Source | Your Git repository, branch `main` |
| Compose Path | `./deploy/docker-compose.dokploy.yml` |

Dokploy builds the image from the repo `Dockerfile` (the compose file sets
`context: ..`, which resolves to the repo root).

---

## Step 4 — Environment variables

Paste into Dokploy's **Environment** tab. Generate each secret separately with
`openssl rand -hex 32` — never reuse one value across two fields:

```env
POSTGRES_USER=crshop
POSTGRES_PASSWORD=<openssl rand -hex 32>
POSTGRES_DB=crshop
REDIS_PASSWORD=<openssl rand -hex 32>

ENVIRONMENT=production
DEBUG=false
ENABLE_DOCS=false
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

JWT_SECRET_KEY=<openssl rand -hex 32>
RIDER_PIN_PEPPER=<openssl rand -hex 32>
OTP_PEPPER=<openssl rand -hex 32>
TOTP_ENCRYPTION_KEY=<openssl rand -hex 32>

DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5
FORWARDED_ALLOW_IPS=172.16.0.0/12
```

**`TOTP_ENCRYPTION_KEY` cannot be rotated in place.** It encrypts stored 2FA
secrets; changing it makes every enrolled user's 2FA undecryptable and locks
them out of their accounts. Store a copy somewhere safe now.

**`ENABLE_DOCS=false`** hides `/docs`, `/redoc` and `/openapi.json`. Set it to
`true` only if your frontend team needs the interactive docs on this host —
it publishes your entire API surface to anyone who finds it.

---

## Step 5 — Attach the domain

**Service → Domains → Add Domain**

| Field | Value |
|---|---|
| Host | `api.yourdomain.com` |
| Service | `api` |
| Container Port | `8000` |
| HTTPS | on |
| Certificate | Let's Encrypt |

Let Dokploy generate the Traefik labels. Hand-writing them means guessing at the
label schema for whatever Traefik version Dokploy ships, and getting it subtly
wrong produces a 404 or 502 that is tedious to debug.

---

## Step 6 — Deploy

Hit **Deploy** and watch the log panel. Expect, in order:

```
==> Applying database migrations
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, initial schema
==> Starting: uvicorn ... --workers 2 --proxy-headers
INFO:     Uvicorn running on http://0.0.0.0:8000
```

and from the worker:

```
Starting worker for 4 functions: auto_decline_stale_orders, flush_rider_trail,
recompute_restaurant_rating, expire_idempotency_keys
```

The schema is created automatically — the API container runs
`alembic upgrade head` before uvicorn starts. Then:

```bash
curl https://api.yourdomain.com/health
curl https://api.yourdomain.com/health/ready
```

Expect `{"success":true,"data":{"status":"ready","database":{"status":"ok"},"redis":{"status":"ok"}}}`.
Dependency version strings are hidden outside local development on purpose —
they are reconnaissance material.

---

## Step 7 — Backups

Dokploy has scheduled database backups in the UI, but they target databases
Dokploy manages. Postgres here lives inside your compose stack, so use the
script instead — **Service → Schedules** (or a host cron):

```
15 3 * * *   /path/to/repo/deploy/backup.sh
```

`backup.sh` dumps, **verifies the dump is readable**, copies it out, and only
then prunes anything older than 14 days — so a run of failing backups can never
delete your last good one. Uncomment its `rclone` line to copy off-box; a backup
on the same disk as the database does not survive the failure you are insuring
against.

**Alternative:** move Postgres to a Dokploy-managed database service to get
backup scheduling in the UI. If you do, set the image to `postgis/postgis:16-3.4`
— a plain `postgres` image lacks PostGIS and migration 0001 will fail outright.

---

## Deploying without your own domain

Let's Encrypt will not issue a certificate for a bare IP address, so
`https://203.0.113.5` is not achievable. You do not need to buy a domain
though — you need a *hostname*, and there are free ones that work properly.

### Why not just any free hostname

Let's Encrypt limits **50 certificates per registered domain per week**, and it
uses the [Public Suffix List](https://publicsuffix.org/) to decide what counts
as a "registered domain". That single fact decides which free services work:

| Hostname service | On PSL? | Usable for HTTPS |
|---|---|---|
| `srvXXXXXX.hstgr.cloud` (Hostinger's own) | **yes** | **yes — best option** |
| `yourname.duckdns.org` | **yes** | **yes** |
| `yourname.dynv6.net` | yes | yes |
| `<ip>.sslip.io` | no | **no** — shares one global quota |
| `<ip>.nip.io` | no | **no** — shares one global quota |

`sslip.io` and `nip.io` resolve perfectly well, and are fine for plain HTTP. But
because they are not PSL-listed, every subdomain on earth shares one 50/week
certificate budget, which is permanently exhausted. Issuance will fail.

### Option A — Hostinger's free hostname (try this first)

Every Hostinger VPS is assigned one, and `hstgr.cloud` is PSL-listed, so it just
works. On the server:

```bash
hostname -f                      # e.g. srv123456.hstgr.cloud
dig +short "$(hostname -f)"      # must print your VPS's public IP
```

If the second command returns your IP, use that hostname in Dokploy and you are
done — no signup, no DNS to configure.

### Option B — DuckDNS (2 minutes, free)

1. Open <https://www.duckdns.org> and sign in with GitHub/Google.
2. Type a subdomain, e.g. `crshop-api`, and click **add domain**.
3. Put your VPS's IPv4 in the **current ip** box, click **update ip**.
4. Verify from anywhere: `dig +short crshop-api.duckdns.org`

You now have `crshop-api.duckdns.org` pointing at the server, and Let's Encrypt
will issue for it.

### Option C — plain HTTP, no certificate (last resort)

Add the domain in Dokploy with **HTTPS off**, using `<your-ip>.sslip.io`.

**Understand what you are accepting.** Without TLS, every request is readable by
anyone on the path: passwords, OTP codes, JWT access tokens, delivery addresses,
phone numbers. Anyone on the same network as a user can copy a token and become
that user.

Acceptable for: a frontend team integrating against a throwaway backend.
Not acceptable for: any real user account, any real address, any real phone
number. Treat the database as public and wipe it before you go live.

If you take this path, still set `ENVIRONMENT=production` — it keeps `/docs`
hidden and OTP codes out of responses. The missing TLS is the only compromise;
do not stack more on top of it.

### Moving to a real domain later

Nothing needs rebuilding:

1. Point the new domain's A record at the VPS.
2. Dokploy → Service → **Domains** → add the new host (keep the old one during
   the switchover so nothing breaks mid-flight).
3. Update `CORS_ORIGINS` to the new front-end origin and redeploy.
4. Update the base URL in the mobile/web clients.
5. Remove the temporary domain once traffic has moved.

Because JWTs are signed, not tied to a hostname, existing sessions survive the
change.

---

## How the networking works

```
internet → Traefik (Dokploy, :80/:443)
              │  dokploy-network
              ▼
           api :8000 ──────┐
                           │  internal (internal: true, no egress)
                    postgres:5432   redis:6379   worker
```

- **`api` joins two networks**: `internal` to reach Postgres and Redis, and
  `dokploy-network` so Traefik can route to it. Omit the second and Traefik
  returns 502.
- **`worker` joins only `internal`** — it serves no HTTP and must not be
  routable from outside.
- **Nothing publishes a host port.** Postgres and Redis are unreachable from the
  internet by construction, not by firewall rule. This matters because Docker
  writes iptables rules that **bypass ufw** — a published `5432:5432` would be
  world-reachable even with a deny-all firewall.

---

## Verified before publishing

This exact compose file was brought up locally against the real images, with a
stand-in `dokploy-network`:

- `docker compose config` valid; **no service publishes a host port**
- API migrated an empty database on start and reported healthy
- Worker started and registered all 4 arq tasks
- From a container on `dokploy-network` (standing in for Traefik):
  `http://api:8000/health` → `{"success":true,...,"environment":"production"}`
  and `/health/ready` → database + redis `ok`
- From that same network, `postgres:5432` **failed to resolve** — confirming the
  database is not reachable from the routable network
- `/docs` returned **404** with `ENABLE_DOCS=false`

---

## Troubleshooting

**`network dokploy-network declared as external, but could not be found`** —
Dokploy is not installed, or its network has a different name. Check:
`docker network ls | grep -i dokploy`, and update the network name at the bottom
of `docker-compose.dokploy.yml` to match.

**Traefik returns 502** — the `api` service is not on `dokploy-network`, or the
domain points at the wrong container port. It must be **8000**.

**Certificate never issues** — DNS is not resolving to this server yet, or ports
80/443 are blocked upstream. `dig +short api.yourdomain.com` must return your
VPS IP.

**API restarts in a loop** — almost always a missing secret. The app refuses to
boot rather than run on a default key; the log names the missing field.

**`FATAL: sorry, too many clients already`** — workers × pool size exceeded
`max_connections`. 2 workers × (10 + 5) + worker ≈ 35 of 100. If you raise
`--workers`, lower `DB_POOL_SIZE`.

**Every user shares one rate-limit bucket** — `FORWARDED_ALLOW_IPS` does not
cover Traefik's address, so the app sees Traefik's IP for every request. Check
Traefik's subnet with `docker network inspect dokploy-network`.
