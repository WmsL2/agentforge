"""Framework-independent contracts for observing workflow execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from app.services.workflow.execution.observability.domain import RunStepError, TraceEventKind

if TYPE_CHECKING:
    from app.services.workflow.definition.model.domain import WorkflowNode
    from app.services.workflow.execution.executor.contract import (
        NodeExecutionContext,
        NodeExecutionResult,
    )


@dataclass(frozen=True)
class WorkflowObservationContext:
    """Identity context shared across one observed execution attempt."""

    run_id: UUID
    step_id: UUID | None = None


class WorkflowExecutionObserver(Protocol):
    """Observe execution facts without participating in workflow recovery."""

    async def start_step(
        self,
        *,
        run_id: UUID,
        node: WorkflowNode,
        execution_context: NodeExecutionContext,
    ) -> WorkflowObservationContext:
        """Observe that a real node-execution attempt is about to begin."""

    async def complete_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        """Observe successful completion of one execution attempt."""

    async def fail_step(
        self,
        context: WorkflowObservationContext,
        *,
        error: RunStepError,
        metadata: Mapping[str, Any],
    ) -> None:
        """Observe a failed execution attempt."""

    async def interrupt_step(
        self,
        context: WorkflowObservationContext,
        *,
        result: NodeExecutionResult,
    ) -> None:
        """Observe an interrupted execution attempt."""

    async def record_event(
        self,
        context: WorkflowObservationContext,
        *,
        kind: TraceEventKind,
        payload: Mapping[str, Any],
    ) -> None:
        """Observe a non-lifecycle execution-history event."""
