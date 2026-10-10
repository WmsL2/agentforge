"""Destructive 0040/0041 cycle, restricted to the dedicated disposable database."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

DATABASE = "agentforge_v09_atomic2_migration_verify"
PREVIOUS = "0040_harden_workflow_workspace_scope"
HEAD = "0041_add_workflow_execution_claim_lease"
BACKEND_ROOT = Path(__file__).parents[3]


def migrate(action, revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.anyio
async def test_migration_preserves_legacy_run_and_reverses_only_claim_fields():
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_POSTGRES_E2E=1 to run PostgreSQL migration proof.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Destructive migration proof requires POSTGRES_DB={DATABASE}.")
    migrate("upgrade", PREVIOUS)
    workspace_id, workflow_id, run_id = uuid4(), uuid4(), uuid4()
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS
            )
            await connection.execute(
                text("INSERT INTO workspaces (id, name) VALUES (:id, 'Atomic 2 migration proof')"),
                {"id": workspace_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO workflows (id, workspace_id, name, definition, revision) VALUES (:id, :workspace_id, 'Legacy', '{}'::jsonb, 1)"
                ),
                {"id": workflow_id, "workspace_id": workspace_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO workflow_runs (id, workflow_id, workflow_revision, definition_snapshot, status, input, node_outputs) VALUES (:id, :workflow_id, 1, '{}'::jsonb, 'running', '{}'::jsonb, '{}'::jsonb)"
                ),
                {"id": run_id, "workflow_id": workflow_id},
            )
        migrate("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            row = (
                await connection.execute(
                    text(
                        "SELECT status, execution_claim_token, execution_lease_expires_at, execution_claim_generation FROM workflow_runs WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            ).one()
            assert tuple(row) == ("running", None, None, 0)
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid='workflow_runs'::regclass AND contype='c'"
                        )
                    )
                ).scalars()
            )
            assert {
                "workflow_runs_execution_claim_generation_nonnegative_check",
                "workflow_runs_execution_claim_lease_pair_check",
            } <= constraints
        migrate("downgrade", PREVIOUS)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS
            )
            assert (
                await connection.scalar(
                    text("SELECT status FROM workflow_runs WHERE id=:id"), {"id": run_id}
                )
                == "running"
            )
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='workflow_runs'"
                        )
                    )
                ).scalars()
            )
            assert (
                not {
                    "execution_claim_token",
                    "execution_lease_expires_at",
                    "execution_claim_generation",
                }
                & columns
            )
        migrate("upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert (
                await connection.scalar(
                    text("SELECT execution_claim_generation FROM workflow_runs WHERE id=:id"),
                    {"id": run_id},
                )
                == 0
            )
    finally:
        # Restore only this disposable database, even after assertion failures.
        try:
            migrate("upgrade", "head")
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM workspaces WHERE id=:id"), {"id": workspace_id}
                )
        finally:
            await engine.dispose()
