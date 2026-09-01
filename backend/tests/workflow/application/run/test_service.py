"""Workflow-run application orchestration tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.services.workflow import (
    DeterministicNodeExecutor,
    WorkflowEngine,
    WorkflowRunError,
    WorkflowRunService,
)
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workflow.definition.validation.validator import (
    WorkflowValidationResult,
)
from app.services.workflow.execution.engine import WorkflowExecutionValidationError


def workflow_row(owner_id, workflow_id=None, revision=3):
    return SimpleNamespace(
        id=workflow_id or uuid4(),
        user_id=owner_id,
        name="Workflow",
        description=None,
        revision=revision,
        definition={
            "schema_version": 1,
            "entry_node_id": "start",
            "nodes": [
                {"id": "start", "kind": "start", "config": {}, "metadata": {}},
                {"id": "end", "kind": "end", "config": {}, "metadata": {}},
            ],
            "edges": [
                {
                    "id": "edge",
                    "source": "start",
                    "target": "end",
                    "condition": None,
                    "metadata": {},
                }
            ],
            "metadata": {},
        },
    )


@pytest.mark.anyio
async def test_execute_creates_snapshot_executes_same_run_and_persists_terminal_state():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    definition_service = WorkflowService(db)
    service = WorkflowRunService(
        db, definition_service, WorkflowEngine(DeterministicNodeExecutor())
    )
    db_run = SimpleNamespace()
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=db_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)

        result = await service.execute_workflow(row.id, owner, {"request": "hello"})

    assert result is db_run
    created_run = run_repo.create_workflow_run.await_args.kwargs["run"]
    snapshot = run_repo.create_workflow_run.await_args.kwargs["definition_snapshot"]
    assert (created_run.workflow_id, created_run.workflow_revision, created_run.input) == (
        row.id,
        3,
        {"request": "hello"},
    )
    assert snapshot == row.definition
    assert created_run.status.value == "completed"
    assert run_repo.update_workflow_run_state.await_args.kwargs == {
        "db_run": db_run,
        "run": created_run,
    }


@pytest.mark.anyio
async def test_failed_engine_result_is_persisted_and_returned_normally():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    definition_service = WorkflowService(db)
    engine = AsyncMock()

    async def fail_run(_, run):
        run.start()
        run.fail(WorkflowRunError(code="node_execution_failed", message="boom", node_id="end"))
        return run

    engine.execute.side_effect = fail_run
    service = WorkflowRunService(db, definition_service, engine)
    db_run = SimpleNamespace()
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=db_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)

        assert await service.execute_workflow(row.id, owner, {}) is db_run

    persisted_run = run_repo.update_workflow_run_state.await_args.kwargs["run"]
    assert persisted_run.status.value == "failed"
    assert persisted_run.error.code == "node_execution_failed"


@pytest.mark.anyio
async def test_ownership_and_run_parent_mismatch_are_not_found():
    db = AsyncMock()
    owner, other = uuid4(), uuid4()
    row = workflow_row(owner)
    definition_service = WorkflowService(db)
    service = WorkflowRunService(db, definition_service, AsyncMock())
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock()
        with pytest.raises(NotFoundError):
            await service.execute_workflow(row.id, other, {})
        run_repo.create_workflow_run.assert_not_awaited()
        run_repo.get_workflow_run_by_id = AsyncMock(
            return_value=SimpleNamespace(workflow_id=uuid4())
        )
        with pytest.raises(NotFoundError):
            await service.get_workflow_run(row.id, uuid4(), owner)


@pytest.mark.anyio
async def test_list_checks_parent_ownership_before_run_repository():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    service = WorkflowRunService(db, WorkflowService(db), AsyncMock())
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.list_workflow_runs_by_workflow = AsyncMock(return_value=[])
        run_repo.count_workflow_runs_by_workflow = AsyncMock(return_value=0)
        assert await service.list_workflow_runs(row.id, owner) == ([], 0)


@pytest.mark.anyio
async def test_execution_validation_error_is_not_persisted_as_a_terminal_run():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    engine = AsyncMock()
    engine.execute.side_effect = WorkflowExecutionValidationError(
        WorkflowValidationResult(issues=())
    )
    service = WorkflowRunService(db, WorkflowService(db), engine)
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=SimpleNamespace())
        run_repo.update_workflow_run_state = AsyncMock()
        with pytest.raises(ValidationError):
            await service.execute_workflow(row.id, owner, {})

    run_repo.create_workflow_run.assert_awaited_once()
    run_repo.update_workflow_run_state.assert_not_awaited()
