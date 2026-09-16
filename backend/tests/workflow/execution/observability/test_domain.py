"""Contract tests for pure execution-observability domain objects."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.services.workflow import (
    RunStep,
    RunStepError,
    RunStepStatus,
    RunStepTransitionError,
    TraceEvent,
    TraceEventKind,
    WorkflowNodeKind,
)

STARTED_AT = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 16, 9, 45, tzinfo=UTC)


def make_step(**kwargs: object) -> RunStep:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "sequence": 1,
        "node_id": "value",
        "node_kind": WorkflowNodeKind.VALUE,
        "input": {"request": "hello"},
        "metadata": {"attempt": 1},
        "started_at": STARTED_AT,
    }
    values.update(kwargs)
    return RunStep(**values)  # type: ignore[arg-type]


def make_event(**kwargs: object) -> TraceEvent:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "step_id": uuid4(),
        "kind": TraceEventKind.NODE_STARTED,
        "payload": {"node_id": "value"},
        "created_at": STARTED_AT,
    }
    values.update(kwargs)
    return TraceEvent(**values)  # type: ignore[arg-type]


def test_run_step_status_values_are_exact() -> None:
    assert [status.value for status in RunStepStatus] == [
        "running",
        "completed",
        "failed",
        "interrupted",
    ]


def test_new_step_defaults_to_a_running_unfinished_attempt() -> None:
    step = make_step()

    assert step.status is RunStepStatus.RUNNING
    assert step.output is None
    assert step.error is None
    assert step.finished_at is None


@pytest.mark.parametrize("sequence", [0, -1])
def test_non_positive_sequence_is_rejected(sequence: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        make_step(sequence=sequence)


def test_empty_node_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        make_step(node_id="")


def test_input_is_an_independent_read_only_snapshot() -> None:
    input_data = {"request": "hello"}
    step = make_step(input=input_data)
    input_data["later"] = "no"

    assert isinstance(step.input, MappingProxyType)
    assert step.input == {"request": "hello"}
    with pytest.raises(TypeError):
        step.input["injected"] = "no"  # type: ignore[index]


def test_metadata_is_an_independent_read_only_snapshot() -> None:
    metadata = {"attempt": 1}
    step = make_step(metadata=metadata)
    metadata["later"] = "no"

    assert isinstance(step.metadata, MappingProxyType)
    assert step.metadata == {"attempt": 1}
    with pytest.raises(TypeError):
        step.metadata["injected"] = "no"  # type: ignore[index]


def test_complete_records_output_metadata_and_finished_time() -> None:
    step = make_step()
    output = {"answer": "done"}
    metadata = {"duration_ms": 12}

    step.complete(output, metadata, at=FINISHED_AT)

    assert step.status is RunStepStatus.COMPLETED
    assert step.output is output
    assert step.error is None
    assert step.metadata == metadata
    assert step.finished_at == FINISHED_AT


def test_fail_records_error_metadata_and_finished_time() -> None:
    step = make_step()
    error = RunStepError(code="node_execution_failed", message="Node failed")

    step.fail(error, {"duration_ms": 12}, at=FINISHED_AT)

    assert step.status is RunStepStatus.FAILED
    assert step.output is None
    assert step.error is error
    assert step.metadata == {"duration_ms": 12}
    assert step.finished_at == FINISHED_AT


def test_interrupt_records_output_metadata_and_finished_time() -> None:
    step = make_step()

    step.interrupt({"approval_id": "approval-1"}, {"duration_ms": 12}, at=FINISHED_AT)

    assert step.status is RunStepStatus.INTERRUPTED
    assert step.output == {"approval_id": "approval-1"}
    assert step.error is None
    assert step.metadata == {"duration_ms": 12}
    assert step.finished_at == FINISHED_AT


@pytest.mark.parametrize(
    ("operation", "attempted"),
    [
        ("complete", RunStepStatus.COMPLETED),
        ("fail", RunStepStatus.FAILED),
        ("interrupt", RunStepStatus.INTERRUPTED),
    ],
)
@pytest.mark.parametrize(
    "terminal_status",
    [RunStepStatus.COMPLETED, RunStepStatus.FAILED, RunStepStatus.INTERRUPTED],
)
def test_terminal_steps_reject_all_terminal_transitions(
    terminal_status: RunStepStatus, operation: str, attempted: RunStepStatus
) -> None:
    step = make_step(status=terminal_status)

    with pytest.raises(RunStepTransitionError) as exc_info:
        if operation == "complete":
            step.complete({"answer": "done"}, {})
        elif operation == "fail":
            step.fail(RunStepError(code="failed", message="failed"), {})
        else:
            step.interrupt(None, {})

    assert exc_info.value.current is terminal_status
    assert exc_info.value.attempted is attempted


def test_transition_error_exposes_current_and_attempted_statuses() -> None:
    step = make_step(status=RunStepStatus.COMPLETED)

    with pytest.raises(RunStepTransitionError) as exc_info:
        step.fail(RunStepError(code="failed", message="failed"), {})

    assert exc_info.value.current is RunStepStatus.COMPLETED
    assert exc_info.value.attempted is RunStepStatus.FAILED


def test_default_started_at_is_timezone_aware_utc() -> None:
    step = make_step()
    step = RunStep(
        id=step.id,
        run_id=step.run_id,
        sequence=step.sequence,
        node_id=step.node_id,
        node_kind=step.node_kind,
    )

    assert step.started_at.tzinfo is UTC
    assert step.started_at.utcoffset() == UTC.utcoffset(step.started_at)


def test_trace_event_kind_values_are_exact() -> None:
    assert [kind.value for kind in TraceEventKind] == [
        "node_started",
        "node_completed",
        "node_failed",
        "node_interrupted",
        "approval_requested",
        "approval_approved",
        "approval_rejected",
        "agent_started",
        "agent_completed",
        "agent_failed",
        "tool_started",
        "tool_completed",
        "tool_failed",
    ]


def test_trace_event_allows_a_step_id_or_no_step_id() -> None:
    step_id = uuid4()

    assert make_event(step_id=step_id).step_id == step_id
    assert make_event(step_id=None).step_id is None


def test_trace_event_payload_is_an_independent_read_only_snapshot() -> None:
    payload = {"node_id": "value"}
    event = make_event(payload=payload)
    payload["later"] = "no"

    assert isinstance(event.payload, MappingProxyType)
    assert event.payload == {"node_id": "value"}
    with pytest.raises(TypeError):
        event.payload["injected"] = "no"  # type: ignore[index]


def test_trace_event_is_frozen_and_preserves_a_timezone_aware_timestamp() -> None:
    event = make_event(created_at=STARTED_AT)

    assert event.created_at == STARTED_AT
    assert event.created_at.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        event.kind = TraceEventKind.NODE_COMPLETED  # type: ignore[misc]
