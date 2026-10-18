"""Asynchronous workflow-run submission orchestration tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AuthorizationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from app.services.workflow import WorkflowAsyncRunService
from app.services.workspace.domain import WorkspacePermission


def workflow_row(*, valid: bool = True):
    workflow_id = uuid4()
    nodes = [
        {"id": "start", "kind": "start", "config": {}, "metadata": {}},
        {"id": "end", "kind": "end", "config": {}, "metadata": {}},
    ]
    edges = [
        {
            "id": "start-end",
            "source": "start",
            "target": "end",
            "condition": None,
            "metadata": {},
        }
    ]
    if not valid:
        nodes.pop()
        edges.clear()
    return SimpleNamespace(
        id=workflow_id,
        workspace_id=uuid4(),
        name="Async workflow",
        description=None,
        revision=7,
        definition={
            "schema_version": 1,
            "entry_node_id": "start",
            "nodes": nodes,
            "edges": edges,
            "metadata": {"source": {"version": 1}},
        },
    )


def subject(row=None):
    db = AsyncMock()
    workflow_service = AsyncMock()
    workflow_service.get_authorized_workflow.return_value = row or workflow_row()
    dispatcher = AsyncMock()
    return (
        WorkflowAsyncRunService(db, workflow_service, dispatcher),
        db,
        workflow_service,
        dispatcher,
    )


@pytest.mark.anyio
async def test_authorize_validate_commit_then_dispatch_pending_snapshot() -> None:
    row = workflow_row()
    service, db, workflow_service, dispatcher = subject(row)
    actor_id = uuid4()
    events = []
    stored = SimpleNamespace(id=None)

    async def create_run(*args, **kwargs):
        events.append("create")
        stored.id = kwargs["run"].id
        return stored

    async def commit():
        events.append("commit")

    async def dispatch(job):
        events.append("dispatch")
        assert job.run_id == stored.id

    db.commit.side_effect = commit
    dispatcher.dispatch.side_effect = dispatch
    with patch(
        "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
        new=AsyncMock(side_effect=create_run),
    ) as create:
        result = await service.submit_workflow(row.id, actor_id, {"nested": {"value": 1}})

    assert result is stored
    assert events == ["create", "commit", "dispatch"]
    workflow_service.get_authorized_workflow.assert_awaited_once_with(
        row.id, actor_id, WorkspacePermission.WORKFLOW_RUN
    )
    run = create.await_args.kwargs["run"]
    snapshot = create.await_args.kwargs["definition_snapshot"]
    assert run.status.value == "pending"
    assert run.workflow_revision == 7
    assert snapshot == row.definition
    assert run.started_at is run.finished_at is run.output is run.error is None
    assert run.node_outputs == {}


@pytest.mark.anyio
async def test_input_and_snapshot_are_detached_from_later_mutation() -> None:
    row = workflow_row()
    input_data = {"nested": {"value": 1}}
    service, _, _, _ = subject(row)
    stored = SimpleNamespace(id=uuid4())
    with patch(
        "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
        new=AsyncMock(return_value=stored),
    ) as create:
        await service.submit_workflow(row.id, uuid4(), input_data)

    run = create.await_args.kwargs["run"]
    snapshot = create.await_args.kwargs["definition_snapshot"]
    input_data["nested"]["value"] = 2
    row.definition["metadata"]["source"]["version"] = 2
    assert run.input == {"nested": {"value": 1}}
    assert snapshot["metadata"] == {"source": {"version": 1}}


@pytest.mark.anyio
async def test_invalid_definition_does_not_write_commit_or_dispatch() -> None:
    service, db, _, dispatcher = subject(workflow_row(valid=False))
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=AsyncMock(),
        ) as create,
        pytest.raises(ValidationError) as captured,
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})

    issues = captured.value.details["issues"]
    assert {"code", "message", "node_id", "edge_id"} <= issues[0].keys()
    create.assert_not_awaited()
    db.commit.assert_not_awaited()
    dispatcher.dispatch.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [NotFoundError(), AuthorizationError()])
async def test_authorization_error_prevents_write_and_dispatch(error) -> None:
    service, db, workflow_service, dispatcher = subject()
    workflow_service.get_authorized_workflow.side_effect = error
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=AsyncMock(),
        ) as create,
        pytest.raises(type(error)),
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})
    create.assert_not_awaited()
    db.commit.assert_not_awaited()
    dispatcher.dispatch.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failure_point", ["create", "commit"])
async def test_database_failure_rolls_back_and_never_dispatches(failure_point: str) -> None:
    service, db, _, dispatcher = subject()
    create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    error = RuntimeError("database unavailable")
    if failure_point == "create":
        create.side_effect = error
    else:
        db.commit.side_effect = error
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=create,
        ),
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})
    db.rollback.assert_awaited_once_with()
    dispatcher.dispatch.assert_not_awaited()


@pytest.mark.anyio
async def test_dispatch_failure_reports_503_without_rolling_back_committed_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, db, _, dispatcher = subject()
    dispatcher.dispatch.side_effect = ConnectionError("redis://secret@broker unavailable")
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        ) as create,
        pytest.raises(ExternalServiceError) as captured,
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})

    assert captured.value.code == "WORKFLOW_DISPATCH_FAILED"
    assert captured.value.status_code == 503
    assert captured.value.details == {"run_id": str(create.await_args.kwargs["run"].id)}
    assert "secret" not in captured.value.message
    assert "secret" not in caplog.text
    assert "ConnectionError" in caplog.records[-1].exception_type
    db.commit.assert_awaited_once_with()
    db.rollback.assert_not_awaited()


@pytest.mark.anyio
async def test_cancellation_is_not_wrapped_or_reported_as_success() -> None:
    service, db, _, dispatcher = subject()
    dispatcher.dispatch.side_effect = asyncio.CancelledError()
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})
    db.commit.assert_awaited_once_with()
    db.rollback.assert_not_awaited()


@pytest.mark.anyio
async def test_cancellation_before_commit_rolls_back_and_never_dispatches() -> None:
    service, db, _, dispatcher = subject()
    db.commit.side_effect = asyncio.CancelledError()
    with (
        patch(
            "app.services.workflow.application.run.async_service.run_repo.create_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await service.submit_workflow(uuid4(), uuid4(), {})
    db.rollback.assert_awaited_once_with()
    dispatcher.dispatch.assert_not_awaited()
