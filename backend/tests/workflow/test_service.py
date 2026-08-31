"""Workflow application-service tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema, WorkflowUpdate
from app.services.workflow.facade import WorkflowService


def graph(nodes=None, edges=None):
    return WorkflowGraphSchema.model_validate(
        {
            "entry_node_id": "start",
            "nodes": nodes
            if nodes is not None
            else [{"id": "start", "kind": "start"}, {"id": "end", "kind": "end"}],
            "edges": edges
            if edges is not None
            else [{"id": "edge", "source": "start", "target": "end"}],
        }
    )


@pytest.mark.anyio
async def test_create_valid_and_invalid_blocks_repository():
    service = WorkflowService(AsyncMock())
    user_id = uuid4()
    with patch("app.services.workflow.facade.workflow_repo") as repo:
        repo.create_workflow = AsyncMock(return_value=SimpleNamespace())
        await service.create_workflow(user_id, WorkflowCreate(name="Valid", definition=graph()))
        assert repo.create_workflow.await_args.kwargs["user_id"] == user_id
        assert repo.create_workflow.await_args.kwargs["revision"] == 1
        with pytest.raises(ValidationError) as error:
            await service.create_workflow(
                user_id, WorkflowCreate(name="Bad", definition=graph(nodes=[]))
            )
        assert error.value.details["issues"][0]["code"] == "empty_workflow"
        assert repo.create_workflow.await_count == 1


@pytest.mark.anyio
async def test_ownership_update_and_empty_patch_rules():
    owner, other, workflow_id = uuid4(), uuid4(), uuid4()
    row = SimpleNamespace(
        id=workflow_id,
        user_id=owner,
        name="Old",
        description=None,
        definition=graph().model_dump(),
        revision=1,
    )
    service = WorkflowService(AsyncMock())
    with patch("app.services.workflow.facade.workflow_repo") as repo:
        repo.get_workflow_by_id = AsyncMock(return_value=row)
        repo.update_workflow = AsyncMock(return_value=row)
        await service.update_workflow(workflow_id, owner, WorkflowUpdate(name="New"))
        assert repo.update_workflow.await_args.kwargs["update_data"]["revision"] == 2
        await service.update_workflow(workflow_id, owner, WorkflowUpdate())
        assert repo.update_workflow.await_count == 1
        with pytest.raises(NotFoundError):
            await service.get_workflow(workflow_id, other)


@pytest.mark.anyio
async def test_list_delete_and_standalone_validation_do_not_bypass_ownership():
    owner = uuid4()
    row = SimpleNamespace(id=uuid4(), user_id=owner)
    service = WorkflowService(AsyncMock())
    with patch("app.services.workflow.facade.workflow_repo") as repo:
        repo.list_workflows_by_user = AsyncMock(return_value=[row])
        repo.count_workflows_by_user = AsyncMock(return_value=1)
        repo.get_workflow_by_id = AsyncMock(return_value=row)
        repo.delete_workflow = AsyncMock()
        assert (await service.list_workflows(owner))[1] == 1
        await service.delete_workflow(row.id, owner)
        repo.delete_workflow.assert_awaited_once()
        assert not service.validate_definition(graph(nodes=[])).is_valid


@pytest.mark.anyio
async def test_create_invalid_workflow_does_not_persist():
    service = WorkflowService(AsyncMock())
    with patch("app.services.workflow.facade.workflow_repo") as repo:
        repo.create_workflow = AsyncMock()
        with pytest.raises(ValidationError):
            await service.create_workflow(
                uuid4(), WorkflowCreate(name="Bad", definition=graph(nodes=[]))
            )
        repo.create_workflow.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_cross_owner_returns_not_found():
    owner, other = uuid4(), uuid4()
    row = SimpleNamespace(id=uuid4(), user_id=owner)
    service = WorkflowService(AsyncMock())
    with patch("app.services.workflow.facade.workflow_repo") as repo:
        repo.get_workflow_by_id = AsyncMock(return_value=row)
        repo.delete_workflow = AsyncMock()
        with pytest.raises(NotFoundError):
            await service.delete_workflow(row.id, other)
        repo.delete_workflow.assert_not_awaited()
