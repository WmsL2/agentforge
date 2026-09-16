"""Opt-in PostgreSQL proofs that paused approval runs survive process restart."""

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.user import User, UserRole
from app.db.models.workflow import ApprovalRequest, Workflow, WorkflowCheckpoint, WorkflowRun
from app.schemas.workflow.definition import WorkflowCreate, WorkflowGraphSchema
from app.services.workflow import (
    ApprovalNodeExecutor,
    DeterministicNodeExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    WorkflowApprovalService,
    WorkflowEngine,
    WorkflowRunService,
    WorkflowService,
    deserialize_workflow_graph,
)
from app.services.workflow.application.run.durability import DurableWorkflowExecutionPersistence
from app.services.workflow.execution.checkpoint import deserialize_workflow_checkpoint
from app.services.workflow.execution.run import deserialize_workflow_run


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
    """Keep real validation but crash when approval service starts downstream resume."""

    async def resume(self, *args: Any, **kwargs: Any):
        raise SimulatedProcessCrash("process stopped after resolution checkpoint commit")


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
) -> tuple[UUID, UUID, UUID]:
    """Commit phase one and return IDs only after Session A has closed."""
    async with session_factory() as session:
        user = User(id=uuid4(), email=f"recovery-{uuid4()}@example.test", role=UserRole.USER.value)
        session.add(user)
        await session.commit()
        workflow_service = WorkflowService(session)
        workflow = await workflow_service.create_workflow(
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
        return user.id, workflow.id, run_id


async def cleanup_case(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID, workflow_id: UUID
) -> None:
    """Delete only this test's aggregate, relying on its database cascades."""
    async with session_factory() as session:
        await session.execute(delete(Workflow).where(Workflow.id == workflow_id))
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
    user_id, workflow_id, run_id = await create_paused_run(postgres_restart_session_factory)
    try:
        await revise_current_workflow(postgres_restart_session_factory, workflow_id)

        guard = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session, WorkflowService(session), WorkflowEngine(guard)
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
        await cleanup_case(postgres_restart_session_factory, user_id, workflow_id)


@pytest.mark.anyio
async def test_recovery_after_crash_uses_committed_resolution_checkpoint(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workflow_id, run_id = await create_paused_run(postgres_restart_session_factory)
    try:
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session, WorkflowService(session), CrashBeforeDownstreamEngine(RecordingExecutor())
            )
            approval = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            with pytest.raises(SimulatedProcessCrash):
                await approval_service.approve(workflow_id, run_id, approval.id, user_id)

        guard = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session:
            db_run = await session.get(WorkflowRun, run_id)
            db_workflow = await session.get(Workflow, workflow_id)
            db_approval = await session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored_checkpoints = await checkpoints(session, run_id)
            assert db_run is not None and db_run.status == "paused"
            assert db_workflow is not None
            assert db_approval is not None and db_approval.status == "approved"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3, 4]
            latest = stored_checkpoints[-1]
            assert latest.completed_node_ids == ["start", "before", "approval"]
            assert latest.pending_node_id is None and latest.interrupt is None

            run = deserialize_workflow_run(
                run_id=db_run.id,
                workflow_id=db_run.workflow_id,
                workflow_revision=db_run.workflow_revision,
                status=db_run.status,
                input=db_run.input,
                node_outputs=db_run.node_outputs,
                output=db_run.output,
                error=db_run.error,
                started_at=db_run.started_at,
                finished_at=db_run.finished_at,
            )
            definition = deserialize_workflow_graph(
                db_run.definition_snapshot,
                workflow_id=db_run.workflow_id,
                name=db_workflow.name,
                description=db_workflow.description,
                revision=db_run.workflow_revision,
            )
            checkpoint = deserialize_workflow_checkpoint(
                checkpoint_id=latest.id,
                run_id=latest.run_id,
                workflow_revision=latest.workflow_revision,
                sequence=latest.sequence,
                completed_node_ids=latest.completed_node_ids,
                node_outputs=latest.node_outputs,
                pending_node_id=latest.pending_node_id,
                interrupt=latest.interrupt,
                created_at=latest.created_at,
            )
            persistence = DurableWorkflowExecutionPersistence(
                session, db_run, next_sequence=latest.sequence + 1
            )
            await WorkflowEngine(guard).resume(definition, run, checkpoint, persistence=persistence)

        async with postgres_restart_session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            stored_checkpoints = await checkpoints(session, run_id)
            assert run is not None and run.status == "completed"
            assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3, 4, 5, 6]
        assert guard.calls == ["after", "end"]
    finally:
        await cleanup_case(postgres_restart_session_factory, user_id, workflow_id)


@pytest.mark.anyio
async def test_approval_restart_reject_cancels_without_execution_or_checkpoint(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workflow_id, run_id = await create_paused_run(postgres_restart_session_factory)
    try:
        guard = RecordingExecutor({"start", "before", "approval", "after", "end"})
        async with postgres_restart_session_factory() as session:
            approval_service = WorkflowApprovalService(
                session, WorkflowService(session), WorkflowEngine(guard)
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
        await cleanup_case(postgres_restart_session_factory, user_id, workflow_id)
