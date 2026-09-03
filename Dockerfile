# 3.13-slim rather than 3.14: every dependency was import-tested on 3.14 and
# works, but 3.13 is the conservative choice for a deployed image while the
# 3.14 wheel ecosystem settles. Bump the tag when you are ready — nothing in
# this codebase depends on the difference.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# libpq for psycopg3's binary wheel; curl for the container healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, from a fully pinned lockfile, so this layer is cached and
# rebuilt only when requirements.txt changes — application edits do not trigger
# a full reinstall. Regenerate with:
#     uv pip compile pyproject.toml --python-version 3.13 -o requirements.txt
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations
# Operator tooling (create_admin.py) — the README tells people to run it with
# `docker exec`, which only works if it is actually in the image.
COPY scripts ./scripts
COPY alembic.ini pyproject.toml ./
COPY docker-entrypoint.sh /usr/local/bin/

# --no-deps: everything is already installed above at pinned versions. This step
# only registers the `app` package itself.
# NOTE: pyproject.toml declares packages = ["app"], so it MUST be copied after
# app/ exists — installing it earlier fails with "package directory 'app' does
# not exist".
RUN pip install --no-deps .

# Non-root: a container that does not need to write to its own filesystem
# should not be able to.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations run on every container start, before the app is reachable. A deploy
# that ships new code against an old schema fails at the first query touching a
# new column; alembic is idempotent so this is a no-op when already current.
# With multiple replicas, run migrations as a one-shot job instead — concurrent
# `alembic upgrade` calls contend on the version table.
ENTRYPOINT ["docker-entrypoint.sh"]

# --proxy-headers + --forwarded-allow-ips: behind a reverse proxy, without
# these, request.client.host is the PROXY's address — so every session row
# records the wrong IP and the per-IP login limit becomes one shared bucket for
# all users. FORWARDED_ALLOW_IPS must name the proxy, never "*" on a public host
# (that would let any client spoof X-Forwarded-For and evade the limit).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
