"""Opt-in real PostgreSQL proof for workspace persistence."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMembership
from app.repositories import workspace as workspace_repo
from app.services.workspace import WorkspaceRole


@pytest.mark.anyio
async def test_workspace_and_memberships_persist_in_postgresql(postgres_session) -> None:
    user_a_id, user_b_id = uuid4(), uuid4()
    user_a = User(id=user_a_id, email=f"workspace-owner-{user_a_id.hex}@example.invalid", hashed_password=None)
    user_b = User(id=user_b_id, email=f"workspace-member-{user_b_id.hex}@example.invalid", hashed_password=None)
    postgres_session.add_all([user_a, user_b])
    await postgres_session.flush()

    workspace = await workspace_repo.create_workspace(
        postgres_session,
        name="PostgreSQL workspace",
        created_by_user_id=user_a_id,
    )
    owner = await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace.id,
        user_id=user_a_id,
        role=WorkspaceRole.OWNER,
    )
    member = await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace.id,
        user_id=user_b_id,
        role=WorkspaceRole.MEMBER,
    )

    stored_workspace = await postgres_session.scalar(select(Workspace).where(Workspace.id == workspace.id))
    stored_memberships = list(
        (await postgres_session.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
        )).all()
    )
    assert stored_workspace is not None
    assert stored_workspace.created_by_user_id == user_a_id
    assert {item.user_id: item.role for item in stored_memberships} == {
        owner.user_id: "owner",
        member.user_id: "member",
    }
    assert [item.id for item in await workspace_repo.list_workspaces_by_user(postgres_session, user_a_id)] == [workspace.id]
    assert [item.id for item in await workspace_repo.list_workspaces_by_user(postgres_session, user_b_id)] == [workspace.id]
