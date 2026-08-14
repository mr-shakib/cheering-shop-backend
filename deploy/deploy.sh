#!/usr/bin/env bash
# Pull, rebuild and restart. Run from the repo root on the server:
#   ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production"

echo "==> Backing up before deploying (a failed migration is much less"
echo "    frightening when you can roll the data back)"
./deploy/backup.sh

echo "==> Fetching latest code"
git pull --ff-only

echo "==> Rebuilding image"
$COMPOSE build api

echo "==> Restarting services (api runs 'alembic upgrade head' on start)"
$COMPOSE up -d

echo "==> Waiting for health"
for i in $(seq 1 30); do
    if $COMPOSE exec -T api curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
        echo "    healthy after ${i}s"
        break
    fi
    sleep 1
done

$COMPOSE ps
echo
echo "==> Readiness:"
$COMPOSE exec -T api curl -fsS http://localhost:8000/health/ready || {
    echo "READINESS FAILED — check: $COMPOSE logs --tail=50 api"
    exit 1
}
