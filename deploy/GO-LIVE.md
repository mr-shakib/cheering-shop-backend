# Go Live — CR Shop Backend on Hostinger VPS + Dokploy

A click-by-click walkthrough from nothing deployed to a working HTTPS API.
**No domain purchase required.**

**Total time: ~35 minutes**, most of it waiting for a Docker build.

> **About the Dokploy screenshots-in-words:** I describe Dokploy's standard
> Compose flow. Button labels move slightly between versions. If a screen does
> not match, the *intent* of each step is stated in bold — find the equivalent
> control and carry on.

---

## Contents

| Part | What you do | Where | Time |
|---|---|---|---|
| [0](#part-0--before-you-start) | Collect what you need | — | 2 min |
| [1](#part-1--get-a-hostname-free) | Get a free hostname | Terminal / duckdns.org | 5 min |
| [2](#part-2--put-the-code-on-github) | Push the code | Your computer | 5 min |
| [3](#part-3--generate-your-secrets) | Generate secrets | Your computer | 1 min |
| [4](#part-4--dokploy-create-the-application) | Create the app | Dokploy UI | 3 min |
| [5](#part-5--dokploy-environment-variables) | Paste env vars | Dokploy UI | 2 min |
| [6](#part-6--dokploy-domain--https) | Attach domain + TLS | Dokploy UI | 2 min |
| [7](#part-7--deploy) | Deploy | Dokploy UI | 10 min |
| [8](#part-8--verify-it-actually-works) | Verify | Terminal | 3 min |
| [9](#part-9--backups) | Schedule backups | Dokploy UI | 2 min |
| [10](#part-10--after-go-live-checklist) | Final checklist | — | 2 min |

---

## Part 0 — Before you start

Have these ready. Write them on a scratch pad; you will need them repeatedly.

- [ ] **VPS public IP address** — Hostinger hPanel → **VPS** → your server →
      shown at the top of the overview page. Looks like `72.60.x.x`.
- [ ] **SSH access to the VPS** — confirm now, not later:
      ```bash
      ssh root@YOUR_VPS_IP
      ```
      (or `ssh youruser@YOUR_VPS_IP` if you already made a user)
- [ ] **Dokploy admin URL and login** — usually `http://YOUR_VPS_IP:3000`.
      Confirm you can sign in.
- [ ] **A GitHub account.**
- [ ] The project on your computer at
      `/home/mr-nacht/Workspace/CR Shop/backend`.

**Notation used below**

- `YOUR_VPS_IP` → replace with your actual IP, e.g. `72.60.12.34`
- `YOUR_HOST` → replace with the hostname you get in Part 1
- Lines starting `$` are run **on your own computer**
- Lines starting `#` are run **on the VPS over SSH**

---

## Part 1 — Get a hostname (free)

**Why you need this:** Let's Encrypt issues certificates for *names*, never for
bare IP addresses. `https://72.60.12.34` cannot exist. A free hostname gets you
real HTTPS at no cost.

**Why not just any free hostname:** Let's Encrypt allows **50 certificates per
registered domain per week**, and uses the
[Public Suffix List](https://publicsuffix.org/) to decide what "registered
domain" means.

| Service | On the PSL? | Gets a certificate? |
|---|---|---|
| `srvXXXXXX.hstgr.cloud` (Hostinger's own) | yes | **yes — try first** |
| `yourname.duckdns.org` | yes | **yes** |
| `<ip>.sslip.io`, `<ip>.nip.io` | **no** | **no** |

`sslip.io` and `nip.io` resolve fine, but because they are not PSL-listed, every
subdomain worldwide shares one 50/week budget that is permanently exhausted.
Certificate issuance will fail. Do not use them for HTTPS.

### Option 1A — Hostinger's built-in hostname (try this first)

SSH into your VPS and run:

```bash
# on the VPS
hostname -f
dig +short "$(hostname -f)"
```

**What you want to see:**

```
srv123456.hstgr.cloud       <- from the first command
72.60.12.34                 <- from the second, matching YOUR_VPS_IP
```

If the second line equals your VPS IP, **you are finished with Part 1**. Your
`YOUR_HOST` is `srv123456.hstgr.cloud`. Skip to Part 2.

> `dig: command not found`? Install it: `apt-get install -y dnsutils`, then retry.

If the second command prints nothing, or an IP that is not yours, use Option 1B.

### Option 1B — DuckDNS (2 minutes)

1. In your browser go to **<https://www.duckdns.org>**
2. Click **sign in with GitHub** (top of the page). Authorise it.
3. You land on your dashboard. Find the box labelled **sub domain** near the
   middle of the page.
4. Type a name, e.g. `crshop-api`, then click the **add domain** button beside
   it.
5. Your new domain appears in the table below as `crshop-api.duckdns.org`.
6. In that row, find the **current ip** field. Replace whatever is there with
   `YOUR_VPS_IP`, then click **update ip** at the end of the row.
7. Confirm it worked — from your own computer:

   ```bash
   $ dig +short crshop-api.duckdns.org
   ```

   Must print your VPS IP. If it prints nothing, wait 60 seconds and retry.

Your `YOUR_HOST` is `crshop-api.duckdns.org`.

---

## Part 2 — Put the code on GitHub

**Why:** Dokploy's Compose deployments pull from a Git repository.

The repository is already initialised locally with two commits and verified to
contain no secrets — you only need to push it.

### 2.1 — Create the remote and push

**With the GitHub CLI** (easiest):

```bash
$ cd "/home/mr-nacht/Workspace/CR Shop/backend"
$ gh auth login          # only if you have never used gh here
$ gh repo create cr-shop-backend --private --source=. --push
```

**Without the GitHub CLI:**

1. Browser → **<https://github.com/new>**
2. **Repository name**: `cr-shop-backend`
3. Select **Private**
4. Leave *"Add a README"*, *".gitignore"* and *"license"* all **unchecked** —
   the repo already has content and those would cause a conflict.
5. Click **Create repository**
6. Back in your terminal:

   ```bash
   $ cd "/home/mr-nacht/Workspace/CR Shop/backend"
   $ git remote add origin https://github.com/YOUR_GITHUB_USERNAME/cr-shop-backend.git
   $ git branch -M main
   $ git push -u origin main
   ```

### 2.2 — Confirm no secrets were published

```bash
$ git ls-files | grep -E '^\.env$|\.env\.production$' && echo "STOP: secrets pushed" || echo "clean"
```

Must print `clean`. If it prints `STOP`, tell me before continuing — the secrets
need rotating and the history rewriting.

### 2.3 — Connect GitHub to Dokploy

1. Browser → `http://YOUR_VPS_IP:3000` → sign in
2. Left sidebar → **Settings**
3. Tab → **Git Providers** (may be called *Git* or *Source Providers*)
4. Click **GitHub** → **Connect / Install GitHub App**
5. GitHub asks which repositories to grant access to. Choose **Only select
   repositories** → pick `cr-shop-backend` → **Install**
6. You are returned to Dokploy with GitHub shown as connected.

---

## Part 3 — Generate your secrets

**On your own computer:**

```bash
$ cd "/home/mr-nacht/Workspace/CR Shop/backend"
$ ./deploy/gen-env.sh YOUR_HOST
```

Example: `./deploy/gen-env.sh crshop-api.duckdns.org`

It prints a complete environment block. **Copy the whole thing** — from
`POSTGRES_USER=` down to `FORWARDED_ALLOW_IPS=...`. You will paste it in Part 5.

### Save `TOTP_ENCRYPTION_KEY` somewhere permanent right now

Password manager, or an encrypted note. It encrypts users' stored 2FA secrets.
**It cannot be rotated in place** — changing it makes every enrolled user's 2FA
undecryptable and locks them out of their own accounts.

> Never paste this block into a chat, an issue, or a commit. Each value is a
> live production credential.

---

## Part 4 — Dokploy: create the application

1. Browser → `http://YOUR_VPS_IP:3000`
2. Left sidebar → **Projects**
3. Click **Create Project** (top right)
   - **Name**: `cr-shop`
   - **Description**: `Food delivery backend`
   - Click **Create**
4. Click into the `cr-shop` project you just made
5. Click **Create Service** → choose **Compose**
   *(not "Application" — Application builds a single container; this stack has
   four services)*
   - **Name**: `backend`
   - Click **Create**

**You are now on the service page.** The tabs across the top — *General*,
*Environment*, *Domains*, *Deployments*, *Logs* — are where Parts 4–7 happen.

### 4.1 — Point it at your repository

On the **General** tab:

| Field | Value |
|---|---|
| Provider / Source Type | **GitHub** |
| Repository | `YOUR_GITHUB_USERNAME/cr-shop-backend` |
| Branch | `main` |
| Compose Path | `./deploy/docker-compose.dokploy.yml` |

Click **Save**.

> **Compose Path is the field people get wrong.** It must be exactly
> `./deploy/docker-compose.dokploy.yml`. Not `docker-compose.yml` (that is the
> development file, which publishes database ports to the internet) and not
> `docker-compose.prod.yml` (that one runs Caddy, which will collide with
> Dokploy's Traefik on ports 80/443).

---

## Part 5 — Dokploy: environment variables

1. On the same service page, click the **Environment** tab
2. Paste the entire block you generated in Part 3 into the large text area
3. Click **Save**

### Check these three lines before saving

| Variable | Must be | Why |
|---|---|---|
| `ENVIRONMENT` | `production` | Hides `/docs`, stops OTP codes appearing in API responses, suppresses version strings on the health endpoint |
| `CORS_ORIGINS` | `https://YOUR_HOST` | Browsers block your frontend otherwise |
| `FORWARDED_ALLOW_IPS` | `172.16.0.0/12` | Lets the app see real client IPs through Traefik. Wrong value = every user shares one rate-limit bucket |

`ENABLE_DOCS=true` is included so your frontend team can browse the interactive
API docs while integrating. **Change it to `false` before real users exist** —
it publishes your entire API surface to anyone who finds the URL.

---

## Part 6 — Dokploy: domain + HTTPS

1. Click the **Domains** tab
2. Click **Add Domain**
3. Fill in:

| Field | Value | Notes |
|---|---|---|
| Host | `YOUR_HOST` | from Part 1, no `https://`, no trailing slash |
| Path | `/` | |
| Service Name | `api` | **must be `api`** — not `backend`, not `web` |
| Container Port | `8000` | **must be 8000** |
| HTTPS | **on** | |
| Certificate Provider | **Let's Encrypt** | |

4. Click **Create** / **Save**

> **Service Name = `api` and Port = `8000` are the two most common mistakes.**
> Anything else gives you a Traefik 404 or 502 with no useful error message.
> `api` is the service name inside `docker-compose.dokploy.yml`; 8000 is the
> port uvicorn listens on inside the container.

Let Dokploy generate the Traefik routing labels. Do not hand-write them.

---

## Part 7 — Deploy

1. Return to the **General** tab (or **Deployments**)
2. Click **Deploy**
3. Click the **Logs** / **Deployments** tab and watch

**First deploy takes 5–10 minutes** — it downloads the Python base image, builds
your image, pulls PostGIS and Redis, then issues a TLS certificate. Later
deploys take under a minute because the layers are cached.

### What healthy output looks like, in order

Build:
```
Successfully built ...
```

API container starting — **this is the schema being created for you**:
```
==> Applying database migrations
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, initial schema
==> Starting: sh -c exec uvicorn app.main:app ...
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Worker container:
```
Starting worker for 4 functions: auto_decline_stale_orders, flush_rider_trail,
recompute_restaurant_rating, expire_idempotency_keys
```

When all four services show **running / healthy**, move on.

---

## Part 8 — Verify it actually works

Run these **from your own computer**, not the VPS — that proves the whole path
works: DNS → Traefik → TLS → container.

### 8.1 — Is it alive?

```bash
$ curl https://YOUR_HOST/health
```
```json
{"success":true,"data":{"status":"ok","environment":"production"}}
```

If `environment` says anything other than `production`, go back to Part 5.

### 8.2 — Can it reach the database and Redis?

```bash
$ curl https://YOUR_HOST/health/ready
```
```json
{"success":true,"data":{"status":"ready","database":{"status":"ok"},"redis":{"status":"ok"}}}
```

Version numbers are hidden on purpose — they are reconnaissance material for an
attacker. Seeing bare `"ok"` is correct.

### 8.3 — Is the certificate real?

```bash
$ curl -sI https://YOUR_HOST/health | head -1
```
Expect `HTTP/2 200`. A certificate error here means Part 1's DNS is wrong or the
certificate has not issued yet — wait two minutes and retry.

### 8.4 — Does the auth flow work end to end?

```bash
$ curl -X POST https://YOUR_HOST/api/v1/auth/otp/send \
    -H 'Content-Type: application/json' \
    -d '{"identifier":"you@example.com"}'
```
```json
{"success":true,"data":{"message":"OTP sent"}}
```

**There must be no `debug_code` field.** If you see one, `ENVIRONMENT` is not
`production` and you are leaking live OTP codes to anyone who calls the endpoint.

### 8.5 — Is brute-force protection live?

```bash
$ for i in $(seq 1 12); do
    curl -s -o /dev/null -w "%{http_code} " -X POST https://YOUR_HOST/api/v1/auth/login \
      -H 'Content-Type: application/json' \
      -d '{"identifier":"you@example.com","password":"WrongPassword1!"}'
  done; echo
```
```
401 401 401 401 401 401 401 401 401 401 429 429
```

Ten failures then `429` is correct. All `401` means rate limiting is not working
— tell me if you see that.

### 8.6 — Are the docs where you expect?

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" https://YOUR_HOST/docs
```

- `200` → docs are public (fine now, **turn off before real users**)
- `404` → docs hidden (`ENABLE_DOCS=false`)

### 8.7 — Is the database genuinely unreachable from outside?

```bash
$ nc -zv -w5 YOUR_HOST 5432
$ nc -zv -w5 YOUR_HOST 6379
```

**Both must fail** (`Connection refused` / timed out). Success on either means
something is publishing database ports to the internet — stop and tell me.

---

## Part 9 — Backups

Your data now matters. Set this up before you forget.

1. Dokploy → your `backend` service → **Schedules** tab (may be *Cron Jobs*)
2. Click **Create Schedule**
   - **Name**: `nightly-db-backup`
   - **Cron**: `15 3 * * *`  (03:15 daily)
   - **Command**: `/deploy/backup.sh`
   - **Service**: `postgres`
3. **Save**

If your Dokploy version has no Schedules tab, use a host cron instead:

```bash
# on the VPS
crontab -e
# add this line, adjusting the path to where Dokploy checked out the repo:
15 3 * * * /etc/dokploy/compose/cr-shop-backend/code/deploy/backup.sh >> /var/log/crshop-backup.log 2>&1
```

Find the real path with: `find /etc/dokploy -name backup.sh 2>/dev/null`

`backup.sh` dumps the database, **verifies the dump is readable**, copies it out,
and only then deletes anything older than 14 days — so a run of broken backups
can never eat your last good one.

### Do one restore drill now

A backup you have never restored is a hope, not a backup.

```bash
# on the VPS
CID=$(docker ps -qf name=postgres | head -1)
docker exec $CID psql -U crshop -d postgres -c "CREATE DATABASE restore_test;"
docker cp ~/backups/crshop-XXXXXX.dump $CID:/tmp/r.dump
docker exec $CID pg_restore -U crshop -d restore_test /tmp/r.dump
docker exec $CID psql -U crshop -d restore_test -c "\dt" | head -20
docker exec $CID psql -U crshop -d postgres -c "DROP DATABASE restore_test;"
```

You should see roughly 25 tables listed.

---

## Part 10 — After go-live checklist

- [ ] `TOTP_ENCRYPTION_KEY` saved in a password manager
- [ ] Restore drill completed successfully (Part 9)
- [ ] `ENABLE_DOCS=false` — **do this before any real user signs up**
- [ ] Off-site backup copies enabled (uncomment the `rclone` line in
      `deploy/backup.sh`); a backup on the same disk as the database does not
      survive a disk failure
- [ ] Give your frontend team the base URL: `https://YOUR_HOST/api/v1`
- [ ] Note that **only Auth works so far** — the other 35 endpoints return
      `501 NOT_IMPLEMENTED` by design, so the frontend can see their shapes but
      not their data yet

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `network dokploy-network not found` | Dokploy not installed, or its network is named differently | `docker network ls \| grep -i dokploy`, then update the network name at the bottom of `deploy/docker-compose.dokploy.yml` |
| Traefik **404** | Domain not attached, or wrong Service Name | Part 6 — Service must be `api` |
| Traefik **502** | Wrong container port, or the API is not running | Part 6 — Port must be `8000`; check the Logs tab |
| Certificate never issues | DNS not resolving yet | `dig +short YOUR_HOST` must return your VPS IP. Let's Encrypt blocks after 5 failures per hostname per hour — wait an hour |
| API restarts in a loop | A missing secret | Logs tab names the missing field. The app refuses to boot rather than run on a default key |
| `FATAL: sorry, too many clients already` | Pool size × workers exceeds `max_connections` | Lower `DB_POOL_SIZE` to `5` and redeploy |
| Everyone shares one rate-limit bucket | `FORWARDED_ALLOW_IPS` does not cover Traefik | `docker network inspect dokploy-network` to find the subnet |
| `debug_code` appears in OTP responses | `ENVIRONMENT` is not `production` | Part 5 |
| Build fails on `pip install` | Out of memory during build | `free -h`; the bare-metal bootstrap script adds 2 GB swap |
| Out of disk | Old images accumulating | `docker image prune -af` — **never** `--volumes`, that deletes your database |

---

## Appendix — what is actually running

```
                    internet
                       │
                       ▼  :80 / :443
              Traefik (Dokploy's, TLS terminates here)
                       │  dokploy-network
                       ▼
                 api  :8000          2 uvicorn workers
                       │             runs migrations on start
                       │  internal network (no internet access at all)
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  postgres:5432   redis:6379       worker
  PostGIS 16      queue + rider    arq: auto-decline,
  25 tables       positions        rating recompute
```

**Only Traefik is reachable from the internet.** Postgres, Redis and the worker
publish no ports and sit on a network marked `internal: true`, which has no
route out. That is architectural, not a firewall rule — which matters, because
Docker writes its own iptables rules that bypass `ufw` entirely.

### Memory budget on a KVM 2 (8 GB)

| Service | Roughly |
|---|---|
| Postgres | 2.0 GB |
| API (2 workers) | 1.0 GB |
| Worker | 0.3 GB |
| Redis | 0.4 GB |
| Dokploy + Traefik | 1.0 GB |
| **Free** | **~3 GB** |

Comfortable. If you later raise uvicorn `--workers`, lower `DB_POOL_SIZE` to
match or you will exhaust Postgres's 100 connections.
