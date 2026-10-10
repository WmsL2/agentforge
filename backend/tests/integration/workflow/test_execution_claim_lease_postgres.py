"""Real PostgreSQL claim/lease and caller-owned fencing transaction proofs."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from app.db.models.workflow import Workflow, WorkflowRun
from app.db.models.workspace import Workspace
from app.repositories.workflow.run import claim as repository
from app.services.workflow import WorkflowExecutionClaimService

pytestmark = pytest.mark.anyio
DURATION = timedelta(minutes=2)


@pytest.fixture
async def make_run(postgres_restart_session_factory):
    factory = postgres_restart_session_factory
    workspace_id, workflow_id = uuid4(), uuid4()
    async with factory() as db:
        db.add(Workspace(id=workspace_id, name="Atomic 2 claim proof"))
        await db.flush()
        db.add(
            Workflow(id=workflow_id, workspace_id=workspace_id, name="Claim proof", definition={})
        )
        await db.commit()

    async def create(status="pending", *, expired=False):
        run_id = uuid4()
        async with factory() as db:
            db.add(
                WorkflowRun(
                    id=run_id,
                    workflow_id=workflow_id,
                    workflow_revision=1,
                    definition_snapshot={},
                    status=status,
                )
            )
            await db.flush()
            if expired:
                await db.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == run_id)
                    .values(
                        execution_claim_token=uuid4(),
                        execution_claim_generation=1,
                        execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1),
                    )
                )
            await db.commit()
        return run_id

    try:
        yield create
    finally:
        async with factory() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()


async def read_run(factory, run_id):
    async with factory() as db:
        row = await db.get(WorkflowRun, run_id)
        assert row is not None
        return row


async def expire(factory, run_id):
    async with factory() as db:
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(execution_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
        await db.commit()


async def wait_until_database_expiry(db, run_id):
    """Wait by the database clock, without relying on worker wall-clock sleeps."""
    await db.execute(
        select(
            func.pg_sleep(
                func.greatest(
                    0,
                    func.extract(
                        "epoch", WorkflowRun.execution_lease_expires_at - func.clock_timestamp()
                    ),
                )
                + 0.05
            )
        ).where(WorkflowRun.id == run_id)
    )


async def wait_until_blocked(factory, pid):
    """Observe actual PostgreSQL lock contention, rather than guessing a delay."""
    async with asyncio.timeout(10), factory() as db:
        while not await db.scalar(select(func.cardinality(func.pg_blocking_pids(pid)) > 0)):
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("workers", [2, 8])
async def test_independent_connections_have_exactly_one_claim_winner(
    postgres_restart_session_factory, make_run, workers
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    gate = asyncio.Event()
    ready = [asyncio.Event() for _ in range(workers)]

    async def worker(index):
        async with factory() as db, db.begin():
            pid = await db.scalar(select(func.pg_backend_pid()))
            ready[index].set()
            await gate.wait()
            return pid, await repository.claim_execution(db, run_id, DURATION)

    tasks = [asyncio.create_task(worker(index)) for index in range(workers)]
    try:
        async with asyncio.timeout(15):
            await asyncio.gather(*(event.wait() for event in ready))
            gate.set()
            results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len({pid for pid, _ in results}) == workers
    winners = [lease for _, lease in results if lease is not None]
    assert len(winners) == 1
    row = await read_run(factory, run_id)
    assert row.execution_claim_token == winners[0].claim_token
    assert row.execution_claim_generation == winners[0].generation == 1
    assert row.execution_lease_expires_at == winners[0].expires_at
    assert row.status == "pending"


async def test_claim_renew_release_and_generation_persist(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        service = WorkflowExecutionClaimService(db)
        first = await service.claim(run_id, DURATION)
        assert first is not None and first.generation == 1
        assert first.expires_at.utcoffset() == timedelta(0)
        assert await service.claim(run_id, DURATION) is None
        renewed = await service.renew(first, DURATION + timedelta(minutes=1))
        assert renewed is not None and renewed.expires_at > first.expires_at
        assert renewed.claim_token == first.claim_token and renewed.generation == first.generation
        stored = await read_run(factory, run_id)
        assert stored.execution_lease_expires_at == renewed.expires_at
        assert not await service.release(replace(first, claim_token=uuid4()))
        assert not await service.release(replace(first, generation=0))
        assert await service.release(renewed)
        stored = await read_run(factory, run_id)
        assert stored.execution_claim_token is None and stored.execution_lease_expires_at is None
        assert stored.execution_claim_generation == 1
        second = await service.claim(run_id, DURATION)
        assert (
            second is not None
            and second.generation == 2
            and second.claim_token != first.claim_token
        )
    stored = await read_run(factory, run_id)
    assert stored.execution_claim_generation == 2
    assert stored.execution_claim_token == second.claim_token


@pytest.mark.parametrize("status", ["pending", "running"])
async def test_expired_claim_replaced_and_stale_holder_rejected(
    postgres_restart_session_factory, make_run, status
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        first = await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    assert first is not None
    async with factory() as db:
        await db.execute(update(WorkflowRun).where(WorkflowRun.id == run_id).values(status=status))
        await db.commit()
    await expire(factory, run_id)
    async with factory() as db:
        service = WorkflowExecutionClaimService(db)
        assert await service.renew(first, DURATION) is None
        assert not await service.release(first)
        second = await service.claim(run_id, DURATION)
        assert (
            second is not None
            and second.generation == 2
            and second.claim_token != first.claim_token
        )
        assert await service.renew(first, DURATION) is None
        assert not await service.release(first)
    stored = await read_run(factory, run_id)
    assert stored.execution_claim_token == second.claim_token
    assert stored.execution_claim_generation == second.generation
    assert stored.status == status


@pytest.mark.parametrize("status", ["paused", "completed", "failed", "cancelled"])
@pytest.mark.parametrize("expired", [False, True])
async def test_nonexecuting_statuses_reject_claim(
    postgres_restart_session_factory, make_run, status, expired
):
    factory = postgres_restart_session_factory
    run_id = await make_run(status, expired=expired)
    before = await read_run(factory, run_id)
    async with factory() as db:
        assert await WorkflowExecutionClaimService(db).claim(run_id, DURATION) is None
    after = await read_run(factory, run_id)
    assert (
        after.execution_claim_token,
        after.execution_claim_generation,
        after.execution_lease_expires_at,
        after.status,
    ) == (
        before.execution_claim_token,
        before.execution_claim_generation,
        before.execution_lease_expires_at,
        status,
    )


async def test_unleased_running_and_missing_run_are_not_claimable(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run("running")
    async with factory() as db:
        service = WorkflowExecutionClaimService(db)
        assert await service.claim(run_id, DURATION) is None
        assert await service.claim(uuid4(), DURATION) is None
    row = await read_run(factory, run_id)
    assert (
        row.status == "running"
        and row.execution_claim_token is None
        and row.execution_claim_generation == 0
    )


async def test_valid_running_lease_blocks_claim(postgres_restart_session_factory, make_run):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        lease = await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    async with factory() as db:
        await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == run_id).values(status="running")
        )
        await db.commit()
    async with factory() as db:
        assert await WorkflowExecutionClaimService(db).claim(run_id, DURATION) is None
    assert (await read_run(factory, run_id)).execution_claim_token == lease.claim_token


async def test_fencing_rejects_stale_token_generation_and_expiry(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        lease = await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    assert lease is not None
    for candidate in (
        replace(lease, claim_token=uuid4()),
        replace(lease, generation=0),
        replace(lease, run_id=uuid4()),
    ):
        async with factory() as db, db.begin():
            assert not await repository.lock_and_validate_execution_lease(db, candidate)
    async with factory() as db, db.begin():
        assert await repository.lock_and_validate_execution_lease(db, lease)
        assert db.in_transaction()
    await expire(factory, run_id)
    async with factory() as db, db.begin():
        assert not await repository.lock_and_validate_execution_lease(db, lease)
    async with factory() as db:
        replacement = await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    async with factory() as db, db.begin():
        assert not await repository.lock_and_validate_execution_lease(db, lease)
        assert not await repository.lock_and_validate_execution_lease(
            db, replace(replacement, generation=lease.generation)
        )
        assert await repository.lock_and_validate_execution_lease(db, replacement)


async def test_rollback_does_not_persist_claim_or_protected_write(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        provisional = await repository.claim_execution(db, run_id, DURATION)
        assert provisional is not None
        assert await repository.lock_and_validate_execution_lease(db, provisional)
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(node_outputs={"uncommitted": True})
        )
        await db.rollback()
    stored = await read_run(factory, run_id)
    assert stored.execution_claim_token is None and stored.execution_lease_expires_at is None
    assert stored.execution_claim_generation == 0 and stored.node_outputs == {}
    async with factory() as db:
        actual = await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    assert (
        actual is not None
        and actual.generation == 1
        and actual.claim_token != provisional.claim_token
    )


async def test_service_rolls_back_on_sql_error_and_rejects_caller_transaction(
    postgres_restart_session_factory, make_run, monkeypatch
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        # Force a real SQL failure after claim's UPDATE, before transaction exit.
        original = repository.claim_execution

        async def failing_claim(*args):
            await original(*args)
            await db.execute(text("SELECT 1 / 0"))

        with monkeypatch.context() as context:
            context.setattr(repository, "claim_execution", failing_claim)
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError):
                await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
        assert not db.in_transaction()
        assert (await read_run(factory, run_id)).execution_claim_token is None
        async with db.begin():
            with pytest.raises(InvalidRequestError):
                await WorkflowExecutionClaimService(db).claim(run_id, DURATION)
    assert (await read_run(factory, run_id)).execution_claim_generation == 0


async def test_fencing_lock_serializes_old_protected_write_before_reclaim(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        old = await WorkflowExecutionClaimService(db).claim(run_id, timedelta(seconds=3))
    assert old is not None
    started = asyncio.Event()
    pids = []

    async def reclaim():
        async with factory() as db, db.begin():
            pids.append(await db.scalar(select(func.pg_backend_pid())))
            started.set()
            lease = await repository.claim_execution(db, run_id, DURATION)
            assert lease is not None
            assert await repository.lock_and_validate_execution_lease(db, lease)
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .values(node_outputs={"writer": "new"})
            )
            return lease

    task = None
    try:
        async with factory() as old_db, old_db.begin():
            assert await repository.lock_and_validate_execution_lease(old_db, old)
            old_pid = await old_db.scalar(select(func.pg_backend_pid()))
            await wait_until_database_expiry(old_db, run_id)
            task = asyncio.create_task(reclaim())
            await asyncio.wait_for(started.wait(), 10)
            assert pids[0] != old_pid
            await wait_until_blocked(factory, pids[0])
            assert not task.done()
            await old_db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .values(node_outputs={"writer": "old"})
            )
        new = await asyncio.wait_for(task, 10)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    stored = await read_run(factory, run_id)
    assert stored.node_outputs == {"writer": "new"}
    assert stored.execution_claim_token == new.claim_token and new.generation == old.generation + 1
    async with factory() as db, db.begin():
        assert not await repository.lock_and_validate_execution_lease(db, old)


async def test_fencing_rechecks_database_clock_after_waiting_for_lock(
    postgres_restart_session_factory, make_run
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        lease = await WorkflowExecutionClaimService(db).claim(run_id, timedelta(seconds=3))
    assert lease is not None
    started = asyncio.Event()
    pids = []

    async def validate():
        async with factory() as db, db.begin():
            pids.append(await db.scalar(select(func.pg_backend_pid())))
            started.set()
            return await repository.lock_and_validate_execution_lease(db, lease)

    task = None
    try:
        async with factory() as blocker, blocker.begin():
            await blocker.scalar(
                select(WorkflowRun.id).where(WorkflowRun.id == run_id).with_for_update()
            )
            task = asyncio.create_task(validate())
            await asyncio.wait_for(started.wait(), 10)
            await wait_until_blocked(factory, pids[0])
            await wait_until_database_expiry(blocker, run_id)
        assert await asyncio.wait_for(task, 10) is False
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "values",
    [
        {"execution_claim_generation": -1},
        {"execution_claim_token": uuid4()},
        {"execution_lease_expires_at": func.clock_timestamp()},
    ],
)
async def test_database_rejects_inconsistent_claim_state(
    postgres_restart_session_factory, make_run, values
):
    factory = postgres_restart_session_factory
    run_id = await make_run()
    async with factory() as db:
        with pytest.raises(IntegrityError):
            await db.execute(update(WorkflowRun).where(WorkflowRun.id == run_id).values(**values))
        await db.rollback()
    stored = await read_run(factory, run_id)
    assert stored.execution_claim_generation == 0 and stored.execution_claim_token is None
