"""Opt-in PostgreSQL proofs that paused approval runs survive process restart."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.user import User, UserRole
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowCheckpoint, WorkflowRun
from app.repositories import workspace as workspace_repo
from app.schemas.workflow.definition import WorkflowCreate, WorkflowGraphSchema
from app.services.workflow import (
    ApprovalNodeExecutor,
    BackgroundRunExecutor,
    DeterministicNodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowApprovalService,
    WorkflowEngine,
    WorkflowRecoveryScanner,
    WorkflowRunService,
    WorkflowService,
)
from app.services.workflow.application.background.claim_service import WorkflowExecutionClaimService
from app.services.workflow.application.background.domain import WorkflowExecutionJob
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole


class SimulatedProcessCrash(RuntimeError):
    """Represents a process dying after the resolution checkpoint commits."""


class RecordingExecutor:
    """Record execution and reject nodes that a durable checkpoint must skip."""

    def __init__(self, forbidden: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._forbidden = forbidden or set()
        self._deterministic = DeterministicNodeExecutor()
        self._approval = ApprovalNodeExecutor()

    async def execute(self, node, context: NodeExecutionContext) -> NodeExecutionResult:
        if node.id in self._forbidden:
            raise AssertionError(f"Durable recovery re-executed completed node {node.id!r}.")
        self.calls.append(node.id)
        if node.kind.value == "approval":
            return await self._approval.execute(node, context)
        return await self._deterministic.execute(node, context)


class CrashBeforeDownstreamEngine(WorkflowEngine):
    """Keep validation but crash after the committed synchronous claim."""

    async def recover_running(self, *args: Any, **kwargs: Any):
        raise SimulatedProcessCrash("process stopped after resolution checkpoint and claim commit")


class BlockingDownstreamExecutor(RecordingExecutor):
    """Pause the first downstream node after the synchronous claim commits."""

    def __init__(self) -> None:
        super().__init__({"start", "before", "approval"})
        self.after_started = asyncio.Event()
        self.allow_finish = asyncio.Event()

    async def execute(self, node, context: NodeExecutionContext) -> NodeExecutionResult:
        if node.id == "after":
            self.after_started.set()
            await self.allow_finish.wait()
        return await super().execute(node, context)


class RecordingRecoveryDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[UUID] = []

    async def dispatch(self, job) -> None:
        self.run_ids.append(job.run_id)


def graph(after_value: str = "after-v1") -> WorkflowGraphSchema:
    return WorkflowGraphSchema.model_validate(
        {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "before", "kind": "value", "config": {"value": "before-v1"}},
                {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}},
                {"id": "after", "kind": "value", "config": {"value": after_value}},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start-before", "source": "start", "target": "before"},
                {"id": "before-approval", "source": "before", "target": "approval"},
                {"id": "approval-after", "source": "approval", "target": "after"},
                {"id": "after-end", "source": "after", "target": "end"},
            ],
        }
    )


async def create_paused_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID, UUID]:
    """Commit phase one and return IDs only after Session A has closed."""
    async with session_factory() as session:
        user = User(id=uuid4(), email=f"recovery-{uuid4()}@example.test", role=UserRole.USER.value)
        session.add(user)
        await session.commit()
        workspace = await workspace_repo.create_workspace(
            session, name="Durable recovery", created_by_user_id=user.id
        )
        await workspace_repo.create_membership(
            session, workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER
        )
        workflow_service = WorkflowService(session, WorkspaceAuthorizationService(session))
        workflow = await workflow_service.create_workflow(
            workspace.id,
            user.id,
            WorkflowCreate(name="Durable recovery", definition=graph()),
        )
        await session.commit()
        executor = RecordingExecutor()
        run = await WorkflowRunService(
            session, workflow_service, WorkflowEngine(executor)
        ).execute_workflow(
            workflow.id,
            user.id,
            {},
        )
        run_id = run.id
        assert executor.calls == ["start", "before", "approval"]
        approval = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
        )
        checkpoint = await session.scalar(
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.run_id == run_id)
            .order_by(WorkflowCheckpoint.sequence.desc())
        )
        assert approval is not None and approval.status == "pending"
        assert checkpoint is not None
        assert checkpoint.sequence == 3
        assert checkpoint.completed_node_ids == ["start", "before"]
        assert checkpoint.pending_node_id == "approval"
        assert (
            checkpoint.interrupt is not None and checkpoint.interrupt["type"] == "approval_required"
        )
        return user.id, workspace.id, workflow.id, run_id


async def cleanup_case(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID, workspace_id: UUID
) -> None:
    """Delete only this test's aggregate, relying on its database cascades."""
    async with session_factory() as session:
        await workspace_repo.delete_workspace(session, workspace_id)
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


