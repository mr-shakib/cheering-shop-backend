"""`db/schema.sql` must describe what the migrations actually produce.

Originally this compared `db/schema.sql` textually against migration 0001's
embedded DDL. That premise expired the moment a second migration existed: 0001
is an immutable historical snapshot, while `schema.sql` documents the CURRENT
schema. Comparing them would either force 0001 to be edited (which is never
safe — it has already run everywhere) or force `schema.sql` to go stale.

So the check is now behavioural instead of textual, and stronger for it: build
one database from `db/schema.sql`, build another with `alembic upgrade head`,
and compare the structures. If they differ, either the migrations do not produce
the documented schema, or the documentation is out of date — both are bugs.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"
INITIAL_MIGRATION = ROOT / "migrations" / "versions" / "20260814_0001_initial.py"

INSPECT_COLUMNS = """
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name NOT IN ('spatial_ref_sys', 'alembic_version')
  AND table_name NOT LIKE 'rider_location_pings_%'
ORDER BY table_name, column_name
"""

INSPECT_CONSTRAINTS = """
SELECT c.conrelid::regclass::text AS tbl, c.conname, c.contype
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'public'
  AND c.conrelid::regclass::text NOT LIKE 'rider_location_pings_%'
  -- alembic_version is Alembic's own bookkeeping; it exists only in the
  -- migrated database, by design.
  AND c.conrelid::regclass::text <> 'alembic_version'
ORDER BY 1, 2
"""


def _admin_url() -> str:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql+psycopg://")
    return re.sub(r"/[^/]+$", "/postgres", url)


def _recreate(dbname: str) -> str:
    engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    engine.dispose()
    return re.sub(r"/[^/]+$", f"/{dbname}", os.environ["DATABASE_URL"])


def _inspect(url: str) -> tuple[list, list]:
    engine = create_engine(url)
    with engine.connect() as conn:
        cols = [tuple(r) for r in conn.execute(text(INSPECT_COLUMNS))]
        cons = [tuple(r) for r in conn.execute(text(INSPECT_CONSTRAINTS))]
    engine.dispose()
    return cols, cons


@pytest.mark.usefixtures("db_available")
def test_schema_sql_matches_migrated_head():
    """The documented schema and the migrated schema must be the same thing."""
    # Build A from db/schema.sql
    url_a = _recreate("crshop_parity_doc")
    engine = create_engine(url_a, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(SCHEMA_SQL.read_text()))
    engine.dispose()

    # Build B by running every migration
    url_b = _recreate("crshop_parity_mig")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url_b, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr[-1500:]}"

    cols_a, cons_a = _inspect(url_a)
    cols_b, cons_b = _inspect(url_b)

    missing = set(cols_a) - set(cols_b)
    extra = set(cols_b) - set(cols_a)
    assert not missing and not extra, (
        "db/schema.sql and the migrations disagree.\n"
        f"  in schema.sql but not after migrating: {sorted(missing)[:8]}\n"
        f"  produced by migrations but undocumented: {sorted(extra)[:8]}\n"
        "Add a migration for the change, and update db/schema.sql to match."
    )

    con_missing = set(cons_a) - set(cons_b)
    con_extra = set(cons_b) - set(cons_a)
    assert not con_missing and not con_extra, (
        f"constraint drift:\n  only in schema.sql: {sorted(con_missing)[:8]}\n"
        f"  only after migrating: {sorted(con_extra)[:8]}"
    )


def test_initial_migration_downgrade_is_complete():
    """0001's downgrade must drop everything 0001 creates.

    Checked against the migration's OWN embedded DDL, not against schema.sql —
    later migrations add objects that 0001 knows nothing about.
    """
    migration = INITIAL_MIGRATION.read_text()
    embedded = re.search(r'SCHEMA_DDL = r"""(.*?)"""', migration, re.S)
    assert embedded, "migration 0001 no longer exposes a SCHEMA_DDL block"
    ddl = embedded.group(1)

    tables = set(re.findall(r"CREATE TABLE (\w+)", ddl))
    types = set(re.findall(r"CREATE TYPE (\w+)", ddl))
    dropped_tables = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", migration))
    dropped_types = set(re.findall(r"DROP TYPE IF EXISTS (\w+)", migration))

    assert not tables - dropped_tables, f"downgrade misses tables: {tables - dropped_tables}"
    assert not types - dropped_types, f"downgrade misses types: {types - dropped_types}"


def test_schema_sql_is_still_the_authoring_source():
    """A guard against schema.sql quietly rotting.

    It is referenced by the deployment docs and by `make verify-db`, so it must
    stay a runnable, complete description — not a stale fragment.
    """
    sql = SCHEMA_SQL.read_text()
    assert sql.strip().startswith("--"), "schema.sql lost its header"
    assert "BEGIN;" in sql and "COMMIT;" in sql, "schema.sql must be transactional"
    assert len(re.findall(r"CREATE TABLE (\w+)", sql)) >= 25
