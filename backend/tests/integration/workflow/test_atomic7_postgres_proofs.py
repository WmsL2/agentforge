"""Atomic 7 release proofs against a disposable PostgreSQL database."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workflow import WorkflowCheckpoint as DBWorkflowCheckpoint
from app.db.models.workspace import Workspace
from app.repositories.workflow.run import claim as claim_repo
from app.services.workflow.application.background import durability
from app.services.workflow.application.background.domain import WorkflowExecutionLeaseLostError
from app.services.workflow.application.background.durability import (
    FencedDurableWorkflowExecutionPersistence,
)
from app.services.workflow.execution.run.domain import WorkflowRun as DomainWorkflowRun

DATABASE = "agentforge_v09_atomic7_verify"
HEAD = "0042_add_workflow_recovery_dispatch_schedule"
LEASE_DURATION = timedelta(minutes=2)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def atomic7_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provide isolated PostgreSQL connections and fail closed outside Atomic 7 CI."""
    if os.getenv("AGENTFORGE_RUN_ATOMIC7_E2E") != "1":
        pytest.skip("Atomic 7 dedicated PostgreSQL proofs are not enabled.")
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.fail("Atomic 7 proofs require AGENTFORGE_RUN_POSTGRES_E2E=1.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.fail(f"Atomic 7 proofs require POSTGRES_DB={DATABASE}.")

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        except (OSError, SQLAlchemyError) as error:
            pytest.fail(f"Atomic 7 dedicated PostgreSQL is unavailable: {type(error).__name__}.")
        if revision != HEAD:
            pytest.fail(f"Atomic 7 PostgreSQL must be at {HEAD}; found {revision!r}.")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def atomic7_runs(
    atomic7_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Callable[[], Awaitable[tuple[UUID, UUID]]]]:
    workspace_ids: list[UUID] = []

    async def create() -> tuple[UUID, UUID]:
        workspace_id, workflow_id, run_id = uuid4(), uuid4(), uuid4()
        workspace_ids.append(workspace_id)
        async with atomic7_factory() as db:
            db.add(Workspace(id=workspace_id, name=f"Atomic 7 {workspace_id.hex}"))
            await db.flush()
            db.add(
                Workflow(
                    id=workflow_id,
                    workspace_id=workspace_id,
                    name="Atomic 7 proof",
                    definition={},
                    revision=1,
                )
            )
            await db.flush()
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=workflow_id,
                    workflow_revision=1,
                    definition_snapshot={},
                    status="pending",
                    input={},
                )
            )
            await db.commit()
        return workflow_id, run_id

    try:
        yield create
    finally:
        if workspace_ids:
            async with atomic7_factory() as db:
                await db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
                await db.commit()


def _runtime_run(
    workflow_id: UUID, run_id: UUID, *, outputs: dict[str, object]
) -> DomainWorkflowRun:
    run = DomainWorkflowRun(id=run_id, workflow_id=workflow_id, workflow_revision=1)
    run.start()
    run.node_outputs = outputs
    return run


async def _read_run(factory: async_sessionmaker[AsyncSession], run_id: UUID) -> WorkflowRun:
    async with factory() as db:
        run = await db.get(WorkflowRun, run_id)
        assert run is not None
        return run


