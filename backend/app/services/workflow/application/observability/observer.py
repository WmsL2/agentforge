"""Independent-transaction SQLAlchemy observer for workflow execution facts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.workflow.observability.run_step import WorkflowRunStep as DBWorkflowRunStep
from app.db.models.workflow.run.model import WorkflowRun as DBWorkflowRun
from app.repositories.workflow.observability.run_step import (
    create_workflow_run_step,
    get_workflow_run_step_by_id,
    update_workflow_run_step_state,
)
from app.repositories.workflow.observability.trace_event import create_workflow_trace_event
from app.services.workflow.definition.model.domain import WorkflowNode
from app.services.workflow.execution.executor.contract import (
    NodeExecutionContext,
    NodeExecutionOutcome,
    NodeExecutionResult,
)
from app.services.workflow.execution.observability.domain import (
    RunStep,
    RunStepError,
    TraceEvent,
    TraceEventKind,
)
from app.services.workflow.execution.observability.observer.contract import (
    WorkflowObservationContext,
)
from app.services.workflow.execution.observability.serialization import deserialize_run_step


class SQLAlchemyWorkflowExecutionObserver:
    """Persist observability facts in transactions independent of workflow correctness."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start_step(
        self,
        *,
        run_id: UUID,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        # This independent commit precedes executor invocation, so a crash can retain RUNNING.
        async with self._transaction() as session:
            await self._lock_workflow_run(session, run_id)
            next_sequence = await self._next_sequence(session, run_id)
            started_at = datetime.now(UTC)
            step = RunStep(
                id=uuid4(),
                run_id=run_id,
                sequence=next_sequence,
                node_id=node.id,
                node_kind=node.kind,
                input={
                    "workflow_input": dict(execution_context.workflow_input),
                    "upstream_outputs": dict(execution_context.upstream_outputs),
                    "node_outputs": dict(execution_context.node_outputs),
                },
                metadata={},
                started_at=started_at,
            )
            await create_workflow_run_step(session, step=step)
            await create_workflow_trace_event(
                session,
                event=TraceEvent(
                    id=uuid4(),
                    run_id=run_id,
                    step_id=step.id,
                    kind=TraceEventKind.NODE_STARTED,
                    payload={"node_id": node.id, "node_kind": node.kind.value},
                    created_at=started_at,
                ),
            )
            return WorkflowObservationContext(run_id=run_id, step_id=step.id)

    async def complete_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        if context.step_id is None:
            return None
        async with self._transaction() as session:
            step, db_step = await self._load_step(session, context)
            finished_at = datetime.now(UTC)
            step.complete(result.output, result.metadata, at=finished_at)
            await update_workflow_run_step_state(session, db_step=db_step, step=step)
            await create_workflow_trace_event(
                session,
                event=TraceEvent(
                    id=uuid4(),
                    run_id=context.run_id,
                    step_id=context.step_id,
                    kind=TraceEventKind.NODE_COMPLETED,
                    payload={
                        "node_id": step.node_id,
                        "node_kind": step.node_kind.value,
                        "metadata": dict(result.metadata),
                    },
                    created_at=finished_at,
                ),
            )

    async def fail_step(
        self,
        context: WorkflowObservationContext,
        *,
        error: RunStepError,
        metadata: Mapping[str, Any],
    ) -> None:
        if context.step_id is None:
            return None
        async with self._transaction() as session:
            step, db_step = await self._load_step(session, context)
            finished_at = datetime.now(UTC)
            step.fail(error, metadata, at=finished_at)
            await update_workflow_run_step_state(session, db_step=db_step, step=step)
            await create_workflow_trace_event(
                session,
                event=TraceEvent(
                    id=uuid4(),
                    run_id=context.run_id,
                    step_id=context.step_id,
                    kind=TraceEventKind.NODE_FAILED,
                    payload={
                        "node_id": step.node_id,
                        "node_kind": step.node_kind.value,
                        "error": {"code": error.code, "message": error.message},
                        "metadata": dict(metadata),
                    },
                    created_at=finished_at,
                ),
            )

    async def interrupt_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        if context.step_id is None:
            return None
        if result.outcome is not NodeExecutionOutcome.INTERRUPTED or result.interrupt is None:
            raise ValueError("Interrupted observation requires an interrupted node execution result.")
        async with self._transaction() as session:
            step, db_step = await self._load_step(session, context)
            finished_at = datetime.now(UTC)
            step.interrupt(result.output, result.metadata, at=finished_at)
            await update_workflow_run_step_state(session, db_step=db_step, step=step)
            await create_workflow_trace_event(
                session,
                event=TraceEvent(
                    id=uuid4(),
                    run_id=context.run_id,
                    step_id=context.step_id,
                    kind=TraceEventKind.NODE_INTERRUPTED,
                    payload={
                        "node_id": step.node_id,
                        "node_kind": step.node_kind.value,
                        "metadata": dict(result.metadata),
                        "interrupt": {
                            "type": result.interrupt.type,
                            "payload": dict(result.interrupt.payload),
                        },
                    },
                    created_at=finished_at,
                ),
            )

    async def record_event(
        self,
        context: WorkflowObservationContext,
        *,
        kind: TraceEventKind,
        payload: Mapping[str, Any],
    ) -> None:
        async with self._transaction() as session:
            await create_workflow_trace_event(
                session,
                event=TraceEvent(
                    id=uuid4(),
                    run_id=context.run_id,
                    step_id=context.step_id,
                    kind=kind,
                    payload=payload,
                    created_at=datetime.now(UTC),
                ),
            )

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        """Own a short observability transaction without touching request-session state."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                with suppress(Exception):
                    await session.rollback()
                raise

    @staticmethod
    async def _lock_workflow_run(session: AsyncSession, run_id: UUID) -> None:
        result = await session.execute(
            select(DBWorkflowRun.id).where(DBWorkflowRun.id == run_id).with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"Workflow run {run_id} does not exist for observation.")

    @staticmethod
    async def _next_sequence(session: AsyncSession, run_id: UUID) -> int:
        maximum = await session.scalar(
            select(func.max(DBWorkflowRunStep.sequence)).where(DBWorkflowRunStep.run_id == run_id)
        )
        return 1 if maximum is None else maximum + 1

    @staticmethod
    async def _load_step(
        session: AsyncSession,
        context: WorkflowObservationContext,
    ) -> tuple[RunStep, DBWorkflowRunStep]:
        assert context.step_id is not None
        db_step = await get_workflow_run_step_by_id(session, context.step_id)
        if db_step is None:
            raise ValueError(f"Workflow run step {context.step_id} does not exist for observation.")
        if db_step.run_id != context.run_id:
            raise ValueError("Workflow observation context run does not own the requested step.")
        return (
            deserialize_run_step(
                {
                    "id": db_step.id,
                    "run_id": db_step.run_id,
                    "sequence": db_step.sequence,
                    "node_id": db_step.node_id,
                    "node_kind": db_step.node_kind,
                    "status": db_step.status,
                    "input": db_step.input,
                    "output": db_step.output,
                    "error": db_step.error,
                    "metadata": db_step.metadata_,
                    "started_at": db_step.started_at,
                    "finished_at": db_step.finished_at,
                }
            ),
            db_step,
        )
