"""AsyncMock tests for workspace persistence primitives."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import workspace as workspace_repo
from app.services.workspace import WorkspaceRole


@pytest.mark.anyio
async def test_create_workspace_flushes_and_refreshes_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    workspace_id = uuid4()

    created = await workspace_repo.create_workspace(
        db,
        workspace_id=workspace_id,
        name="Research",
        created_by_user_id=uuid4(),
    )

    assert created.id == workspace_id
    assert created.name == "Research"
    db.add.assert_called_once_with(created)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_create_membership_flushes_and_refreshes_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    workspace_id, user_id = uuid4(), uuid4()

    created = await workspace_repo.create_membership(
        db, workspace_id=workspace_id, user_id=user_id, role=WorkspaceRole.OWNER
    )

    assert (created.workspace_id, created.user_id, created.role) == (workspace_id, user_id, "owner")
    db.add.assert_called_once_with(created)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_membership_uses_composite_identity() -> None:
    db = AsyncMock()
    workspace_id, user_id = uuid4(), uuid4()

    await workspace_repo.get_membership(db, workspace_id=workspace_id, user_id=user_id)

    db.get.assert_awaited_once_with(workspace_repo.WorkspaceMembership, (workspace_id, user_id))


@pytest.mark.anyio
async def test_list_workspaces_by_user_joins_memberships() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [SimpleNamespace()]
    db.execute.return_value = result
    user_id = uuid4()

    assert len(await workspace_repo.list_workspaces_by_user(db, user_id)) == 1

    statement = db.execute.await_args.args[0]
    assert "JOIN workspace_memberships ON workspace_memberships.workspace_id = workspaces.id" in str(statement)
    assert "workspace_memberships.user_id" in str(statement)
    assert "ORDER BY workspaces.created_at DESC" in str(statement)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_update_membership_role_flushes_and_refreshes_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    membership = SimpleNamespace(role="member")

    updated = await workspace_repo.update_membership_role(
        db, db_membership=membership, role=WorkspaceRole.ADMIN
    )

    assert updated is membership
    assert membership.role == "admin"
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(membership)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_primitives_flush_without_committing() -> None:
    db = AsyncMock()
    workspace = SimpleNamespace()
    membership = SimpleNamespace()
    db.get.side_effect = [workspace, membership]

    assert await workspace_repo.delete_workspace(db, uuid4()) is True
    assert await workspace_repo.delete_membership(db, workspace_id=uuid4(), user_id=uuid4()) is True

    assert db.delete.await_count == 2
    assert db.flush.await_count == 2
    db.commit.assert_not_awaited()