async def checkpoints(session: AsyncSession, run_id: UUID) -> list[WorkflowCheckpoint]:
    return list(
        (
            await session.scalars(
                select(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.run_id == run_id)
                .order_by(WorkflowCheckpoint.sequence)
            )
        ).all()
    )


async def revise_current_workflow(
    session_factory: async_sessionmaker[AsyncSession], workflow_id: UUID
) -> None:
    async with session_factory() as session:
        workflow = await session.get(Workflow, workflow_id)
        assert workflow is not None
        definition = deepcopy(workflow.definition)
        next(node for node in definition["nodes"] if node["id"] == "after")["config"]["value"] = (
            "after-v2"
        )
        workflow.definition = definition
        workflow.revision += 1
        await session.commit()


@pytest.mark.anyio
async def test_approval_restart_recovers_from_committed_snapshot_and_checkpoint(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workspace_id, workflow_id, run_id = await create_paused_run(
        postgres_restart_session_factory
    )
    try:
        await revise_current_workflow(postgres_restart_session_factory, workflow_id)

        guard = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session,
                WorkflowService(session, WorkspaceAuthorizationService(session)),
                WorkflowEngine(guard),
                session_factory=postgres_restart_session_factory,
            )
            approval = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            await approval_service.approve(
                workflow_id, run_id, approval.id, user_id, note="approved"
            )

        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored_checkpoints = await checkpoints(session, run_id)
            assert run is not None and run.status == "completed"
            assert approval is not None and approval.status == "approved"
            assert run.node_outputs["after"] == "after-v1"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3, 4, 5, 6]
            assert stored_checkpoints[3].completed_node_ids == ["start", "before", "approval"]
            assert stored_checkpoints[3].pending_node_id is None
            assert stored_checkpoints[3].interrupt is None
            assert stored_checkpoints[3].node_outputs["approval"]["decision"] == "approved"
            assert stored_checkpoints[-1].completed_node_ids == [
                "start",
                "before",
                "approval",
                "after",
                "end",
            ]
            assert stored_checkpoints[-1].pending_node_id is None
            assert stored_checkpoints[-1].interrupt is None
        assert guard.calls == ["after", "end"]
    finally:
        await cleanup_case(postgres_restart_session_factory, user_id, workspace_id)


@pytest.mark.anyio
async def test_recovery_after_crash_uses_committed_resolution_checkpoint(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workspace_id, workflow_id, run_id = await create_paused_run(
        postgres_restart_session_factory
    )
    try:
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session,
                WorkflowService(session, WorkspaceAuthorizationService(session)),
                CrashBeforeDownstreamEngine(RecordingExecutor()),
                session_factory=postgres_restart_session_factory,
            )
            approval = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            with pytest.raises(SimulatedProcessCrash):
                await approval_service.approve(workflow_id, run_id, approval.id, user_id)

        guard = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session:
            db_run = await session.get(WorkflowRun, run_id)
            db_approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored_checkpoints = await checkpoints(session, run_id)
            assert db_run is not None and db_run.status == "running"
            assert db_run.execution_claim_token is not None
            assert db_run.execution_lease_expires_at is not None
            assert db_approval is not None and db_approval.status == "approved"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3, 4]
            latest = stored_checkpoints[-1]
            assert latest.completed_node_ids == ["start", "before", "approval"]
            assert latest.pending_node_id is None and latest.interrupt is None

            await session.execute(
                text(
                    "UPDATE workflow_runs "
                    "SET execution_lease_expires_at = clock_timestamp() - INTERVAL '1 second' "
                    "WHERE id = :run_id"
                ),
                {"run_id": run_id},
            )
            await session.commit()

        result = await BackgroundRunExecutor(
            postgres_restart_session_factory,
            WorkflowEngine(guard),
            lease_duration=timedelta(seconds=30),
        ).execute(WorkflowExecutionJob(run_id))
        assert result.status.value == "completed"

        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            stored_checkpoints = await checkpoints(session, run_id)
            assert run is not None and run.status == "completed"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3, 4, 5, 6]
        assert guard.calls == ["after", "end"]
    finally:
        await cleanup_case(postgres_restart_session_factory, user_id, workspace_id)


