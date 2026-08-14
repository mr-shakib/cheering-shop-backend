#!/usr/bin/env bash
# Print a complete environment block ready to paste into Dokploy's
# Environment tab. Every secret is generated separately — reusing one value
# across two fields would mean a single leak compromises all of them.
#
#   ./deploy/gen-env.sh api.example.com
#
set -euo pipefail

HOST="${1:-}"
if [ -z "$HOST" ]; then
    echo "usage: $0 <hostname>    e.g. $0 crshop-api.duckdns.org" >&2
    exit 1
fi

gen() { openssl rand -hex 32; }

cat <<ENVBLOCK
# ---- paste everything below into Dokploy -> Environment ----
POSTGRES_USER=crshop
POSTGRES_PASSWORD=$(gen)
POSTGRES_DB=crshop
REDIS_PASSWORD=$(gen)

ENVIRONMENT=production
DEBUG=false
ENABLE_DOCS=true
CORS_ORIGINS=https://$HOST

JWT_SECRET_KEY=$(gen)
RIDER_PIN_PEPPER=$(gen)
OTP_PEPPER=$(gen)
TOTP_ENCRYPTION_KEY=$(gen)

DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5
FORWARDED_ALLOW_IPS=172.16.0.0/12
# ---- end ----
ENVBLOCK

cat >&2 <<'WARN'

SAVE TOTP_ENCRYPTION_KEY SOMEWHERE SAFE.
It encrypts stored 2FA secrets. Changing it later makes every enrolled user's
2FA undecryptable and locks them out — it cannot be rotated in place.

ENABLE_DOCS is set to true so your frontend team can use /docs while
integrating. Set it to false before real users exist: it publishes your whole
API surface.
WARN
