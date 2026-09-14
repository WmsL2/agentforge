"""Pure JSONB-compatible persistence-state mapping for workflow checkpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.workflow.execution.checkpoint.domain import WorkflowCheckpoint


def serialize_workflow_checkpoint_state(checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
    """Map an immutable checkpoint snapshot into JSONB-compatible state."""
    return {
        "completed_node_ids": list(checkpoint.completed_node_ids),
        "node_outputs": dict(checkpoint.node_outputs),
        "pending_node_id": checkpoint.pending_node_id,
        "interrupt": None if checkpoint.interrupt is None else dict(checkpoint.interrupt),
        "created_at": checkpoint.created_at,
    }


def deserialize_workflow_checkpoint(
    *,
    checkpoint_id: UUID,
    run_id: UUID,
    workflow_revision: int,
    sequence: int,
    completed_node_ids: list[str],
    node_outputs: Mapping[str, Any],
    pending_node_id: str | None,
    interrupt: Mapping[str, Any] | None,
    created_at: datetime | None,
) -> WorkflowCheckpoint:
    """Reconstruct a checkpoint while applying its domain invariants."""
    return WorkflowCheckpoint(
        id=checkpoint_id,
        run_id=run_id,
        workflow_revision=workflow_revision,
        sequence=sequence,
        completed_node_ids=tuple(completed_node_ids),
        node_outputs=node_outputs,
        pending_node_id=pending_node_id,
        interrupt=interrupt,
        created_at=created_at,
    )
