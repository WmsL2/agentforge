"""Workflow-run application orchestration tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.services.workflow import (
    ApprovalNodeExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
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
    persistence = MagicMock()
    persistence.persist_node_completion = AsyncMock()
    events: list[str] = []

    async def create_run(*args, **kwargs):
        events.append("create")
        return db_run

    async def commit():
        events.append("commit")

    async def execute_run(*args, **kwargs):
        events.append("execute")
        return await WorkflowEngine(DeterministicNodeExecutor()).execute(*args, **kwargs)

    db.commit.side_effect = commit
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
        patch(
            "app.services.workflow.application.run.service.DurableWorkflowExecutionPersistence",
            return_value=persistence,
        ) as durability,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(side_effect=create_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)
        service.engine.execute = AsyncMock(side_effect=execute_run)

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
    assert events[:3] == ["create", "commit", "execute"]
    durability.assert_called_once_with(db, db_run, next_sequence=1)
    service.engine.execute.assert_awaited_once_with(
        row and service._definition_from_row(row), created_run, persistence=persistence
    )
    run_repo.update_workflow_run_state.assert_not_awaited()


@pytest.mark.anyio
async def test_failed_engine_result_is_persisted_and_returned_normally():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    definition_service = WorkflowService(db)
    engine = AsyncMock()
    engine.validate_definition = MagicMock()

    async def fail_run(_, run, *, persistence):
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
        patch("app.services.workflow.application.run.service.DurableWorkflowExecutionPersistence"),
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=db_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)

        assert await service.execute_workflow(row.id, owner, {}) is db_run

    persisted_run = run_repo.update_workflow_run_state.await_args.kwargs["run"]
    assert persisted_run.status.value == "failed"
    assert persisted_run.error.code == "node_execution_failed"
    assert db.commit.await_count == 2


@pytest.mark.anyio
async def test_paused_approval_run_is_durably_persisted_by_engine_without_terminal_update():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    row.definition["nodes"] = [
        {"id": "start", "kind": "start", "config": {}, "metadata": {}},
        {
            "id": "approval",
            "kind": "approval",
            "config": {"prompt": "Continue?"},
            "metadata": {},
        },
        {"id": "end", "kind": "end", "config": {}, "metadata": {}},
    ]
    row.definition["edges"] = [
        {
            "id": "start-approval",
            "source": "start",
            "target": "approval",
            "condition": None,
            "metadata": {},
        },
        {
            "id": "approval-end",
            "source": "approval",
            "target": "end",
            "condition": None,
            "metadata": {},
        },
    ]
    engine = WorkflowEngine(
        DispatchingNodeExecutor(
            deterministic_executor=DeterministicNodeExecutor(),
            agent_executor=MagicMock(),
            approval_executor=ApprovalNodeExecutor(),
        )
    )
    service = WorkflowRunService(db, WorkflowService(db), engine)
    db_run = SimpleNamespace()
    persistence = MagicMock()
    persistence.persist_node_completion = AsyncMock()
    persistence.persist_interruption = AsyncMock()
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
        patch(
            "app.services.workflow.application.run.service.DurableWorkflowExecutionPersistence",
            return_value=persistence,
        ),
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=db_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)

        assert await service.execute_workflow(row.id, owner, {}) is db_run

    persisted_run = persistence.persist_interruption.await_args.args[0]
    assert persisted_run.status.value == "paused"
    run_repo.update_workflow_run_state.assert_not_awaited()
    assert db.commit.await_count == 1


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
@pytest.mark.parametrize(
    ("method_name", "repository_name"),
    [
        ("list_workflow_run_steps", "run_step_repo"),
        ("list_workflow_trace_events", "trace_event_repo"),
    ],
)
async def test_observability_queries_return_repository_order_after_ownership_gate(
    method_name, repository_name
):
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    run = SimpleNamespace(id=uuid4(), workflow_id=row.id)
    ordered = [SimpleNamespace(sequence=1), SimpleNamespace(sequence=2)]
    service = WorkflowRunService(db, WorkflowService(db), AsyncMock())
    with (
        patch("app.services.workflow.application.definition.service.workflow_repo") as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
        patch(f"app.services.workflow.application.run.service.{repository_name}") as observability_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        if repository_name == "run_step_repo":
            observability_repo.list_workflow_run_steps = AsyncMock(return_value=ordered)
        else:
            observability_repo.list_workflow_trace_events = AsyncMock(return_value=ordered)

        assert await getattr(service, method_name)(row.id, run.id, owner) is ordered

    run_repo.get_workflow_run_by_id.assert_awaited_once_with(db, run.id)
    expected_call = (db, run.id)
    if repository_name == "run_step_repo":
        observability_repo.list_workflow_run_steps.assert_awaited_once_with(*expected_call)
    else:
        observability_repo.list_workflow_trace_events.assert_awaited_once_with(*expected_call)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method_name", "repository_name", "workflow_result", "run_result"),
    [
        ("list_workflow_run_steps", "run_step_repo", None, None),
        ("list_workflow_trace_events", "trace_event_repo", "owned", None),
        ("list_workflow_run_steps", "run_step_repo", "owned", "other_workflow"),
        ("list_workflow_trace_events", "trace_event_repo", "owned", "other_workflow"),
    ],
)
async def test_observability_queries_never_call_repository_when_ownership_gate_fails(
    method_name, repository_name, workflow_result, run_result
):
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    run_id = uuid4()
    service = WorkflowRunService(db, WorkflowService(db), AsyncMock())
    with (
        patch("app.services.workflow.application.definition.service.workflow_repo") as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
        patch(f"app.services.workflow.application.run.service.{repository_name}") as observability_repo,
    ):
        definition_repo.get_workflow_by_id = AsyncMock(
            return_value=row if workflow_result == "owned" else None
        )
        run_repo.get_workflow_run_by_id = AsyncMock(
            return_value=(
                SimpleNamespace(id=run_id, workflow_id=uuid4()) if run_result == "other_workflow" else None
            )
        )

        with pytest.raises(NotFoundError):
            await getattr(service, method_name)(row.id, run_id, owner)

    if repository_name == "run_step_repo":
        observability_repo.list_workflow_run_steps.assert_not_called()
    else:
        observability_repo.list_workflow_trace_events.assert_not_called()


@pytest.mark.anyio
async def test_execution_validation_error_is_not_persisted_as_a_terminal_run():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    engine = AsyncMock()
    engine.validate_definition = MagicMock(
        side_effect=WorkflowExecutionValidationError(WorkflowValidationResult(issues=()))
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

    run_repo.create_workflow_run.assert_not_awaited()
    run_repo.update_workflow_run_state.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_persistence_exception_propagates_without_terminal_failure_update():
    db = AsyncMock()
    owner = uuid4()
    row = workflow_row(owner)
    engine = AsyncMock()
    engine.validate_definition = MagicMock()
    engine.execute.side_effect = RuntimeError("durability failed")
    service = WorkflowRunService(db, WorkflowService(db), engine)
    db_run = SimpleNamespace()
    with (
        patch(
            "app.services.workflow.application.definition.service.workflow_repo"
        ) as definition_repo,
        patch("app.services.workflow.application.run.service.run_repo") as run_repo,
        patch("app.services.workflow.application.run.service.DurableWorkflowExecutionPersistence"),
    ):
        definition_repo.get_workflow_by_id = AsyncMock(return_value=row)
        run_repo.create_workflow_run = AsyncMock(return_value=db_run)
        run_repo.update_workflow_run_state = AsyncMock(return_value=db_run)

        with pytest.raises(RuntimeError, match="durability failed"):
            await service.execute_workflow(row.id, owner, {})

    run_repo.update_workflow_run_state.assert_not_awaited()
    assert db.commit.await_count == 1
