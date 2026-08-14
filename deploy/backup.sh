#!/usr/bin/env bash
# Nightly Postgres backup. Install with:
#   crontab -e
#   15 3 * * * /home/deploy/cr-shop/deploy/backup.sh >> /home/deploy/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/crshop-$STAMP.dump"
mkdir -p "$BACKUP_DIR"

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"

# shellcheck disable=SC1091
set -a; . ./.env.production; set +a

CID=$($COMPOSE ps -q postgres)
if [ -z "$CID" ]; then
    echo "ERROR: postgres container is not running" >&2
    exit 1
fi

REMOTE="/tmp/crshop-$STAMP.dump"
cleanup() { docker exec "$CID" rm -f "$REMOTE" 2>/dev/null || true; }
trap cleanup EXIT

# Dump to a file INSIDE the container rather than piping to stdout, because the
# verification below needs a seekable file: `pg_restore --list` on a pipe fails
# with "did not find magic string in file header" even for a perfectly good
# dump. -Fc (custom format) is compressed and lets pg_restore recover a single
# table instead of replaying everything.
docker exec "$CID" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$REMOTE"

# A backup you have never restored is a hope, not a backup. Verify inside the
# container: the host needs no postgresql-client, and the container's
# pg_restore always matches the server version that wrote the dump.
if ! docker exec "$CID" pg_restore --list "$REMOTE" >/dev/null 2>&1; then
    echo "ERROR: dump $STAMP failed verification — NOT pruning old backups" >&2
    exit 1
fi

docker cp "$CID:$REMOTE" "$OUT"

# Prune only after a verified success, so a run of bad backups can never delete
# the last good one.
find "$BACKUP_DIR" -name 'crshop-*.dump' -mtime "+$RETENTION_DAYS" -delete

echo "$(date -Is) backup ok: $OUT ($(du -h "$OUT" | cut -f1))"

# STRONGLY RECOMMENDED: copy off-box. A backup on the same disk as the database
# does not survive the failure mode you are actually insuring against.
#   rclone copy "$OUT" remote:crshop-backups/