async def _checkpoint_sequences(
    factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[int]:
    async with factory() as db:
        return list(
            await db.scalars(
                select(DBWorkflowCheckpoint.sequence)
                .where(DBWorkflowCheckpoint.run_id == run_id)
                .order_by(DBWorkflowCheckpoint.sequence)
            )
        )


async def _expire_lease(factory: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    async with factory() as db:
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
        await db.commit()


async def test_pending_run_has_exactly_one_concurrent_claim_winner(
    atomic7_factory, atomic7_runs
) -> None:
    _, run_id = await atomic7_runs()
    ready = [asyncio.Event(), asyncio.Event()]
    start = asyncio.Event()

    async def claim(worker: int):
        async with atomic7_factory() as db, db.begin():
            ready[worker].set()
            await start.wait()
            return await claim_repo.claim_execution(db, run_id, LEASE_DURATION)

    first, second = asyncio.create_task(claim(0)), asyncio.create_task(claim(1))
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), timeout=10)
    start.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    winners = [lease for lease in results if lease is not None]

    assert len(winners) == 1
    winner = winners[0]
    stored = await _read_run(atomic7_factory, run_id)
    assert stored.execution_claim_token == winner.claim_token
    assert stored.execution_claim_generation == winner.generation == 1
    assert stored.execution_lease_expires_at == winner.expires_at
    async with atomic7_factory() as db, db.begin():
        assert await claim_repo.lock_and_validate_execution_lease(db, winner)
        assert await claim_repo.claim_execution(db, run_id, LEASE_DURATION) is None


async def test_expired_lease_is_reclaimed_with_new_generation_and_fences_old_worker(
    atomic7_factory, atomic7_runs
) -> None:
    _, run_id = await atomic7_runs()
    async with atomic7_factory() as db:
        first = await claim_repo.claim_execution(db, run_id, LEASE_DURATION)
        await db.commit()
    assert first is not None
    await _expire_lease(atomic7_factory, run_id)

    async with atomic7_factory() as db:
        second = await claim_repo.claim_execution(db, run_id, LEASE_DURATION)
        assert second is not None
        assert second.claim_token != first.claim_token
        assert second.generation == first.generation + 1 == 2
        assert await claim_repo.renew_execution(db, first, LEASE_DURATION) is None
        assert not await claim_repo.release_execution(db, first)
        await db.commit()

    stored = await _read_run(atomic7_factory, run_id)
    assert stored.execution_claim_token == second.claim_token
    assert stored.execution_claim_generation == 2
    async with atomic7_factory() as db, db.begin():
        assert await claim_repo.lock_and_validate_execution_lease(db, second)


async def test_stale_fenced_persistence_cannot_overwrite_reclaimed_run(
    atomic7_factory, atomic7_runs
) -> None:
    workflow_id, run_id = await atomic7_runs()
    async with atomic7_factory() as db:
        old_lease = await claim_repo.claim_execution(db, run_id, LEASE_DURATION)
        await db.commit()
    assert old_lease is not None
    await _expire_lease(atomic7_factory, run_id)
    async with atomic7_factory() as db:
        new_lease = await claim_repo.claim_execution(db, run_id, LEASE_DURATION)
        await db.commit()
    assert new_lease is not None

    stale = FencedDurableWorkflowExecutionPersistence(atomic7_factory, old_lease)
    with pytest.raises(WorkflowExecutionLeaseLostError):
        await stale.persist_node_completion(
            _runtime_run(workflow_id, run_id, outputs={"worker": "old"}),
            completed_node_ids=("start",),
            pending_node_id=None,
        )
    after_stale = await _read_run(atomic7_factory, run_id)
    assert after_stale.status == "pending"
    assert after_stale.node_outputs == {}
    assert after_stale.execution_claim_token == new_lease.claim_token
    assert await _checkpoint_sequences(atomic7_factory, run_id) == []

    current = FencedDurableWorkflowExecutionPersistence(atomic7_factory, new_lease)
    await current.persist_node_completion(
        _runtime_run(workflow_id, run_id, outputs={"worker": "new"}),
        completed_node_ids=("start",),
        pending_node_id=None,
    )
    stored = await _read_run(atomic7_factory, run_id)
    assert stored.status == "running" and stored.node_outputs == {"worker": "new"}
    assert stored.execution_claim_token == new_lease.claim_token
    assert await _checkpoint_sequences(atomic7_factory, run_id) == [1]


