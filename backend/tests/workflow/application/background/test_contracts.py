"""Tests for background workflow execution application contracts."""

from dataclasses import FrozenInstanceError, fields
from uuid import uuid4

import pytest

from app.services.workflow import WorkflowExecutionDispatcher, WorkflowExecutionJob


def test_workflow_execution_job_preserves_run_id():
    run_id = uuid4()

    job = WorkflowExecutionJob(run_id=run_id)

    assert job.run_id == run_id


def test_workflow_execution_job_is_frozen():
    job = WorkflowExecutionJob(run_id=uuid4())

    with pytest.raises(FrozenInstanceError):
        job.run_id = uuid4()


def test_workflow_execution_job_has_only_run_id_field():
    assert [field.name for field in fields(WorkflowExecutionJob)] == ["run_id"]


@pytest.mark.anyio
async def test_dispatcher_protocol_supports_recording_implementation():
    class RecordingDispatcher:
        def __init__(self) -> None:
            self.jobs: list[WorkflowExecutionJob] = []

        async def dispatch(self, job: WorkflowExecutionJob) -> None:
            self.jobs.append(job)

    job = WorkflowExecutionJob(run_id=uuid4())
    dispatcher: WorkflowExecutionDispatcher = RecordingDispatcher()

    result = await dispatcher.dispatch(job)

    assert result is None
    assert dispatcher.jobs == [job]
    assert dispatcher.jobs[0].run_id == job.run_id


def test_background_contracts_are_publicly_exported():
    assert WorkflowExecutionJob.__name__ == "WorkflowExecutionJob"
    assert WorkflowExecutionDispatcher.__name__ == "WorkflowExecutionDispatcher"
