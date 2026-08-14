#!/bin/sh
# Deploy entrypoint: bring the schema up to date, then start the process.
#
# Migrations run here rather than in a separate manual step because forgetting
# them is the single most common way a deploy half-works: the new code goes
# live against the old schema and fails at the first query touching a new
# column. Alembic is idempotent, so re-running on an up-to-date database is a
# no-op.
#
# NOTE: with more than one replica, run this as a one-shot job instead — several
# containers racing `alembic upgrade` will contend on the version table.
set -e

echo "==> Applying database migrations"
alembic upgrade head

echo "==> Starting: $*"
exec "$@"
