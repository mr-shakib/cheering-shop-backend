# Deploying CR Shop to a Hostinger KVM 2 VPS

Target: **2 vCPU · 8 GB RAM · ~100 GB NVMe**, Ubuntu 24.04 LTS.

## Which guide do I follow?

| Your server | Use | Compose file |
|---|---|---|
| **Dokploy already installed** | [DOKPLOY.md](DOKPLOY.md) | `docker-compose.dokploy.yml` |
| Bare Ubuntu, nothing installed | this file | `docker-compose.prod.yml` |

**They are mutually exclusive.** Dokploy runs Traefik on ports 80/443; the bare
setup runs Caddy on the same ports. Only one process can bind a port, so running
both fails with `bind: address already in use` — and can break routing for
anything Dokploy is already serving. If Dokploy is installed, do not use this
file.

Everything runs in Docker on one host: Caddy (TLS) → API → Postgres/PostGIS +
Redis, plus a background worker. Only Caddy is reachable from the internet.

> **Why self-hosted Postgres:** Hostinger offers no managed PostgreSQL with
> PostGIS. That is fine — it actually removes the biggest deployment risk, since
> the `postgis/postgis:16-3.4` image guarantees PG16 + `postgis` + `citext` +
> `pg_trgm`, which this schema requires.

---

## Phase 0 — Before you touch the server

**Buy/point a domain.** Create a DNS **A record** for `api.yourdomain.com` →
your VPS IPv4 address. Do this first: Caddy proves domain ownership over HTTP to
get a certificate, and it will fail until DNS resolves. Propagation is usually
minutes.

**Have an SSH key.** If you don't:

```bash
ssh-keygen -t ed25519 -C "crshop-deploy"
```

Paste the public key into Hostinger's panel when creating the VPS (**hPanel →
VPS → Create → SSH Keys**), and choose the **Ubuntu 24.04** template.

---

## Phase 1 — Harden the server (once)

```bash
ssh root@YOUR_VPS_IP

# Copy the repo up first, or clone it — see Phase 2 for both options.
bash deploy/bootstrap-vps.sh deploy
```

`bootstrap-vps.sh` installs Docker, creates a non-root `deploy` user, configures
ufw (22/80/443 only), enables fail2ban and unattended security upgrades, adds
2 GB swap, and caps Docker log sizes.

> **Do not close this terminal yet.** The script disables root login and password
> auth. Open a *second* terminal and confirm `ssh deploy@YOUR_VPS_IP` works
> before you disconnect — otherwise a typo locks you out of your own server.

**A thing that surprises people:** Docker writes its own iptables rules that
**bypass ufw**. A container publishing `5432:5432` is exposed to the whole
internet even with a "deny all" firewall. This is why `docker-compose.prod.yml`
publishes **no** database ports — the protection is architectural, not a rule.

---

## Phase 2 — Get the code onto the server

**Option A — Git (recommended).** Locally:

```bash
git init && git add -A && git commit -m "Initial commit"
gh repo create cr-shop-backend --private --source=. --push
```

Then on the server, as `deploy`:

```bash
git clone git@github.com:YOU/cr-shop-backend.git ~/cr-shop
```

**Option B — rsync** (no repo yet). From your machine:

```bash
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.env' \
      --exclude '.pytest_cache' --exclude '.ruff_cache' \
      ./ deploy@YOUR_VPS_IP:~/cr-shop/
```

Option A is worth the ten minutes: `deploy.sh` does `git pull`, and without
version control you have no rollback.

---

## Phase 3 — Configure secrets

On the server:

```bash
cd ~/cr-shop
cp deploy/env.production.example deploy/.env.production

# Generate four DIFFERENT secrets — never reuse one value across fields
for k in JWT_SECRET_KEY RIDER_PIN_PEPPER OTP_PEPPER TOTP_ENCRYPTION_KEY \
         POSTGRES_PASSWORD REDIS_PASSWORD; do
  echo "$k=$(openssl rand -hex 32)"
done

nano deploy/.env.production   # paste them in, set DOMAIN and ACME_EMAIL
chmod 600 deploy/.env.production
```

**`TOTP_ENCRYPTION_KEY` is not rotatable in place.** It encrypts stored 2FA
secrets; changing it makes every enrolled user's 2FA undecryptable and locks
them out. Back it up somewhere safe before you go live.

---

## Phase 4 — Launch

```bash
cd ~/cr-shop
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

First boot takes a few minutes (image build + certificate issuance). Watch:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production logs -f
```

The API container runs `alembic upgrade head` before starting, so the schema is
created automatically. Verify:

