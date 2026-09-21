"""Opt-in real PostgreSQL proof for workspace authorization."""

from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.db.models.user import User
from app.repositories import workspace as workspace_repo
from app.services.workspace import (
    WorkspaceAuthorizationService,
    WorkspacePermission,
    WorkspaceRole,
)


@pytest.mark.anyio
async def test_workspace_authorization_uses_persisted_postgresql_memberships(postgres_session) -> None:
    user_ids = {role: uuid4() for role in ("owner", "admin", "member", "outsider")}
    postgres_session.add_all(
        [
            User(
                id=user_id,
                email=f"workspace-auth-{role}-{user_id.hex}@example.invalid",
                hashed_password=None,
            )
            for role, user_id in user_ids.items()
        ]
    )
    await postgres_session.flush()
    workspace = await workspace_repo.create_workspace(
        postgres_session,
        name="Authorization workspace",
        created_by_user_id=user_ids["owner"],
    )
    for actor, role in (
        ("owner", WorkspaceRole.OWNER),
        ("admin", WorkspaceRole.ADMIN),
        ("member", WorkspaceRole.MEMBER),
    ):
        await workspace_repo.create_membership(
            postgres_session,
            workspace_id=workspace.id,
            user_id=user_ids[actor],
            role=role,
        )

    service = WorkspaceAuthorizationService(postgres_session)
    assert (
        await service.require_permission(
            workspace.id, user_ids["owner"], WorkspacePermission.WORKSPACE_MANAGE
        )
    ).workspace_role is WorkspaceRole.OWNER
    for permission in (WorkspacePermission.APPROVAL_DECIDE, WorkspacePermission.MEMBER_MANAGE):
        assert (
            await service.require_permission(workspace.id, user_ids["admin"], permission)
        ).workspace_role is WorkspaceRole.ADMIN
    for permission in (
        WorkspacePermission.WORKFLOW_READ,
        WorkspacePermission.WORKFLOW_CREATE,
        WorkspacePermission.WORKFLOW_EDIT,
        WorkspacePermission.WORKFLOW_RUN,
        WorkspacePermission.RUN_READ,
    ):
        assert (
            await service.require_permission(workspace.id, user_ids["member"], permission)
        ).workspace_role is WorkspaceRole.MEMBER

    for actor, permission in (
        ("admin", WorkspacePermission.WORKSPACE_MANAGE),
        ("member", WorkspacePermission.APPROVAL_DECIDE),
        ("member", WorkspacePermission.WORKFLOW_DELETE),
    ):
        with pytest.raises(AuthorizationError) as error:
            await service.require_permission(workspace.id, user_ids[actor], permission)
        assert error.value.status_code == 403
    for permission in (WorkspacePermission.WORKFLOW_READ, WorkspacePermission.WORKSPACE_MANAGE):
        with pytest.raises(NotFoundError) as error:
            await service.require_permission(workspace.id, user_ids["outsider"], permission)
        assert error.value.status_code == 404
