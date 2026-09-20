"""Workflow observability HTTP read-model tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.workflow import WorkflowRunStepRead, WorkflowTraceEventRead
from app.services.workflow.definition import WorkflowNodeKind
from app.services.workflow.execution.observability import RunStepStatus, TraceEventKind


def _step_row(*, finished_at: datetime | None):
    started_at = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        sequence=3,
        node_id="agent",
        node_kind="agent",
        status="completed",
        input={"question": "status"},
        output={"answer": "ok"},
        error={"code": "provider_failed", "message": "retry later"},
        metadata_={"provider": "test"},
        started_at=started_at,
        finished_at=finished_at,
    )


def test_run_step_read_validates_orm_attributes_and_maps_metadata_and_duration() -> None:
    row = _step_row(finished_at=datetime(2026, 9, 19, 10, 0, 1, 500000, tzinfo=UTC))

    read = WorkflowRunStepRead.model_validate(row)

    assert read.node_kind is WorkflowNodeKind.AGENT
    assert read.status is RunStepStatus.COMPLETED
    assert read.error is not None
    assert (read.error.code, read.error.message) == ("provider_failed", "retry later")
    assert read.metadata == {"provider": "test"}
    assert read.duration_ms == 1500.0
    assert "metadata_" not in read.model_dump()
    assert read.model_dump()["metadata"] == {"provider": "test"}


def test_run_step_read_has_no_duration_for_unfinished_step() -> None:
    read = WorkflowRunStepRead.model_validate(_step_row(finished_at=None))

    assert read.duration_ms is None


def test_trace_event_read_supports_run_level_event_without_step_identity() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        step_id=None,
        kind="approval_approved",
        payload={"node_id": "approval"},
        created_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    read = WorkflowTraceEventRead.model_validate(row)

    assert read.step_id is None
    assert read.kind is TraceEventKind.APPROVAL_APPROVED
    assert read.payload == {"node_id": "approval"}
