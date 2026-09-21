"""Metadata tests for workspace ORM models."""

from sqlalchemy import CheckConstraint

from app.db.models.workspace import Workspace, WorkspaceMembership
from app.services.workspace import WorkspaceRole


def test_workspace_table_has_the_expected_persistence_contract() -> None:
    table = Workspace.__table__

    assert table.name == "workspaces"
    assert set(table.columns.keys()) == {"id", "name", "created_by_user_id", "created_at", "updated_at"}
    assert table.c.name.type.length == 255
    assert table.c.created_by_user_id.nullable is True
    foreign_key = next(iter(table.c.created_by_user_id.foreign_keys))
    assert foreign_key.target_fullname == "users.id"
    assert foreign_key.ondelete == "SET NULL"


def test_workspace_membership_table_has_composite_key_fks_and_role_constraint() -> None:
    table = WorkspaceMembership.__table__

    assert table.name == "workspace_memberships"
    assert set(table.primary_key.columns.keys()) == {"workspace_id", "user_id"}
    assert next(iter(table.c.workspace_id.foreign_keys)).target_fullname == "workspaces.id"
    assert next(iter(table.c.workspace_id.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(table.c.user_id.foreign_keys)).target_fullname == "users.id"
    assert next(iter(table.c.user_id.foreign_keys)).ondelete == "CASCADE"
    assert table.c.role.type.length == 32
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.sqltext.text == "role IN ('owner', 'admin', 'member')"
        for constraint in table.constraints
    )
    assert {tuple(index.columns.keys()) for index in table.indexes} == {("user_id",)}


def test_workspace_membership_role_property_returns_domain_role() -> None:
    membership = WorkspaceMembership(role="owner")

    assert membership.workspace_role is WorkspaceRole.OWNER