```bash
curl https://api.yourdomain.com/health
curl https://api.yourdomain.com/health/ready
```

Expect `{"success":true,"data":{"status":"ready","database":{"status":"ok"},"redis":{"status":"ok"}}}`.
Version strings are hidden outside local development, deliberately — they are
reconnaissance material.

---

## Phase 5 — Backups

```bash
crontab -e
# nightly at 03:15
15 3 * * * /home/deploy/cr-shop/deploy/backup.sh >> /home/deploy/backup.log 2>&1
```

`backup.sh` dumps, **verifies the dump is readable**, copies it out, and only
then prunes anything older than 14 days — so a run of failing backups can never
delete your last good one.

Uncomment the `rclone` line to copy off-box. A backup on the same disk as the
database does not survive the failure you are actually insuring against.

**Restore drill** (do this once, now, not during an incident):

```bash
CID=$(docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production ps -q postgres)
docker exec -i $CID psql -U crshop -d postgres -c "CREATE DATABASE restore_test;"
docker cp ~/backups/crshop-XXXX.dump $CID:/tmp/r.dump
docker exec $CID pg_restore -U crshop -d restore_test /tmp/r.dump
docker exec $CID psql -U crshop -d restore_test -c "\dt"
docker exec $CID psql -U crshop -d postgres -c "DROP DATABASE restore_test;"
```

---

## Day-to-day

| Task | Command |
|---|---|
| Deploy an update | `./deploy/deploy.sh` |
| Logs | `docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production logs -f api` |
| Status | `... ps` |
| Restart API | `... restart api` |
| psql shell | `docker exec -it $(... ps -q postgres) psql -U crshop -d crshop` |
| Resource use | `docker stats` |

`deploy.sh` backs up before deploying — a failed migration is much less
frightening when the data can be rolled back.

---

## Resource budget (8 GB)

| Service | Limit | Notes |
|---|---|---|
| Postgres | 3 GB | `shared_buffers=2GB`, `max_connections=100` |
| API (2 workers) | 2 GB | one worker per vCPU |
| Worker | 1 GB | arq |
| Redis | 768 MB | `maxmemory 512mb`, **noeviction** |
| Caddy | 256 MB | |
| **Total** | **~7 GB** | leaves ~1 GB for the OS + 2 GB swap |

Connection maths: 2 uvicorn workers × (`DB_POOL_SIZE` 10 + overflow 5) + the arq
worker ≈ **35 of 100** Postgres connections. If you raise `--workers`, lower
`DB_POOL_SIZE` to match or you will exhaust `max_connections`.

Redis uses **`noeviction` on purpose**: it holds the arq job queue as well as
live rider positions. Under an eviction policy, memory pressure would silently
delete queued jobs — including the 60-second vendor auto-decline tasks. Failing
a write loudly is much better than losing an order timeout.

---

## Verified before publishing

This stack was brought up locally against the real images, not just written:

- `docker compose config` valid; **only Caddy publishes ports** — postgres,
  redis, api and worker are internal-only, on a `internal: true` network with no
  egress
- API container migrated an empty database on start (33 tables, `0001_initial`)
  and reported healthy
- Worker started and registered all 4 arq tasks
- With `ENVIRONMENT=production`: `/docs` returns **404**, OTP responses carry no
  code, readiness hides dependency versions
- `backup.sh` produced a verified 108 KB dump which was **restored into a
  scratch database** — 33 tables, `alembic 0001_initial`
- A packaging bug was found and fixed this way: `packages = ["app"]` shipped
  only the top-level package, so the worker died with
  `ModuleNotFoundError: No module named 'app.workers'` while the API looked
  perfectly healthy (uvicorn adds the working directory to `sys.path`; arq does
  not). Now `[tool.setuptools.packages.find] include = ["app*"]`.

---

## Troubleshooting

**Caddy won't get a certificate.** DNS must resolve to this server *before*
Caddy starts: `dig +short api.yourdomain.com`. Ports 80 and 443 must be open.
Let's Encrypt rate-limits 5 failures per hostname per hour — uncomment the
`acme_ca` staging line in the `Caddyfile` while debugging.

**API restarts in a loop.** Almost always a missing secret; the app refuses to
boot rather than run on a default key. `... logs api | tail -30`.

**`FATAL: sorry, too many clients already`.** Workers × pool size exceeded
`max_connections`. Lower `DB_POOL_SIZE` or `--workers`.

**Out of disk.** `docker system prune -af --volumes` — but read that carefully,
`--volumes` will delete your database. Prefer `docker image prune -af`.
