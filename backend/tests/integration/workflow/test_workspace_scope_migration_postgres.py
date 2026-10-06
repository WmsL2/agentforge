"""Opt-in destructive PostgreSQL proof for the 0039 to 0040 workspace migration."""

import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

E2E_GATE = "AGENTFORGE_RUN_POSTGRES_E2E"
VERIFY_DATABASE = "agentforge_v08_atomic7_verify"
REVISION_0039 = "0039_add_workflow_workspace_scope"
REVISION_0040 = "0040_harden_workflow_workspace_scope"
BACKEND_ROOT = Path(__file__).parents[3]


def personal_workspace_id(user_id):
    return uuid5(NAMESPACE_URL, f"agentforge://personal-workspace/{user_id}")


def alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


async def seed_user(connection, user_id, email: str) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, role, is_app_admin) "
            "VALUES (:id, :email, NULL, 'user', false)"
        ),
        {"id": user_id, "email": email},
    )


async def seed_null_scoped_workflow(connection, workflow_id, user_id) -> None:
    await connection.execute(
        text(
            "INSERT INTO workflows "
            "(id, user_id, workspace_id, name, description, definition, revision) "
            "VALUES (:id, :user_id, NULL, 'Legacy', NULL, CAST(:definition AS jsonb), 1)"
        ),
        {
            "id": workflow_id,
            "user_id": user_id,
            "definition": json.dumps(
                {
                    "schema_version": 1,
                    "entry_node_id": "start",
                    "nodes": [{"id": "start", "kind": "start"}],
                    "edges": [],
                    "metadata": {},
                }
            ),
        },
    )


@pytest.mark.anyio
async def test_workspace_scope_hardening_migration_repairs_data_and_rolls_back_unrecoverable_nulls():
    if os.getenv(E2E_GATE) != "1":
        pytest.skip(f"Set {E2E_GATE}=1 to run PostgreSQL integration tests.")
    if settings.POSTGRES_DB != VERIFY_DATABASE:
        pytest.skip(
            "Destructive migration proof requires "
            f"POSTGRES_DB={VERIFY_DATABASE!r}; got {settings.POSTGRES_DB!r}."
        )

    user_a, workflow_a = uuid4(), uuid4()
    user_b, workflow_b, unrecoverable_workflow = uuid4(), uuid4(), uuid4()
    workspace_a, workspace_b = personal_workspace_id(user_a), personal_workspace_id(user_b)
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        await engine.dispose()
        alembic("upgrade", REVISION_0040)
        alembic("downgrade", REVISION_0039)

        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0039
            await seed_user(connection, user_a, f"migration-a-{user_a.hex}@example.invalid")
            await seed_null_scoped_workflow(connection, workflow_a, user_a)
            await connection.execute(
                text(
                    "INSERT INTO workspaces (id, name, created_by_user_id) "
                    "VALUES (:id, 'Personal Workspace', :user_id)"
                ),
                {"id": workspace_a, "user_id": user_a},
            )
            await connection.execute(
                text(
                    "INSERT INTO workspace_memberships (workspace_id, user_id, role) "
                    "VALUES (:workspace_id, :user_id, 'member')"
                ),
                {"workspace_id": workspace_a, "user_id": user_a},
            )
        await engine.dispose()

        alembic("upgrade", REVISION_0040)
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0040
            assert await connection.scalar(
                text("SELECT workspace_id FROM workflows WHERE id = :id"), {"id": workflow_a}
            ) == workspace_a
            assert await connection.scalar(
                text(
                    "SELECT role FROM workspace_memberships "
                    "WHERE workspace_id = :workspace_id AND user_id = :user_id"
                ),
                {"workspace_id": workspace_a, "user_id": user_a},
            ) == "owner"
            assert await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'workflows' AND column_name = 'workspace_id'"
                )
            ) == "NO"
        await engine.dispose()

        alembic("downgrade", REVISION_0039)
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as connection:
            await seed_user(connection, user_b, f"migration-b-{user_b.hex}@example.invalid")
            await seed_null_scoped_workflow(connection, workflow_b, user_b)
            await seed_null_scoped_workflow(connection, unrecoverable_workflow, None)
        await engine.dispose()

        with pytest.raises(subprocess.CalledProcessError):
            alembic("upgrade", REVISION_0040)

        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0039
            assert await connection.scalar(
                text("SELECT workspace_id FROM workflows WHERE id = :id"), {"id": workflow_b}
            ) is None
            assert await connection.scalar(
                text("SELECT id FROM workspaces WHERE id = :id"), {"id": workspace_b}
            ) is None
            await connection.execute(text("DELETE FROM workflows WHERE id = :id"), {"id": unrecoverable_workflow})
        await engine.dispose()

        alembic("upgrade", REVISION_0040)
    finally:
        with suppress(Exception):
            await engine.dispose()
        with suppress(Exception):
            alembic("upgrade", REVISION_0040)
