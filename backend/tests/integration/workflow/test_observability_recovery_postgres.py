"""Opt-in PostgreSQL proofs for v0.6 recovery plus v0.7 observability."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.user import User, UserRole
from app.db.models.workflow import (
    ApprovalRequest,
    Workflow,
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowRunStep,
    WorkflowTraceEvent,
)
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
from app.services.workflow.application.observability import SQLAlchemyWorkflowExecutionObserver
from app.services.workflow.application.run.durability import DurableWorkflowExecutionPersistence
from app.services.workflow.execution.checkpoint import deserialize_workflow_checkpoint
from app.services.workflow.execution.run import deserialize_workflow_run


class SimulatedProcessCrash(BaseException):
    """A test-only crash that WorkflowEngine must not convert into failure history."""


class RecordingExecutor:
    """Execute deterministic nodes while proving durable checkpoints skip prior nodes."""

    def __init__(self, forbidden: Iterable[str] = ()) -> None:
        self.calls: list[str] = []
        self._forbidden = set(forbidden)
        self._deterministic = DeterministicNodeExecutor()
        self._observer = None

    def bind_observer(self, workflow_observer) -> None:
        self._observer = workflow_observer

    async def execute(self, node, context: NodeExecutionContext) -> NodeExecutionResult:
        if node.id in self._forbidden:
            raise AssertionError(f"Recovery re-executed completed node {node.id!r}.")
        self.calls.append(node.id)
        if node.kind.value == "approval":
            return await ApprovalNodeExecutor(observer=self._observer).execute(node, context)
        return await self._deterministic.execute(node, context)


class CrashOnValueExecutor(RecordingExecutor):
    async def execute(self, node, context: NodeExecutionContext) -> NodeExecutionResult:
        if node.id == "value":
            self.calls.append(node.id)
            raise SimulatedProcessCrash("process died during value execution")
        return await super().execute(node, context)


class CrashBeforeDownstreamEngine(WorkflowEngine):
    async def resume(self, *args: Any, **kwargs: Any):
        raise SimulatedProcessCrash("process died after approval resolution checkpoint")


def completed_graph() -> WorkflowGraphSchema:
    return WorkflowGraphSchema.model_validate(
        {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "value", "kind": "value", "config": {"value": "done"}},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start-value", "source": "start", "target": "value"},
                {"id": "value-end", "source": "value", "target": "end"},
            ],
        }
    )


def approval_graph() -> WorkflowGraphSchema:
    return WorkflowGraphSchema.model_validate(
        {
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "before", "kind": "value", "config": {"value": "before"}},
                {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}},
                {"id": "after", "kind": "value", "config": {"value": "after"}},
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


def observer(factory: async_sessionmaker[AsyncSession]) -> SQLAlchemyWorkflowExecutionObserver:
    return SQLAlchemyWorkflowExecutionObserver(factory)


async def create_run(
    factory: async_sessionmaker[AsyncSession], graph: WorkflowGraphSchema, executor: RecordingExecutor
) -> tuple[UUID, UUID, UUID]:
    async with factory() as session:
        user = User(id=uuid4(), email=f"observability-{uuid4()}@example.test", role=UserRole.USER.value)
        session.add(user)
        await session.commit()
        workflow_service = WorkflowService(session)
        workflow = await workflow_service.create_workflow(
            user.id, WorkflowCreate(name="Observability recovery", definition=graph)
        )
        await session.commit()
        workflow_observer = observer(factory)
        executor.bind_observer(workflow_observer)
        run = await WorkflowRunService(
            session, workflow_service, WorkflowEngine(executor, observer=workflow_observer)
        ).execute_workflow(workflow.id, user.id, {})
        return user.id, workflow.id, run.id


async def steps(session: AsyncSession, run_id: UUID) -> list[WorkflowRunStep]:
    return list(
        (
            await session.scalars(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .order_by(WorkflowRunStep.sequence)
            )
        ).all()
    )


async def events(session: AsyncSession, run_id: UUID) -> list[WorkflowTraceEvent]:
    return list(
        (
            await session.scalars(
                select(WorkflowTraceEvent)
                .where(WorkflowTraceEvent.run_id == run_id)
                .order_by(WorkflowTraceEvent.created_at, WorkflowTraceEvent.id)
            )
        ).all()
    )


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


async def cleanup(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, workflow_id: UUID, run_id: UUID
) -> None:
    async with factory() as session:
        await session.execute(delete(Workflow).where(Workflow.id == workflow_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()
        assert await session.scalar(
            select(func.count()).select_from(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
        ) == 0
        assert await session.scalar(
            select(func.count()).select_from(WorkflowTraceEvent).where(WorkflowTraceEvent.run_id == run_id)
        ) == 0


async def resume_from_database(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    workflow_id: UUID,
    run_id: UUID,
    executor: RecordingExecutor,
) -> None:
    db_run = await session.get(WorkflowRun, run_id)
    db_workflow = await session.get(Workflow, workflow_id)
    latest = (await checkpoints(session, run_id))[-1]
    assert db_run is not None and db_workflow is not None
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
    persistence = DurableWorkflowExecutionPersistence(session, db_run, next_sequence=latest.sequence + 1)
    await WorkflowEngine(executor, observer=observer(factory)).resume(
        definition, run, checkpoint, persistence=persistence
    )


@pytest.mark.anyio
async def test_completed_workflow_observability_survives_cross_connection_reads(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = RecordingExecutor()
    user_id, workflow_id, run_id = await create_run(
        postgres_restart_session_factory, completed_graph(), executor
    )
    try:
        async with postgres_restart_session_factory() as session_b:
            run = await session_b.get(WorkflowRun, run_id)
            stored_checkpoints = await checkpoints(session_b, run_id)
            stored_steps = await steps(session_b, run_id)
            stored_events = await events(session_b, run_id)
        async with postgres_restart_session_factory() as session_c:
            assert await session_c.get(WorkflowRun, run_id) is not None
            assert [step.id for step in await steps(session_c, run_id)] == [
                step.id for step in stored_steps
            ]

        assert executor.calls == ["start", "value", "end"]
        assert run is not None and run.status == "completed"
        assert [checkpoint.sequence for checkpoint in stored_checkpoints] == [1, 2, 3]
        assert stored_checkpoints[-1].completed_node_ids == ["start", "value", "end"]
        assert [step.sequence for step in stored_steps] == [1, 2, 3]
        assert [step.node_id for step in stored_steps] == ["start", "value", "end"]
        assert [step.status for step in stored_steps] == ["completed", "completed", "completed"]
        assert all(step.finished_at is not None for step in stored_steps)
        event_kinds_by_step = {
            step.id: [event.kind for event in stored_events if event.step_id == step.id]
            for step in stored_steps
        }
        assert all(kinds == ["node_started", "node_completed"] for kinds in event_kinds_by_step.values())
    finally:
        await cleanup(postgres_restart_session_factory, user_id, workflow_id, run_id)


@pytest.mark.anyio
async def test_approval_restart_preserves_interrupted_history_and_appends_downstream_steps(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phase_a = RecordingExecutor()
    user_id, workflow_id, run_id = await create_run(
        postgres_restart_session_factory, approval_graph(), phase_a
    )
    try:
        async with postgres_restart_session_factory() as session_a:
            stored_steps = await steps(session_a, run_id)
            stored_events = await events(session_a, run_id)
            assert [step.status for step in stored_steps] == ["completed", "completed", "interrupted"]
            assert stored_steps[-1].finished_at is not None
            approval_step = stored_steps[-1]
            assert [event.kind for event in stored_events if event.step_id == approval_step.id] == [
                "node_started",
                "approval_requested",
                "node_interrupted",
            ]

        phase_b = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session_b:
            approval_service = WorkflowApprovalService(
                session_b,
                WorkflowService(session_b),
                WorkflowEngine(phase_b, observer=observer(postgres_restart_session_factory)),
                observer=observer(postgres_restart_session_factory),
            )
            pending = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            await approval_service.approve(workflow_id, run_id, pending.id, user_id)

        async with postgres_restart_session_factory() as session_c:
            stored_steps = await steps(session_c, run_id)
            stored_events = await events(session_c, run_id)
            stored_checkpoints = await checkpoints(session_c, run_id)
            assert [step.sequence for step in stored_steps] == [1, 2, 3, 4, 5]
            assert [step.node_id for step in stored_steps] == [
                "start",
                "before",
                "approval",
                "after",
                "end",
            ]
            assert [step.status for step in stored_steps] == [
                "completed",
                "completed",
                "interrupted",
                "completed",
                "completed",
            ]
            approved = [event for event in stored_events if event.kind == "approval_approved"]
            assert len(approved) == 1 and approved[0].step_id is None
            assert stored_checkpoints[3].completed_node_ids == ["start", "before", "approval"]
            assert stored_checkpoints[3].pending_node_id is None
            assert stored_checkpoints[3].interrupt is None
            assert stored_checkpoints[-1].completed_node_ids == [
                "start",
                "before",
                "approval",
                "after",
                "end",
            ]
        assert phase_a.calls == ["start", "before", "approval"]
        assert phase_b.calls == ["after", "end"]
    finally:
        await cleanup(postgres_restart_session_factory, user_id, workflow_id, run_id)


@pytest.mark.anyio
async def test_crash_after_resolution_checkpoint_recovers_without_duplicate_observability_steps(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, workflow_id, run_id = await create_run(
        postgres_restart_session_factory, approval_graph(), RecordingExecutor()
    )
    try:
        async with postgres_restart_session_factory() as session_b:
            crash_engine = CrashBeforeDownstreamEngine(
                RecordingExecutor(), observer=observer(postgres_restart_session_factory)
            )
            approval_service = WorkflowApprovalService(
                session_b,
                WorkflowService(session_b),
                crash_engine,
                observer=observer(postgres_restart_session_factory),
            )
            pending = await approval_service.get_pending_approval(workflow_id, run_id, user_id)
            with pytest.raises(SimulatedProcessCrash):
                await approval_service.approve(workflow_id, run_id, pending.id, user_id)

        phase_c = RecordingExecutor({"start", "before", "approval"})
        async with postgres_restart_session_factory() as session_c:
            run = await session_c.get(WorkflowRun, run_id)
            approval = await session_c.scalar(
                select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
            )
            stored_steps = await steps(session_c, run_id)
            stored_events = await events(session_c, run_id)
            latest = (await checkpoints(session_c, run_id))[-1]
            assert run is not None and run.status == "paused"
            assert approval is not None and approval.status == "approved"
            assert latest.completed_node_ids == ["start", "before", "approval"]
            assert latest.pending_node_id is None and latest.interrupt is None
            assert [step.node_id for step in stored_steps] == ["start", "before", "approval"]
            assert any(event.kind == "approval_approved" and event.step_id is None for event in stored_events)
            await resume_from_database(
                session_c, postgres_restart_session_factory, workflow_id, run_id, phase_c
            )

        async with postgres_restart_session_factory() as session_d:
            stored_steps = await steps(session_d, run_id)
            assert [step.sequence for step in stored_steps] == [1, 2, 3, 4, 5]
            assert [step.node_id for step in stored_steps] == [
                "start",
                "before",
                "approval",
                "after",
                "end",
            ]
        assert phase_c.calls == ["after", "end"]
    finally:
        await cleanup(postgres_restart_session_factory, user_id, workflow_id, run_id)


@pytest.mark.anyio
async def test_process_crash_leaves_stale_running_step_with_only_started_trace(
    postgres_restart_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = CrashOnValueExecutor()
    user_id = workflow_id = run_id = None
    try:
        async with postgres_restart_session_factory() as session_a:
            user = User(id=uuid4(), email=f"crash-{uuid4()}@example.test", role=UserRole.USER.value)
            session_a.add(user)
            await session_a.commit()
            workflow_service = WorkflowService(session_a)
            workflow = await workflow_service.create_workflow(
                user.id, WorkflowCreate(name="Crash semantics", definition=completed_graph())
            )
            await session_a.commit()
            with pytest.raises(SimulatedProcessCrash):
                await WorkflowRunService(
                    session_a,
                    workflow_service,
                    WorkflowEngine(executor, observer=observer(postgres_restart_session_factory)),
                ).execute_workflow(workflow.id, user.id, {})
            user_id, workflow_id = user.id, workflow.id
            run_id = (await session_a.scalar(select(WorkflowRun.id).where(WorkflowRun.workflow_id == workflow.id)))
            assert run_id is not None

        async with postgres_restart_session_factory() as session_b:
            run = await session_b.get(WorkflowRun, run_id)
            latest = (await checkpoints(session_b, run_id))[-1]
            stored_steps = await steps(session_b, run_id)
            stored_events = await events(session_b, run_id)
            value_step = next(step for step in stored_steps if step.node_id == "value")
            assert run is not None and run.node_outputs == {"start": {}}
            assert latest.completed_node_ids == ["start"]
            assert latest.pending_node_id == "value"
            assert [step.status for step in stored_steps] == ["completed", "running"]
            assert value_step.finished_at is None and value_step.error is None
            assert [event.kind for event in stored_events if event.step_id == value_step.id] == [
                "node_started"
            ]
    finally:
        if user_id is not None and workflow_id is not None and run_id is not None:
            await cleanup(postgres_restart_session_factory, user_id, workflow_id, run_id)