async def test_checkpoint_write_failure_rolls_back_run_and_does_not_advance_sequence(
    atomic7_factory, atomic7_runs, monkeypatch
) -> None:
    workflow_id, run_id = await atomic7_runs()
    _, collision_run_id = await atomic7_runs()
    collision_id = uuid4()
    async with atomic7_factory() as db:
        db.add(
            DBWorkflowCheckpoint(
                id=collision_id,
                run_id=collision_run_id,
                workflow_revision=1,
                sequence=1,
                completed_node_ids=[],
                node_outputs={},
            )
        )
        lease = await claim_repo.claim_execution(db, run_id, LEASE_DURATION)
        await db.commit()
    assert lease is not None

    persistence = FencedDurableWorkflowExecutionPersistence(atomic7_factory, lease)
    monkeypatch.setattr(durability, "uuid4", lambda: collision_id)
    with pytest.raises(IntegrityError):
        await persistence.persist_node_completion(
            _runtime_run(workflow_id, run_id, outputs={"result": "must-roll-back"}),
            completed_node_ids=("start",),
            pending_node_id=None,
        )
    failed = await _read_run(atomic7_factory, run_id)
    assert failed.status == "pending" and failed.node_outputs == {}
    assert failed.execution_claim_token == lease.claim_token
    assert await _checkpoint_sequences(atomic7_factory, run_id) == []
    assert persistence._next_sequence == 1

    monkeypatch.undo()
    await persistence.persist_node_completion(
        _runtime_run(workflow_id, run_id, outputs={"result": "committed"}),
        completed_node_ids=("start",),
        pending_node_id=None,
    )
    assert await _checkpoint_sequences(atomic7_factory, run_id) == [1]
    async with atomic7_factory() as db, db.begin():
        assert await claim_repo.lock_and_validate_execution_lease(db, lease)


async def test_database_claim_and_checkpoint_constraints_reject_invalid_rows(
    atomic7_factory, atomic7_runs
) -> None:
    _, run_id = await atomic7_runs()
    for values in (
        {"execution_claim_generation": -1},
        {"execution_claim_token": uuid4()},
        {"execution_lease_expires_at": func.clock_timestamp()},
    ):
        async with atomic7_factory() as db:
            with pytest.raises(IntegrityError):
                await db.execute(
                    update(WorkflowRun).where(WorkflowRun.id == run_id).values(**values)
                )
            await db.rollback()

    async with atomic7_factory() as db:
        checkpoint = DBWorkflowCheckpoint(
            id=uuid4(),
            run_id=run_id,
            workflow_revision=1,
            sequence=1,
            completed_node_ids=[],
            node_outputs={},
        )
        db.add(checkpoint)
        await db.commit()
    async with atomic7_factory() as db:
        db.add(
            DBWorkflowCheckpoint(
                id=uuid4(),
                run_id=run_id,
                workflow_revision=1,
                sequence=1,
                completed_node_ids=[],
                node_outputs={},
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    stored = await _read_run(atomic7_factory, run_id)
    assert stored.execution_claim_generation == 0
    assert stored.execution_claim_token is None and stored.execution_lease_expires_at is None
    assert await _checkpoint_sequences(atomic7_factory, run_id) == [1]


async def test_final_migration_schema_exposes_claim_and_recovery_contract(atomic7_factory) -> None:
    async with atomic7_factory() as db:
        columns = set(
            await db.scalars(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'workflow_runs'
                    """
                )
            )
        )
        constraints = set(
            await db.scalars(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'workflow_runs'::regclass
                    """
                )
            )
        )
        indexes = set(
            await db.scalars(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = 'workflow_runs'
                    """
                )
            )
        )
    assert {
        "execution_claim_token",
        "execution_lease_expires_at",
        "execution_claim_generation",
        "recovery_last_dispatched_at",
        "recovery_next_dispatch_at",
    }.issubset(columns)
    assert {"execution_claim_generation_nonnegative", "execution_claim_lease_pair"}.issubset(
        constraints
    )
    assert "workflow_runs_recovery_dispatch_idx" in indexes
