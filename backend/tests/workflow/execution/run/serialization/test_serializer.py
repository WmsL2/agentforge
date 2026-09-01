"""Tests for pure workflow-run persistence-state serialization."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.workflow.execution.run import (
    WorkflowRun,
    WorkflowRunError,
    WorkflowRunStatus,
    deserialize_workflow_run,
    deserialize_workflow_run_error,
    serialize_workflow_run_error,
    serialize_workflow_run_state,
)

STARTED_AT = datetime(2026, 9, 1, 10, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 1, 10, 5, tzinfo=UTC)


def make_run(**kwargs: object) -> WorkflowRun:
    return WorkflowRun(id=uuid4(), workflow_id=uuid4(), workflow_revision=2, **kwargs)  # type: ignore[arg-type]


def test_pending_run_state_serializes_with_independent_plain_dicts() -> None:
    run = make_run(input={"request": "hello"})

    state = serialize_workflow_run_state(run)

    assert state == {
        "status": "pending",
        "input": {"request": "hello"},
        "node_outputs": {},
        "output": None,
        "error": None,
        "started_at": None,
        "finished_at": None,
    }
    assert state["input"] is not run.input
    assert state["node_outputs"] is not run.node_outputs


def test_completed_run_state_preserves_output_and_timestamps() -> None:
    run = make_run(input={"request": "hello"})
    run.start(at=STARTED_AT)
    run.node_outputs["value"] = 10
    run.complete({"end": {"value": 10}}, at=FINISHED_AT)

    state = serialize_workflow_run_state(run)

    assert state["status"] == "completed"
    assert state["output"] == {"end": {"value": 10}}
    assert state["started_at"] == STARTED_AT
    assert state["finished_at"] == FINISHED_AT


def test_failed_run_error_round_trips_with_optional_node_id() -> None:
    error = WorkflowRunError(code="node_execution_failed", message="boom", node_id="value")
    run = make_run()
    run.start(at=STARTED_AT)
    run.fail(error, at=FINISHED_AT)

    assert serialize_workflow_run_error(error) == {
        "code": "node_execution_failed",
        "message": "boom",
        "node_id": "value",
    }
    assert serialize_workflow_run_state(run)["error"] == serialize_workflow_run_error(error)
    assert deserialize_workflow_run_error(
        {"code": "workflow_failed", "message": "failed", "node_id": None}
    ) == WorkflowRunError(code="workflow_failed", message="failed", node_id=None)
    assert deserialize_workflow_run_error(None) is None


def test_deserialize_run_reconstructs_terminal_state_with_fresh_dicts() -> None:
    input_payload = {"request": "hello"}
    outputs_payload = {"value": 10}
    output_payload = {"end": {"value": 10}}
    run_id = uuid4()
    workflow_id = uuid4()

    run = deserialize_workflow_run(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_revision=3,
        status="completed",
        input=input_payload,
        node_outputs=outputs_payload,
        output=output_payload,
        error=None,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
    )
    run.input["mutated"] = True
    run.node_outputs["other"] = 20
    assert run.output is not None
    run.output["other_end"] = None

    assert run.status is WorkflowRunStatus.COMPLETED
    assert (run.id, run.workflow_id, run.workflow_revision) == (run_id, workflow_id, 3)
    assert input_payload == {"request": "hello"}
    assert outputs_payload == {"value": 10}
    assert output_payload == {"end": {"value": 10}}
    assert (run.started_at, run.finished_at) == (STARTED_AT, FINISHED_AT)


def test_invalid_status_and_malformed_error_payloads_are_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid stored workflow run status"):
        deserialize_workflow_run(
            run_id=uuid4(),
            workflow_id=uuid4(),
            workflow_revision=1,
            status="paused",
            input={},
            node_outputs={},
            output=None,
            error=None,
            started_at=None,
            finished_at=None,
        )

    with pytest.raises(ValueError, match="missing keys"):
        deserialize_workflow_run_error({"code": "failed", "message": "failed"})
    with pytest.raises(TypeError, match="node_id"):
        deserialize_workflow_run_error({"code": "failed", "message": "failed", "node_id": 1})
