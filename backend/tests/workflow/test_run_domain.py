"""Contract tests for the pure workflow-run domain model."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.workflow import (
    WorkflowRun,
    WorkflowRunError,
    WorkflowRunStatus,
    WorkflowRunTransitionError,
)

STARTED_AT = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 1, 9, 45, tzinfo=UTC)


def make_run(**kwargs: object) -> WorkflowRun:
    """Build a run with only its value-object identity fields specified."""
    return WorkflowRun(
        id=uuid4(),
        workflow_id=uuid4(),
        workflow_revision=3,
        **kwargs,
    )  # type: ignore[arg-type]


def test_workflow_run_status_values_are_exact() -> None:
    assert [status.value for status in WorkflowRunStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
    ]


def test_new_workflow_run_has_expected_initial_state() -> None:
    input_data = {"prompt": "Draft release notes"}

    run = make_run(input=input_data)

    assert run.status is WorkflowRunStatus.PENDING
    assert run.input == input_data
    assert run.node_outputs == {}
    assert run.output is None
    assert run.error is None
    assert run.started_at is None
    assert run.finished_at is None


def test_run_mutable_defaults_are_isolated() -> None:
    first = make_run()
    second = make_run()

    first.input["request"] = "first"
    first.node_outputs["planner"] = {"plan": "first plan"}

    assert second.input == {}
    assert second.node_outputs == {}


def test_start_transitions_pending_to_running_with_explicit_timestamp() -> None:
    run = make_run(
        input={"topic": "workflow runs"},
        node_outputs={"draft": {"summary": "existing"}},
    )

    run.start(at=STARTED_AT)

    assert run.status is WorkflowRunStatus.RUNNING
    assert run.started_at == STARTED_AT
    assert run.finished_at is None
    assert run.input == {"topic": "workflow runs"}
    assert run.node_outputs == {"draft": {"summary": "existing"}}


def test_start_uses_timezone_aware_utc_timestamp_by_default() -> None:
    run = make_run()

    run.start()

    assert run.started_at is not None
    assert run.started_at.tzinfo is UTC
    assert run.started_at.utcoffset() == UTC.utcoffset(run.started_at)


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
    ],
)
def test_start_rejects_non_pending_states(status: WorkflowRunStatus) -> None:
    run = make_run(status=status)

    with pytest.raises(WorkflowRunTransitionError) as exc_info:
        run.start()

    assert exc_info.value.current is status
    assert exc_info.value.attempted is WorkflowRunStatus.RUNNING


def test_complete_transitions_running_to_completed() -> None:
    run = make_run(node_outputs={"planner": {"steps": ["write", "review"]}})
    run.start(at=STARTED_AT)
    output = {"answer": "done"}

    run.complete(output, at=FINISHED_AT)

    assert run.status is WorkflowRunStatus.COMPLETED
    assert run.output == output
    assert run.error is None
    assert run.started_at == STARTED_AT
    assert run.finished_at == FINISHED_AT
    assert run.node_outputs == {"planner": {"steps": ["write", "review"]}}


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
    ],
)
def test_complete_rejects_invalid_source_states(status: WorkflowRunStatus) -> None:
    run = make_run(status=status)

    with pytest.raises(WorkflowRunTransitionError) as exc_info:
        run.complete({"answer": "done"})

    assert exc_info.value.current is status
    assert exc_info.value.attempted is WorkflowRunStatus.COMPLETED


def test_fail_transitions_running_to_failed_and_retains_node_outputs() -> None:
    run = make_run()
    run.start(at=STARTED_AT)
    run.node_outputs["value"] = {"partial": "available"}
    error = WorkflowRunError(
        code="node_execution_failed",
        message="Node failed",
        node_id="value",
    )

    run.fail(error, at=FINISHED_AT)

    assert run.status is WorkflowRunStatus.FAILED
    assert run.error is error
    assert run.output is None
    assert run.started_at == STARTED_AT
    assert run.finished_at == FINISHED_AT
    assert run.node_outputs == {"value": {"partial": "available"}}


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
    ],
)
def test_fail_rejects_invalid_source_states(status: WorkflowRunStatus) -> None:
    run = make_run(status=status)

    with pytest.raises(WorkflowRunTransitionError) as exc_info:
        run.fail(WorkflowRunError(code="failed", message="failed"))

    assert exc_info.value.current is status
    assert exc_info.value.attempted is WorkflowRunStatus.FAILED


@pytest.mark.parametrize(
    ("status", "attempted"),
    [
        (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.RUNNING),
        (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED),
        (WorkflowRunStatus.FAILED, WorkflowRunStatus.RUNNING),
        (WorkflowRunStatus.FAILED, WorkflowRunStatus.COMPLETED),
    ],
)
def test_terminal_states_cannot_restart_or_switch_outcome(
    status: WorkflowRunStatus,
    attempted: WorkflowRunStatus,
) -> None:
    run = make_run(status=status)

    with pytest.raises(WorkflowRunTransitionError) as exc_info:
        if attempted is WorkflowRunStatus.RUNNING:
            run.start()
        elif attempted is WorkflowRunStatus.COMPLETED:
            run.complete({"answer": "done"})
        else:
            run.fail(WorkflowRunError(code="failed", message="failed"))

    assert exc_info.value.current is status
    assert exc_info.value.attempted is attempted


def test_transition_error_exposes_statuses_without_message_coupling() -> None:
    run = make_run()

    with pytest.raises(WorkflowRunTransitionError) as exc_info:
        run.complete({"answer": "done"})

    assert exc_info.value.current is WorkflowRunStatus.PENDING
    assert exc_info.value.attempted is WorkflowRunStatus.COMPLETED


def test_workflow_run_error_preserves_fields_and_allows_missing_node_id() -> None:
    error = WorkflowRunError(
        code="node_execution_failed",
        message="Node failed",
        node_id="value",
    )
    workflow_error = WorkflowRunError(code="workflow_failed", message="Workflow failed")

    assert (error.code, error.message, error.node_id) == (
        "node_execution_failed",
        "Node failed",
        "value",
    )
    assert workflow_error.node_id is None
