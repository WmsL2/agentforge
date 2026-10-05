"""Opt-in PostgreSQL proof that Workflow workspace scope is hardened at the database."""

from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from app.db.models.user import User, UserRole
from app.db.models.workflow.definition.model import Workflow
from app.repositories import workspace as workspace_repo
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole


@pytest.mark.anyio
async def test_workflow_workspace_scope_is_not_null_in_postgresql(postgres_session) -> None:
    user = User(
        id=uuid4(),
        email=f"workflow-scope-hardening-{uuid4()}@example.invalid",
        hashed_password=None,
        role=UserRole.USER.value,
    )
    postgres_session.add(user)
    await postgres_session.flush()
    workspace = await workspace_repo.create_workspace(
        postgres_session, name="Hardening", created_by_user_id=user.id
    )
    await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    workflow = await WorkflowService(
        postgres_session, WorkspaceAuthorizationService(postgres_session)
    ).create_workflow(
        workspace.id,
        user.id,
        WorkflowCreate(
            name="Scoped",
            definition=WorkflowGraphSchema(
                entry_node_id="start",
                nodes=[{"id": "start", "kind": "start"}, {"id": "end", "kind": "end"}],
                edges=[{"id": "start-end", "source": "start", "target": "end"}],
            ),
        ),
    )

    assert workflow.workspace_id == workspace.id
    is_nullable = await postgres_session.scalar(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'workflows' AND column_name = 'workspace_id'"
        )
    )
    assert is_nullable == "NO"
    workspace_fk = next(iter(Workflow.__table__.c.workspace_id.foreign_keys))
    user_fk = next(iter(Workflow.__table__.c.user_id.foreign_keys))
    assert workspace_fk.ondelete == "CASCADE"
    assert user_fk.ondelete == "SET NULL"

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            await postgres_session.execute(
                insert(Workflow).values(
                    id=uuid4(),
                    user_id=None,
                    workspace_id=None,
                    name="Invalid",
                    description=None,
                    definition={"entry_node_id": "start", "nodes": [], "edges": []},
                    revision=1,
                )
            )
            await postgres_session.flush()
