"""Guards the one duplication in this codebase.

`db/schema.sql` is the authoring source; migration 0001 embeds a verbatim copy
because migrations must be immutable. Duplication is acceptable here, silent
divergence is not — so this test fails the build the moment the two disagree.

If it fails after an intentional schema edit, you almost certainly want a NEW
migration rather than an edit to 0001: 0001 has already run in every environment
that exists, and changing it will not re-run there.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"
MIGRATION = ROOT / "migrations" / "versions" / "20260814_0001_initial.py"


def _normalise(sql: str) -> str:
    """Strip the transaction wrapper and collapse whitespace."""
    sql = re.sub(r"^\s*(BEGIN|COMMIT);\s*$", "", sql, flags=re.M)
    return re.sub(r"\s+", " ", sql).strip()


def test_migration_matches_schema_sql():
    schema = _normalise(SCHEMA_SQL.read_text())
    embedded = MIGRATION.read_text()

    match = re.search(r'SCHEMA_DDL = r"""(.*?)"""', embedded, re.S)
    assert match, "migration 0001 no longer exposes a SCHEMA_DDL block"

    assert _normalise(match.group(1)) == schema, (
        "db/schema.sql and migration 0001 have diverged.\n"
        "Do NOT edit migration 0001 to fix this — it has already been applied "
        "everywhere. Add a new migration for the change instead."
    )


def test_every_table_is_dropped_by_downgrade():
    """A downgrade that leaves tables behind makes the migration non-reversible."""
    schema = SCHEMA_SQL.read_text()
    migration = MIGRATION.read_text()

    tables = set(re.findall(r"CREATE TABLE (\w+)", schema))
    types = set(re.findall(r"CREATE TYPE (\w+)", schema))
    dropped_tables = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", migration))
    dropped_types = set(re.findall(r"DROP TYPE IF EXISTS (\w+)", migration))

    assert tables - dropped_tables == set(), f"downgrade misses tables: {tables - dropped_tables}"
    assert types - dropped_types == set(), f"downgrade misses types: {types - dropped_types}"
