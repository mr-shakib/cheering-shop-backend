"""Model/database drift guard.

Migration 0001 is raw DDL and the ORM models are a hand-written mirror of it.
Nothing enforces that they agree — except this. `alembic check` compares the
live schema against `Base.metadata` and fails on any difference, so a column
added to a model without a migration (or vice versa) breaks the build here
rather than at runtime in Step 4.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.usefixtures("db_available")
def test_models_match_the_migrated_schema():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "New upgrade operations detected" not in combined, (
        "ORM models have drifted from the migrated schema:\n"
        + "\n".join(
            line for line in combined.splitlines() if "Detected" in line or "FAILED" in line
        )
    )
    assert "No new upgrade operations detected" in combined, combined[-2000:]
