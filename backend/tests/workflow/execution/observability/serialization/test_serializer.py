"""Tests for execution-observability persistence serialization."""

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.services.workflow import (
    RunStep,
    RunStepError,
    RunStepStatus,
    TraceEvent,
    TraceEventKind,
    WorkflowNodeKind,
)
from app.services.workflow.execution.observability.serialization import (
    deserialize_run_step,
    deserialize_trace_event,
    serialize_run_step_state,
    serialize_trace_event_state,
)

STARTED_AT = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 16, 9, 45, tzinfo=UTC)


def make_step(**kwargs: object) -> RunStep:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "sequence": 2,
        "node_id": "agent",
        "node_kind": WorkflowNodeKind.AGENT,
        "input": {"prompt": "hello"},
        "metadata": {"attempt": 2},
        "started_at": STARTED_AT,
    }
    values.update(kwargs)
    return RunStep(**values)  # type: ignore[arg-type]


def values_for(step: RunStep) -> dict[str, object]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "sequence": step.sequence,
        "node_id": step.node_id,
        "node_kind": step.node_kind.value,
        **serialize_run_step_state(step),
    }


def test_running_step_serializes_jsonb_compatible_state() -> None:
    step = make_step()

    assert serialize_run_step_state(step) == {
        "status": "running",
        "input": {"prompt": "hello"},
        "output": None,
        "error": None,
        "metadata": {"attempt": 2},
        "started_at": STARTED_AT,
        "finished_at": None,
    }


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_error"),
    [
        ("completed", RunStepStatus.COMPLETED, None),
        ("failed", RunStepStatus.FAILED, RunStepError(code="failed", message="boom")),
        ("interrupted", RunStepStatus.INTERRUPTED, None),
    ],
)
def test_terminal_step_round_trip_restores_status_error_and_timestamps(
    outcome: str,
    expected_status: RunStepStatus,
    expected_error: RunStepError | None,
) -> None:
    step = make_step()
    if outcome == "completed":
        step.complete({"answer": "done"}, {"duration_ms": 10}, at=FINISHED_AT)
    elif outcome == "failed":
        step.fail(expected_error, {"duration_ms": 10}, at=FINISHED_AT)  # type: ignore[arg-type]
    else:
        step.interrupt({"approval_id": "approval-1"}, {"duration_ms": 10}, at=FINISHED_AT)

    restored = deserialize_run_step(values_for(step))

    assert restored.status is expected_status
    assert restored.error == expected_error
    assert (restored.started_at, restored.finished_at) == (STARTED_AT, FINISHED_AT)
    assert restored.node_kind is WorkflowNodeKind.AGENT


def test_step_deserialization_reapplies_input_and_metadata_snapshots() -> None:
    step = make_step()
    values = values_for(step)
    input_data = values["input"]
    metadata = values["metadata"]
    assert isinstance(input_data, dict)
    assert isinstance(metadata, dict)

    restored = deserialize_run_step(values)
    input_data["later"] = "no"
    metadata["later"] = "no"

    assert isinstance(restored.input, MappingProxyType)
    assert isinstance(restored.metadata, MappingProxyType)
    assert restored.input == {"prompt": "hello"}
    assert restored.metadata == {"attempt": 2}


def test_trace_event_round_trip_restores_kind_step_id_and_immutable_payload() -> None:
    step_id = uuid4()
    event = TraceEvent(
        id=uuid4(),
        run_id=uuid4(),
        step_id=step_id,
        kind=TraceEventKind.TOOL_COMPLETED,
        payload={"tool": "search"},
        created_at=STARTED_AT,
    )
    values = {
        "id": event.id,
        "run_id": event.run_id,
        "step_id": event.step_id,
        **serialize_trace_event_state(event),
    }
    payload = values["payload"]
    assert isinstance(payload, dict)

    restored = deserialize_trace_event(values)
    payload["later"] = "no"

    assert restored.step_id == step_id
    assert restored.kind is TraceEventKind.TOOL_COMPLETED
    assert restored.created_at == STARTED_AT
    assert isinstance(restored.payload, MappingProxyType)
    assert restored.payload == {"tool": "search"}


def test_trace_event_round_trip_preserves_a_none_step_id() -> None:
    event = TraceEvent(
        id=uuid4(),
        run_id=uuid4(),
        step_id=None,
        kind=TraceEventKind.APPROVAL_APPROVED,
        payload={"approval_id": "approval-1"},
        created_at=FINISHED_AT,
    )

    restored = deserialize_trace_event(
        {"id": event.id, "run_id": event.run_id, "step_id": None, **serialize_trace_event_state(event)}
    )

    assert restored.step_id is None
    assert restored.kind is TraceEventKind.APPROVAL_APPROVED
