"""Workspace-RBAC tests for WorkflowService CRUD."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema, WorkflowUpdate
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workspace.domain import WorkspacePermission


def graph() -> WorkflowGraphSchema:
    return WorkflowGraphSchema(entry_node_id="start", nodes=[{"id": "start", "kind": "start"}, {"id": "end", "kind": "end"}], edges=[{"id": "edge", "source": "start", "target": "end"}])


def service() -> tuple[WorkflowService, AsyncMock]:
    authorization = AsyncMock()
    return WorkflowService(AsyncMock(), authorization), authorization


@pytest.mark.anyio
async def test_create_authorizes_workspace_and_persists_creator_and_scope() -> None:
    subject, authorization = service()
    workspace_id, actor_id = uuid4(), uuid4()
    with patch("app.services.workflow.application.definition.service.workflow_repo.create_workflow", AsyncMock()) as create:
        await subject.create_workflow(workspace_id, actor_id, WorkflowCreate(name="New", definition=graph()))
    authorization.require_permission.assert_awaited_once_with(workspace_id, actor_id, WorkspacePermission.WORKFLOW_CREATE)
    assert create.await_args.kwargs["user_id"] == actor_id
    assert create.await_args.kwargs["workspace_id"] == workspace_id


@pytest.mark.anyio
async def test_list_uses_workspace_primitives_after_read_permission() -> None:
    subject, authorization = service()
    workspace_id, actor_id = uuid4(), uuid4()
    with patch("app.services.workflow.application.definition.service.workflow_repo") as repo:
        repo.list_workflows_by_workspace = AsyncMock(return_value=[])
        repo.count_workflows_by_workspace = AsyncMock(return_value=0)
        assert await subject.list_workflows(workspace_id, actor_id) == ([], 0)
    authorization.require_permission.assert_awaited_once_with(workspace_id, actor_id, WorkspacePermission.WORKFLOW_READ)


@pytest.mark.anyio
async def test_authorized_lookup_hides_missing_null_scope_and_non_member() -> None:
    subject, authorization = service()
    workflow_id, actor_id = uuid4(), uuid4()
    with patch("app.services.workflow.application.definition.service.workflow_repo.get_workflow_by_id", AsyncMock(return_value=None)), pytest.raises(NotFoundError, match="Workflow not found"):
        await subject.get_workflow(workflow_id, actor_id)
    row = SimpleNamespace(id=workflow_id, workspace_id=None)
    with patch("app.services.workflow.application.definition.service.workflow_repo.get_workflow_by_id", AsyncMock(return_value=row)), pytest.raises(NotFoundError, match="Workflow not found"):
        await subject.get_workflow(workflow_id, actor_id)
    row.workspace_id = uuid4()
    authorization.require_permission.side_effect = NotFoundError(message="Workspace not found")
    with patch("app.services.workflow.application.definition.service.workflow_repo.get_workflow_by_id", AsyncMock(return_value=row)), pytest.raises(NotFoundError, match="Workflow not found"):
        await subject.get_workflow(workflow_id, actor_id)


@pytest.mark.anyio
async def test_same_workspace_member_can_update_and_delete_permission_remains_403() -> None:
    subject, authorization = service()
    workspace_id, actor_id = uuid4(), uuid4()
    row = SimpleNamespace(id=uuid4(), workspace_id=workspace_id, user_id=uuid4(), name="Old", description=None, definition=graph().model_dump(), revision=1)
    with patch("app.services.workflow.application.definition.service.workflow_repo") as repo:
        repo.get_workflow_by_id = AsyncMock(return_value=row)
        repo.update_workflow = AsyncMock(return_value=row)
        repo.delete_workflow = AsyncMock()
        await subject.update_workflow(row.id, actor_id, WorkflowUpdate(name="New"))
        assert repo.update_workflow.await_args.kwargs["update_data"]["revision"] == 2
        authorization.require_permission.side_effect = AuthorizationError(code="WORKSPACE_PERMISSION_DENIED")
        with pytest.raises(AuthorizationError) as error:
            await subject.delete_workflow(row.id, actor_id)
    assert error.value.code == "WORKSPACE_PERMISSION_DENIED"
    repo.delete_workflow.assert_not_awaited()


@pytest.mark.anyio
async def test_get_owned_workflow_remains_creator_legacy_boundary() -> None:
    subject, _ = service()
    owner, other = uuid4(), uuid4()
    row = SimpleNamespace(user_id=owner)
    with patch("app.services.workflow.application.definition.service.workflow_repo.get_workflow_by_id", AsyncMock(return_value=row)):
        assert await subject.get_owned_workflow(uuid4(), owner) is row
        with pytest.raises(NotFoundError):
            await subject.get_owned_workflow(uuid4(), other)
