"""Fixtures for opt-in PostgreSQL integration tests."""

import os
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models.workflow.approval.model import ApprovalRequest
from app.db.models.workflow.checkpoint.model import WorkflowCheckpoint
from app.db.models.workflow.definition.model import Workflow
from app.db.models.workflow.run.model import WorkflowRun

_POSTGRES_E2E_ENV = "AGENTFORGE_RUN_POSTGRES_E2E"
_EXPECTED_ALEMBIC_REVISION = "0039_add_workflow_workspace_scope"


@pytest.fixture
async def postgres_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a real PostgreSQL session isolated by an outer transaction."""
    if os.getenv(_POSTGRES_E2E_ENV) != "1":
        pytest.skip(f"Set {_POSTGRES_E2E_ENV}=1 to run PostgreSQL integration tests.")

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        try:
            connection = await engine.connect()
        except (OSError, SQLAlchemyError) as exception:
            pytest.skip(
                "PostgreSQL is unavailable; start PostgreSQL before running "
                f"this test ({exception.__class__.__name__})."
            )
        try:
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError as exception:
                pytest.skip(
                    "PostgreSQL is unavailable or migrations are missing; "
                    f"run Alembic migrations first ({exception.__class__.__name__})."
                )
            if revision != _EXPECTED_ALEMBIC_REVISION:
                pytest.skip(
                    "PostgreSQL migrations are not current; "
                    f"expected {_EXPECTED_ALEMBIC_REVISION!r}, found {revision!r}."
                )

            await connection.rollback()
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                workflow_id = session.info.get("e2e_workflow_id")
                run_id = session.info.get("e2e_run_id")
                await session.close()
                await transaction.rollback()

                if isinstance(workflow_id, UUID) and isinstance(run_id, UUID):
                    assert (
                        await connection.scalar(
                            select(func.count())
                            .select_from(ApprovalRequest)
                            .where(ApprovalRequest.run_id == run_id)
                        )
                        == 0
                    )
                    assert (
                        await connection.scalar(
                            select(func.count())
                            .select_from(Workflow)
                            .where(Workflow.id == workflow_id)
                        )
                        == 0
                    )
                    assert (
                        await connection.scalar(
                            select(func.count())
                            .select_from(WorkflowCheckpoint)
                            .where(WorkflowCheckpoint.run_id == run_id)
                        )
                        == 0
                    )
                    assert (
                        await connection.scalar(
                            select(func.count())
                            .select_from(WorkflowRun)
                            .where(WorkflowRun.id == run_id)
                        )
                        == 0
                    )
        finally:
            await connection.close()
    finally:
        await engine.dispose()


@pytest.fixture
async def postgres_restart_session_factory() -> AsyncGenerator[
    async_sessionmaker[AsyncSession], None
]:
    """Yield independent sessions whose commits are visible across NullPool connections."""
    if os.getenv(_POSTGRES_E2E_ENV) != "1":
        pytest.skip(f"Set {_POSTGRES_E2E_ENV}=1 to run PostgreSQL integration tests.")

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        except (OSError, SQLAlchemyError) as exception:
            pytest.skip(
                "PostgreSQL is unavailable or migrations are missing; "
                f"start PostgreSQL and run Alembic migrations first ({exception.__class__.__name__})."
            )
        if revision != _EXPECTED_ALEMBIC_REVISION:
            pytest.skip(
                "PostgreSQL migrations are not current; "
                f"expected {_EXPECTED_ALEMBIC_REVISION!r}, found {revision!r}."
            )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
