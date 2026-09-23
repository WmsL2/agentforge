"""Opt-in PostgreSQL proof for Workflow workspace RBAC."""

from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.db.models.user import User, UserRole
from app.repositories import workspace as workspace_repo
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema, WorkflowUpdate
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole


def create_data(name: str) -> WorkflowCreate:
    return WorkflowCreate(
        name=name,
        definition=WorkflowGraphSchema(
            entry_node_id="start",
            nodes=[{"id": "start", "kind": "start"}, {"id": "end", "kind": "end"}],
            edges=[{"id": "edge", "source": "start", "target": "end"}],
        ),
    )


@pytest.mark.anyio
async def test_workflow_workspace_rbac_postgresql(postgres_session) -> None:
    ids = {name: uuid4() for name in ("owner", "admin", "member", "outsider", "global")}
    postgres_session.add_all([
        User(id=user_id, email=f"workflow-rbac-{name}-{user_id.hex}@example.invalid", hashed_password=None,
             role=UserRole.ADMIN.value if name == "global" else "user", is_app_admin=name == "global")
        for name, user_id in ids.items()
    ])
    await postgres_session.flush()
    workspace = await workspace_repo.create_workspace(postgres_session, name="A", created_by_user_id=ids["owner"])
    for name, role in (("owner", WorkspaceRole.OWNER), ("admin", WorkspaceRole.ADMIN), ("member", WorkspaceRole.MEMBER)):
        await workspace_repo.create_membership(postgres_session, workspace_id=workspace.id, user_id=ids[name], role=role)
    service = WorkflowService(postgres_session, WorkspaceAuthorizationService(postgres_session))
    member_workflow = await service.create_workflow(workspace.id, ids["member"], create_data("Member"))
    owner_workflow = await service.create_workflow(workspace.id, ids["owner"], create_data("Owner"))
    assert (member_workflow.workspace_id, member_workflow.user_id) == (workspace.id, ids["member"])
    assert await service.get_workflow(owner_workflow.id, ids["member"]) is owner_workflow
    updated = await service.update_workflow(owner_workflow.id, ids["member"], WorkflowUpdate(name="Edited"))
    assert updated.revision == 2
    listed, _ = await service.list_workflows(workspace.id, ids["member"])
    assert {item.id for item in listed} >= {member_workflow.id, owner_workflow.id}
    with pytest.raises(AuthorizationError) as denied:
        await service.delete_workflow(owner_workflow.id, ids["member"])
    assert denied.value.code == "WORKSPACE_PERMISSION_DENIED"
    await service.delete_workflow(owner_workflow.id, ids["admin"])
    owner_delete = await service.create_workflow(workspace.id, ids["owner"], create_data("Owner delete"))
    await service.delete_workflow(owner_delete.id, ids["owner"])
    workspace_b = await workspace_repo.create_workspace(
        postgres_session, name="B", created_by_user_id=ids["owner"]
    )
    await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace_b.id,
        user_id=ids["owner"],
        role=WorkspaceRole.OWNER,
    )
    workflow_b = await service.create_workflow(workspace_b.id, ids["owner"], create_data("Workspace B"))
    for action in (
        service.get_workflow(workflow_b.id, ids["member"]),
        service.update_workflow(workflow_b.id, ids["member"], WorkflowUpdate(name="Denied")),
        service.delete_workflow(workflow_b.id, ids["member"]),
    ):
        with pytest.raises(NotFoundError) as denied:
            await action
        assert (denied.value.status_code, denied.value.message) == (404, "Workflow not found")
    with pytest.raises(NotFoundError, match="Workspace not found"):
        await service.create_workflow(workspace.id, ids["outsider"], create_data("Denied"))
    with pytest.raises(NotFoundError, match="Workspace not found"):
        await service.list_workflows(workspace.id, ids["outsider"])
    with pytest.raises(NotFoundError, match="Workflow not found"):
        await service.get_workflow(member_workflow.id, ids["global"])
    for action in (
        service.update_workflow(member_workflow.id, ids["outsider"], WorkflowUpdate(name="Denied")),
        service.delete_workflow(member_workflow.id, ids["outsider"]),
    ):
        with pytest.raises(NotFoundError, match="Workflow not found"):
            await action
    with pytest.raises(NotFoundError, match="Workspace not found"):
        await service.list_workflows(workspace.id, ids["global"])
