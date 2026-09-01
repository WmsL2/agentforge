"""Pure persistence-state mapping for workflow runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.workflow.execution.run.domain import (
    WorkflowRun,
    WorkflowRunError,
    WorkflowRunStatus,
)


def serialize_workflow_run_error(error: WorkflowRunError | None) -> dict[str, Any] | None:
    """Map a structured domain error to JSONB-compatible state."""
    if error is None:
        return None
    return {"code": error.code, "message": error.message, "node_id": error.node_id}


def deserialize_workflow_run_error(
    payload: Mapping[str, Any] | None,
) -> WorkflowRunError | None:
    """Reconstruct a structured domain error from persisted JSONB state."""
    if payload is None:
        return None
    required = ("code", "message", "node_id")
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"Workflow run error payload is missing keys: {', '.join(missing)}")
    code = payload["code"]
    message = payload["message"]
    node_id = payload["node_id"]
    if not isinstance(code, str) or not isinstance(message, str):
        raise TypeError("Workflow run error code and message must be strings.")
    if node_id is not None and not isinstance(node_id, str):
        raise TypeError("Workflow run error node_id must be a string or None.")
    return WorkflowRunError(code=code, message=message, node_id=node_id)


def serialize_workflow_run_state(run: WorkflowRun) -> dict[str, Any]:
    """Map mutable and runtime domain state to SQLAlchemy column values."""
    return {
        "status": run.status.value,
        "input": dict(run.input),
        "node_outputs": dict(run.node_outputs),
        "output": None if run.output is None else dict(run.output),
        "error": serialize_workflow_run_error(run.error),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def deserialize_workflow_run(
    *,
    run_id: UUID,
    workflow_id: UUID,
    workflow_revision: int,
    status: str,
    input: Mapping[str, Any],
    node_outputs: Mapping[str, Any],
    output: Mapping[str, Any] | None,
    error: Mapping[str, Any] | None,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> WorkflowRun:
    """Reconstruct a run directly without replaying lifecycle transitions."""
    try:
        run_status = WorkflowRunStatus(status)
    except ValueError as exception:
        raise ValueError(f"Invalid stored workflow run status: {status!r}") from exception
    return WorkflowRun(
        id=run_id,
        workflow_id=workflow_id,
        workflow_revision=workflow_revision,
        status=run_status,
        input=dict(input),
        node_outputs=dict(node_outputs),
        output=None if output is None else dict(output),
        error=deserialize_workflow_run_error(error),
        started_at=started_at,
        finished_at=finished_at,
    )
