"""Opt-in PostgreSQL proof for workflow workspace persistence semantics."""

from uuid import uuid4

import pytest

from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.repositories import workflow as workflow_repo
from app.repositories import workspace as workspace_repo
from app.services.workspace.domain import WorkspaceRole


@pytest.mark.anyio
async def test_workflow_workspace_scope_preserves_creator_and_cascades_workspace(postgres_session) -> None:
    creator_id = uuid4()
    creator = User(id=creator_id, email=f"workflow-creator-{creator_id.hex}@example.invalid", hashed_password=None)
    postgres_session.add(creator)
    await postgres_session.flush()
    workspace = await workspace_repo.create_workspace(
        postgres_session, name="Workflow scope", created_by_user_id=creator_id
    )
    await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace.id,
        user_id=creator_id,
        role=WorkspaceRole.OWNER,
    )
    workflow = await workflow_repo.create_workflow(
        postgres_session,
        workflow_id=uuid4(),
        user_id=creator_id,
        workspace_id=workspace.id,
        name="Scoped workflow",
        description=None,
        definition={},
    )
    assert (workflow.user_id, workflow.workspace_id) == (creator_id, workspace.id)

    await postgres_session.delete(creator)
    await postgres_session.flush()
    await postgres_session.refresh(workflow)
    assert workflow.user_id is None
    assert await postgres_session.get(Workspace, workspace.id) is not None

    second_user_id = uuid4()
    second_user = User(
        id=second_user_id,
        email=f"workflow-workspace-delete-{second_user_id.hex}@example.invalid",
        hashed_password=None,
    )
    postgres_session.add(second_user)
    await postgres_session.flush()
    second_workspace = await workspace_repo.create_workspace(
        postgres_session, name="Cascade scope", created_by_user_id=second_user_id
    )
    second_workflow = await workflow_repo.create_workflow(
        postgres_session,
        workflow_id=uuid4(),
        user_id=second_user_id,
        workspace_id=second_workspace.id,
        name="Cascade workflow",
        description=None,
        definition={},
    )
    await postgres_session.delete(second_workspace)
    await postgres_session.flush()
    assert await workflow_repo.get_workflow_by_id(postgres_session, second_workflow.id) is None
