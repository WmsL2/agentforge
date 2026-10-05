"""Opt-in PostgreSQL proof for Workspace-scoped run and approval authorization."""

from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.db.models.user import User, UserRole
from app.repositories import workspace as workspace_repo
from app.schemas.workflow import WorkflowCreate, WorkflowGraphSchema
from app.services.workflow import (
    ApprovalNodeExecutor,
    DeterministicNodeExecutor,
    DispatchingNodeExecutor,
    WorkflowApprovalService,
    WorkflowEngine,
    WorkflowRunService,
)
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspaceRole


def graph(*, approval: bool = False) -> WorkflowGraphSchema:
    nodes = [{"id": "start", "kind": "start"}]
    edges = []
    if approval:
        nodes.extend(
            [
                {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}},
                {"id": "end", "kind": "end"},
            ]
        )
        edges.extend(
            [
                {"id": "start-approval", "source": "start", "target": "approval"},
                {"id": "approval-end", "source": "approval", "target": "end"},
            ]
        )
    else:
        nodes.append({"id": "end", "kind": "end"})
        edges.append({"id": "start-end", "source": "start", "target": "end"})
    return WorkflowGraphSchema(entry_node_id="start", nodes=nodes, edges=edges)


def engine() -> WorkflowEngine:
    deterministic = DeterministicNodeExecutor()
    return WorkflowEngine(
        DispatchingNodeExecutor(
            deterministic_executor=deterministic,
            agent_executor=deterministic,
            approval_executor=ApprovalNodeExecutor(),
        )
    )


@pytest.mark.anyio
async def test_run_and_approval_workspace_rbac_postgresql(postgres_session) -> None:
    ids = {name: uuid4() for name in ("owner", "admin", "member", "outsider", "global")}
    postgres_session.add_all(
        [
            User(
                id=user_id,
                email=f"run-approval-rbac-{name}-{user_id.hex}@example.invalid",
                hashed_password=None,
                role=UserRole.ADMIN.value if name == "global" else UserRole.USER.value,
                is_app_admin=name == "global",
            )
            for name, user_id in ids.items()
        ]
    )
    await postgres_session.flush()
    workspace_a = await workspace_repo.create_workspace(
        postgres_session, name="Run RBAC A", created_by_user_id=ids["owner"]
    )
    for name, role in (
        ("owner", WorkspaceRole.OWNER),
        ("admin", WorkspaceRole.ADMIN),
        ("member", WorkspaceRole.MEMBER),
    ):
        await workspace_repo.create_membership(
            postgres_session, workspace_id=workspace_a.id, user_id=ids[name], role=role
        )
    workspace_b = await workspace_repo.create_workspace(
        postgres_session, name="Run RBAC B", created_by_user_id=ids["owner"]
    )
    await workspace_repo.create_membership(
        postgres_session,
        workspace_id=workspace_b.id,
        user_id=ids["owner"],
        role=WorkspaceRole.OWNER,
    )

    workflow_service = WorkflowService(
        postgres_session, WorkspaceAuthorizationService(postgres_session)
    )
    run_service = WorkflowRunService(postgres_session, workflow_service, engine())
    approval_service = WorkflowApprovalService(postgres_session, workflow_service, engine())
    workflow_a = await workflow_service.create_workflow(
        workspace_a.id, ids["owner"], WorkflowCreate(name="A", definition=graph())
    )
    workflow_a_other = await workflow_service.create_workflow(
        workspace_a.id, ids["owner"], WorkflowCreate(name="A other", definition=graph())
    )
    workflow_b = await workflow_service.create_workflow(
        workspace_b.id, ids["owner"], WorkflowCreate(name="B", definition=graph())
    )

    run_a = await run_service.execute_workflow(workflow_a.id, ids["member"], {})
    listed, total = await run_service.list_workflow_runs(workflow_a.id, ids["member"])
    assert {item.id for item in listed} >= {run_a.id}
    assert total >= 1
    assert await run_service.get_workflow_run(workflow_a.id, run_a.id, ids["member"]) is run_a
    assert await run_service.list_workflow_run_steps(workflow_a.id, run_a.id, ids["member"]) == []
    assert await run_service.list_workflow_trace_events(workflow_a.id, run_a.id, ids["member"]) == []

    for actor in (ids["outsider"], ids["global"]):
        for operation in (
            run_service.execute_workflow(workflow_a.id, actor, {}),
            run_service.get_workflow_run(workflow_a.id, run_a.id, actor),
        ):
            with pytest.raises(NotFoundError, match="Workflow not found"):
                await operation
    for operation in (
        run_service.execute_workflow(workflow_b.id, ids["member"], {}),
        run_service.get_workflow_run(workflow_b.id, run_a.id, ids["member"]),
    ):
        with pytest.raises(NotFoundError, match="Workflow not found"):
            await operation
    with pytest.raises(NotFoundError, match="Workflow run not found"):
        await run_service.get_workflow_run(workflow_a_other.id, run_a.id, ids["member"])

    approval_workflow = await workflow_service.create_workflow(
        workspace_a.id,
        ids["owner"],
        WorkflowCreate(name="Approval", definition=graph(approval=True)),
    )
    admin_run = await run_service.execute_workflow(approval_workflow.id, ids["owner"], {})
    admin_pending = await approval_service.get_pending_approval(
        approval_workflow.id, admin_run.id, ids["admin"]
    )
    for operation in (
        approval_service.get_pending_approval(approval_workflow.id, admin_run.id, ids["member"]),
        approval_service.approve(approval_workflow.id, admin_run.id, admin_pending.id, ids["member"]),
        approval_service.reject(approval_workflow.id, admin_run.id, admin_pending.id, ids["member"]),
    ):
        with pytest.raises(AuthorizationError) as denied:
            await operation
        assert (denied.value.status_code, denied.value.code) == (403, "WORKSPACE_PERMISSION_DENIED")
    assert await approval_service.approve(
        approval_workflow.id, admin_run.id, admin_pending.id, ids["admin"]
    ) is not None

    owner_run = await run_service.execute_workflow(approval_workflow.id, ids["owner"], {})
    owner_pending = await approval_service.get_pending_approval(
        approval_workflow.id, owner_run.id, ids["owner"]
    )
    assert await approval_service.reject(
        approval_workflow.id, owner_run.id, owner_pending.id, ids["owner"]
    ) is not None
    with pytest.raises(NotFoundError, match="Approval request not found"):
        await approval_service.approve(
            approval_workflow.id, owner_run.id, admin_pending.id, ids["owner"]
        )