@pytest.mark.anyio
async def test_sync_approval_claim_excludes_scanner_and_second_worker_until_completion(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workspace_id, workflow_id, run_id = await create_paused_run(
        postgres_restart_session_factory
    )
    executor = BlockingDownstreamExecutor()
    try:

        async def approve() -> None:
            async with postgres_restart_session_factory() as session:
                service = WorkflowApprovalService(
                    session,
                    WorkflowService(session, WorkspaceAuthorizationService(session)),
                    WorkflowEngine(executor),
                    session_factory=postgres_restart_session_factory,
                    lease_duration=timedelta(seconds=30),
                )
                approval = await service.get_pending_approval(workflow_id, run_id, user_id)
                await service.approve(workflow_id, run_id, approval.id, user_id, note="approved")

        approving = asyncio.create_task(approve())
        await asyncio.wait_for(executor.after_started.wait(), timeout=10)

        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored = await checkpoints(session, run_id)
        assert run is not None and run.status == "running"
        assert run.execution_claim_token is not None and run.execution_claim_generation == 1
        assert run.execution_lease_expires_at is not None
        assert approval is not None and approval.status == "approved"
        assert [checkpoint.sequence for checkpoint in stored] == [1, 2, 3, 4]
        assert stored[-1].completed_node_ids == ["start", "before", "approval"]
        assert stored[-1].pending_node_id is None and stored[-1].interrupt is None

        dispatcher = RecordingRecoveryDispatcher()
        scanner = WorkflowRecoveryScanner(
            postgres_restart_session_factory,
            dispatcher,
            batch_size=10,
            redispatch_delay=timedelta(seconds=60),
        )
        result = await scanner.scan_once()
        assert (result.scanned, result.dispatched, result.skipped, result.failed) == (0, 0, 0, 0)
        assert dispatcher.run_ids == []
        async with postgres_restart_session_factory() as session:
            assert (
                await WorkflowExecutionClaimService(session).claim(run_id, timedelta(seconds=30))
            ) is None

        executor.allow_finish.set()
        await asyncio.wait_for(approving, timeout=10)
        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored = await checkpoints(session, run_id)
        assert run is not None and run.status == "completed"
        assert run.execution_claim_generation == 1
        assert run.execution_claim_token is None and run.execution_lease_expires_at is None
        assert approval is not None and approval.status == "approved"
        assert [checkpoint.sequence for checkpoint in stored] == [1, 2, 3, 4, 5, 6]
        assert executor.calls == ["after", "end"]
    finally:
        executor.allow_finish.set()
        await cleanup_case(postgres_restart_session_factory, user_id, workspace_id)


@pytest.mark.anyio
async def test_approval_restart_reject_cancels_without_execution_or_checkpoint(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workspace_id, workflow_id, run_id = await create_paused_run(
        postgres_restart_session_factory
    )
    try:
        guard = RecordingExecutor({"start", "before", "approval", "after", "end"})
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session,
                WorkflowService(session, WorkspaceAuthorizationService(session)),
                WorkflowEngine(guard),
            )
            approval = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            await approval_service.reject(
                workflow_id, run_id, approval.id, user_id, note="rejected"
            )

        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored_checkpoints = await checkpoints(session, run_id)
            assert run is not None and run.status == "cancelled" and run.finished_at is not None
            assert approval is not None and approval.status == "rejected"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3]
            assert stored_checkpoints[-1].pending_node_id == "approval"
            assert stored_checkpoints[-1].interrupt is not None
            assert stored_checkpoints[-1].interrupt["type"] == "approval_required"
        assert guard.calls == []
    finally:
        await cleanup_case(postgres_restart_session_factory, user_id, workspace_id)
