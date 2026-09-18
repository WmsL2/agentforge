"""No-op workflow execution observer for observability-free execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.services.workflow.execution.observability.domain import RunStepError, TraceEventKind
from app.services.workflow.execution.observability.observer.contract import (
    WorkflowObservationContext,
)

if TYPE_CHECKING:
    from app.services.workflow.definition.model.domain import WorkflowNode
    from app.services.workflow.execution.executor.contract import (
        NodeExecutionContext,
        NodeExecutionResult,
    )


class NoOpWorkflowExecutionObserver:
    """Satisfy the observer boundary without recording or mutating anything."""

    async def start_step(
        self,
        *,
        run_id: UUID,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        return WorkflowObservationContext(run_id=run_id)

    async def complete_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        return None

    async def fail_step(
        self,
        context: WorkflowObservationContext,
        *,
        error: RunStepError,
        metadata: Mapping[str, Any],
    ) -> None:
        return None

    async def interrupt_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        return None

    async def record_event(
        self,
        context: WorkflowObservationContext,
        *,
        kind: TraceEventKind,
        payload: Mapping[str, Any],
    ) -> None:
        return None
