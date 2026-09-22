"""Opt-in real PostgreSQL proof for Workspace application service."""

from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.db.models.user import User
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole
from app.services.workspace.service import WorkspaceService


@pytest.mark.anyio
async def test_workspace_application_service_uses_postgresql_memberships(postgres_session) -> None:
    user_ids = {name: uuid4() for name in ("owner", "admin", "member", "outsider")}
    postgres_session.add_all(
        [
            User(
                id=user_id,
                email=f"workspace-app-{name}-{user_id.hex}@example.invalid",
                hashed_password=None,
            )
            for name, user_id in user_ids.items()
        ]
    )
    await postgres_session.flush()
    service = WorkspaceService(postgres_session, WorkspaceAuthorizationService(postgres_session))

    workspace = await service.create_workspace(user_ids["owner"], WorkspaceCreate(name="Application proof"))
    owner_members = await service.list_members(workspace.id, user_ids["owner"])
    assert [(membership.user_id, membership.role) for membership in owner_members] == [
        (user_ids["owner"], "owner")
    ]
    await service.add_member(
        workspace.id,
        user_ids["owner"],
        WorkspaceMemberCreate(user_id=user_ids["admin"], role=WorkspaceRole.ADMIN),
    )
    await service.add_member(
        workspace.id,
        user_ids["owner"],
        WorkspaceMemberCreate(user_id=user_ids["member"], role=WorkspaceRole.MEMBER),
    )
    for actor in ("owner", "admin", "member"):
        assert [item.id for item in await service.list_workspaces(user_ids[actor])] == [workspace.id]
    assert len(await service.list_members(workspace.id, user_ids["member"])) == 3

    with pytest.raises(AuthorizationError):
        await service.add_member(
            workspace.id, user_ids["member"], WorkspaceMemberCreate(user_id=user_ids["outsider"])
        )
    with pytest.raises(AuthorizationError):
        await service.update_workspace(
            workspace.id, user_ids["admin"], WorkspaceUpdate(name="Not allowed")
        )
    with pytest.raises(ValidationError):
        await service.update_member(
            workspace.id,
            user_ids["admin"],
            user_ids["member"],
            WorkspaceMemberUpdate(role=WorkspaceRole.OWNER),
        )
    with pytest.raises(AuthorizationError):
        await service.update_member(
            workspace.id,
            user_ids["admin"],
            user_ids["owner"],
            WorkspaceMemberUpdate(role=WorkspaceRole.MEMBER),
        )
    with pytest.raises(AuthorizationError):
        await service.delete_member(workspace.id, user_ids["admin"], user_ids["owner"])

    updated = await service.update_workspace(
        workspace.id, user_ids["owner"], WorkspaceUpdate(name="Updated")
    )
    assert updated.name == "Updated"
    with pytest.raises(NotFoundError):
        await service.get_workspace(workspace.id, user_ids["outsider"])
