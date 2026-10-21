"""Real PostgreSQL proof for Atomic 6 recovery selection and reservation."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowCheckpoint, WorkflowRun
from app.db.models.workspace import Workspace
from app.repositories.workflow.run import claim as claim_repo
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.background.recovery_scanner import WorkflowRecoveryScanner

DATABASE = "agentforge_v09_atomic6_verify"
HEAD = "0042_add_workflow_recovery_dispatch_schedule"
_DELAY = timedelta(hours=1)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "entry_node_id": "start",
        "metadata": {},
        "nodes": [
            {"id": "start", "kind": "start", "config": {}, "metadata": {}},
            {
                "id": "approval",
                "kind": "approval",
                "config": {"prompt": "Continue?"},
                "metadata": {},
            },
            {"id": "end", "kind": "end", "config": {}, "metadata": {}},
        ],
        "edges": [
            {
                "id": "start-approval",
                "source": "start",
                "target": "approval",
                "condition": None,
                "metadata": {},
            },
            {
                "id": "approval-end",
                "source": "approval",
                "target": "end",
                "condition": None,
                "metadata": {},
            },
        ],
    }


@pytest.fixture
async def atomic6_factory() -> async_sessionmaker[AsyncSession]:
    if os.getenv("AGENTFORGE_RUN_ATOMIC6_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC6_E2E=1 for Atomic 6 PostgreSQL proofs.")
    if os.getenv("AGENTFORGE_RUN_POSTGRES_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_POSTGRES_E2E=1 for Atomic 6 PostgreSQL proofs.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.fail(f"Atomic 6 proofs require POSTGRES_DB={DATABASE}.")
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        except Exception as error:
            pytest.fail(f"Atomic 6 dedicated PostgreSQL is unavailable: {type(error).__name__}.")
        if revision != HEAD:
            pytest.fail(f"Atomic 6 PostgreSQL must be at {HEAD}; found {revision!r}.")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _create_run(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: str,
    lease: str | None = None,
    approved_resolution: bool = False,
    complete_resolution: bool = True,
    approval_status: str | None = None,
) -> tuple[UUID, UUID]:
    workspace_id, workflow_id, run_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    async with factory() as db:
        db.add(Workspace(id=workspace_id, name=f"Atomic 6 {workspace_id.hex}"))
        await db.flush()
        db.add(
            Workflow(
                id=workflow_id,
                workspace_id=workspace_id,
                name="Atomic 6 recovery",
                definition=_snapshot(),
                revision=1,
            )
        )
        await db.flush()
        values: dict[str, object] = {}
        if lease == "expired":
            values = {
                "execution_claim_token": uuid4(),
                "execution_claim_generation": 1,
                "execution_lease_expires_at": now - timedelta(seconds=1),
            }
        elif lease == "valid":
            values = {
                "execution_claim_token": uuid4(),
                "execution_claim_generation": 1,
                "execution_lease_expires_at": now + timedelta(hours=1),
            }
        db.add(
            WorkflowRun(
                id=run_id,
                workflow_id=workflow_id,
                workflow_revision=1,
                definition_snapshot=_snapshot(),
                status=status,
                input={},
                **values,
            )
        )
        await db.flush()
        if status == "paused":
            db.add(
                ApprovalRequest(
                    id=uuid4(),
                    run_id=run_id,
                    workflow_revision=1,
                    node_id="approval",
                    prompt="Continue?",
                    status=approval_status or ("approved" if approved_resolution else "pending"),
                    decided_at=now if approved_resolution else None,
                )
            )
            db.add(
                WorkflowCheckpoint(
                    id=uuid4(),
                    run_id=run_id,
                    workflow_revision=1,
                    sequence=1,
                    completed_node_ids=["start", "approval"] if complete_resolution else ["start"],
                    node_outputs={},
                    pending_node_id=None if complete_resolution else "approval",
                    interrupt=None if complete_resolution else {"type": "approval_required"},
                )
            )
        await db.commit()
    return workspace_id, run_id


async def _cleanup(factory: async_sessionmaker[AsyncSession], workspaces: list[UUID]) -> None:
    if not workspaces:
        return
    async with factory() as db:
        await db.execute(Workspace.__table__.delete().where(Workspace.id.in_(workspaces)))
        await db.commit()


@pytest.mark.anyio
async def test_recovery_selection_accepts_only_valid_states_and_reserves_rows(
    atomic6_factory,
) -> None:
    workspaces: list[UUID] = []
    try:
        eligible: list[UUID] = []
        for status, lease, approved, complete in (
            ("pending", None, False, False),
            ("pending", "expired", False, False),
            ("running", "expired", False, False),
            ("paused", None, True, True),
        ):
            workspace_id, run_id = await _create_run(
                atomic6_factory,
                status=status,
                lease=lease,
                approved_resolution=approved,
                complete_resolution=complete,
            )
            workspaces.append(workspace_id)
            eligible.append(run_id)
        json_null_run_id = eligible[-1]
        workspace_id, sql_null_run_id = await _create_run(
            atomic6_factory,
            status="paused",
            approved_resolution=True,
            complete_resolution=True,
        )
        workspaces.append(workspace_id)
        async with atomic6_factory() as db:
            await db.execute(
                text("UPDATE workflow_checkpoints SET interrupt = NULL WHERE run_id = :run_id"),
                {"run_id": sql_null_run_id},
            )
            await db.commit()
        eligible.append(sql_null_run_id)

        for status, lease, approved, complete, approval_status in (
            ("running", "valid", False, False, None),
            ("paused", "valid", True, True, None),
            ("paused", None, False, True, None),
            ("paused", None, True, True, "rejected"),
            ("paused", None, True, False, None),
            ("completed", None, False, False, None),
            ("failed", None, False, False, None),
            ("cancelled", None, False, False, None),
        ):
            workspace_id, _ = await _create_run(
                atomic6_factory,
                status=status,
                lease=lease,
                approved_resolution=approved,
                complete_resolution=complete,
                approval_status=approval_status,
            )
            workspaces.append(workspace_id)

        async with atomic6_factory() as db, db.begin():
            selected = await run_repo.list_recoverable_workflow_run_ids_for_update(
                db, limit=32, redispatch_delay=_DELAY
            )
        assert set(selected) == set(eligible)
        async with atomic6_factory() as db:
            reserved = list(
                (await db.scalars(select(WorkflowRun).where(WorkflowRun.id.in_(eligible)))).all()
            )
        assert all(row.recovery_last_dispatched_at is not None for row in reserved)
        assert all(row.recovery_next_dispatch_at is not None for row in reserved)
        async with atomic6_factory() as db:
            json_storage = (
                (
                    await db.execute(
                        text(
                            """
                        SELECT interrupt IS NULL AS is_sql_null,
                               interrupt = 'null'::jsonb AS is_json_null,
                               jsonb_typeof(interrupt) AS json_type
                        FROM workflow_checkpoints
                        WHERE run_id = :run_id
                        ORDER BY sequence DESC
                        LIMIT 1
                        """
                        ),
                        {"run_id": json_null_run_id},
                    )
                )
                .mappings()
                .one()
            )
            sql_storage = (
                (
                    await db.execute(
                        text(
                            """
                        SELECT interrupt IS NULL AS is_sql_null,
                               interrupt = 'null'::jsonb AS is_json_null,
                               jsonb_typeof(interrupt) AS json_type
                        FROM workflow_checkpoints
                        WHERE run_id = :run_id
                        ORDER BY sequence DESC
                        LIMIT 1
                        """
                        ),
                        {"run_id": sql_null_run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(json_storage) == {
                "is_sql_null": False,
                "is_json_null": True,
                "json_type": "null",
            }
            assert dict(sql_storage) == {
                "is_sql_null": True,
                "is_json_null": False,
                "json_type": None,
            }

            paused_run = await db.get(WorkflowRun, json_null_run_id)
            approval = await db.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == json_null_run_id)
            )
            latest = await db.scalar(
                select(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.run_id == json_null_run_id)
                .order_by(WorkflowCheckpoint.sequence.desc())
                .limit(1)
            )
            assert paused_run is not None and paused_run.status == "paused"
            assert approval is not None and approval.status == "approved"
            assert latest is not None and latest.sequence == 1
            assert latest.pending_node_id is None and latest.interrupt is None
            assert "approval" in latest.completed_node_ids
            json_null_lease = await claim_repo.claim_execution(
                db, json_null_run_id, timedelta(seconds=30)
            )
            sql_null_lease = await claim_repo.claim_execution(
                db, sql_null_run_id, timedelta(seconds=30)
            )
            assert json_null_lease is not None
            assert sql_null_lease is not None
            await db.commit()
        async with atomic6_factory() as db:
            json_null_claimed = await db.get(WorkflowRun, json_null_run_id)
            sql_null_claimed = await db.get(WorkflowRun, sql_null_run_id)
        assert json_null_claimed is not None and json_null_claimed.status == "running"
        assert sql_null_claimed is not None and sql_null_claimed.status == "running"
    finally:
        await _cleanup(atomic6_factory, workspaces)


@pytest.mark.anyio
async def test_recovery_reservation_is_fair_and_becomes_due_again(atomic6_factory) -> None:
    workspaces: list[UUID] = []
    try:
        run_ids: list[UUID] = []
        for _ in range(5):
            workspace_id, run_id = await _create_run(atomic6_factory, status="pending")
            workspaces.append(workspace_id)
            run_ids.append(run_id)

        batches: list[list[UUID]] = []
        for _ in range(3):
            async with atomic6_factory() as db, db.begin():
                batches.append(
                    await run_repo.list_recoverable_workflow_run_ids_for_update(
                        db, limit=2, redispatch_delay=_DELAY
                    )
                )
        assert batches[0] == run_ids[:2]
        assert batches[1] == run_ids[2:4]
        assert batches[2] == run_ids[4:]

        async with atomic6_factory() as db:
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id.in_(run_ids[:2]))
                .values(recovery_next_dispatch_at=text("clock_timestamp() - INTERVAL '1 second'"))
            )
            await db.commit()
        async with atomic6_factory() as db, db.begin():
            due_again = await run_repo.list_recoverable_workflow_run_ids_for_update(
                db, limit=2, redispatch_delay=_DELAY
            )
        assert due_again == run_ids[:2]
    finally:
        await _cleanup(atomic6_factory, workspaces)


@pytest.mark.anyio
async def test_concurrent_scanners_skip_locked_and_do_not_double_reserve(atomic6_factory) -> None:
    workspaces: list[UUID] = []
    try:
        run_ids: list[UUID] = []
        for _ in range(4):
            workspace_id, run_id = await _create_run(atomic6_factory, status="pending")
            workspaces.append(workspace_id)
            run_ids.append(run_id)
        first_reserved = asyncio.Event()
        release_first = asyncio.Event()

        async def reserve_first() -> list[UUID]:
            async with atomic6_factory() as db, db.begin():
                selected = await run_repo.list_recoverable_workflow_run_ids_for_update(
                    db, limit=2, redispatch_delay=_DELAY
                )
                first_reserved.set()
                await release_first.wait()
                return selected

        first_task = asyncio.create_task(reserve_first())
        await first_reserved.wait()
        async with atomic6_factory() as db, db.begin():
            second = await run_repo.list_recoverable_workflow_run_ids_for_update(
                db, limit=2, redispatch_delay=_DELAY
            )
        release_first.set()
        first = await first_task
        assert set(first).isdisjoint(second)
        assert set(first) | set(second) == set(run_ids)
    finally:
        await _cleanup(atomic6_factory, workspaces)


@pytest.mark.anyio
async def test_publish_failure_leaves_a_durably_reschedulable_run(atomic6_factory) -> None:
    class FailingDispatcher:
        async def dispatch(self, _job) -> None:
            raise ConnectionError("dedicated broker unavailable")

    workspace_id, run_id = await _create_run(atomic6_factory, status="pending")
    try:
        scanner = WorkflowRecoveryScanner(
            atomic6_factory,
            FailingDispatcher(),
            batch_size=1,
            redispatch_delay=_DELAY,
        )
        failed = await scanner.scan_once()
        assert (failed.scanned, failed.dispatched, failed.failed) == (1, 0, 1)
        async with atomic6_factory() as db:
            row = await db.get(WorkflowRun, run_id)
            assert row is not None and row.recovery_next_dispatch_at is not None
            await db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .values(recovery_next_dispatch_at=text("clock_timestamp() - INTERVAL '1 second'"))
            )
            await db.commit()
        async with atomic6_factory() as db, db.begin():
            assert await run_repo.list_recoverable_workflow_run_ids_for_update(
                db, limit=1, redispatch_delay=_DELAY
            ) == [run_id]
    finally:
        await _cleanup(atomic6_factory, [workspace_id])
