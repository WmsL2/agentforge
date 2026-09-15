"""Execution-layer durability boundary for successful workflow nodes."""

from collections.abc import Mapping
from typing import Any, Protocol

from app.services.workflow.execution.run.domain import WorkflowRun


class WorkflowExecutionPersistence(Protocol):
    """Persist one successful node before execution can continue."""

    async def persist_node_completion(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str | None,
    ) -> None:
        """Durably record current run state and its recovery checkpoint."""

    async def persist_interruption(
        self,
        run: WorkflowRun,
        *,
        completed_node_ids: tuple[str, ...],
        pending_node_id: str,
        interrupt: Mapping[str, Any],
    ) -> None:
        """Durably record a paused run and its interruption checkpoint."""
