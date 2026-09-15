"""Approval continuation and cancellation application tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.workflow.application.approval.service import (
    WorkflowApprovalConflictError,
    WorkflowApprovalService,
)


def graph(value="old"):
    return {"schema_version": 1, "entry_node_id": "start", "metadata": {}, "nodes": [{"id": "start", "kind": "start", "config": {}, "metadata": {}}, {"id": "approval", "kind": "approval", "config": {"prompt": "Continue?"}, "metadata": {}}, {"id": "value", "kind": "value", "config": {"value": value}, "metadata": {}}, {"id": "end", "kind": "end", "config": {}, "metadata": {}}], "edges": [{"id": "a", "source": "start", "target": "approval", "condition": None, "metadata": {}}, {"id": "b", "source": "approval", "target": "value", "condition": None, "metadata": {}}, {"id": "c", "source": "value", "target": "end", "condition": None, "metadata": {}}]}


def rows(status="pending"):
    now, workflow_id, run_id, approval_id = datetime(2026, 9, 15, tzinfo=UTC), uuid4(), uuid4(), uuid4()
    workflow = SimpleNamespace(id=workflow_id, name="Current", description=None, definition=graph("new"), revision=2)
    run = SimpleNamespace(id=run_id, workflow_id=workflow_id, workflow_revision=1, definition_snapshot=graph("old"), status="paused", input={}, node_outputs={"stale": True}, output=None, error=None, started_at=now, finished_at=None)
    approval = SimpleNamespace(id=approval_id, run_id=run_id, workflow_revision=1, node_id="approval", prompt="Continue?", status=status, created_at=now, decided_at=None, decided_by=None, decision_note=None)
    checkpoint = SimpleNamespace(id=uuid4(), run_id=run_id, workflow_revision=1, sequence=2, completed_node_ids=["start"], node_outputs={"start": {}}, pending_node_id="approval", interrupt={"type": "approval_required", "payload": {"node_id": "approval", "prompt": "Continue?"}}, created_at=now)
    return workflow, run, approval, checkpoint


def service():
    db, workflow_service, engine = AsyncMock(), AsyncMock(), MagicMock()
    engine.validate_resume = MagicMock()
    engine.resume = AsyncMock()
    return WorkflowApprovalService(db, workflow_service, engine), db, workflow_service, engine


@pytest.mark.anyio
async def test_approve_uses_snapshot_commits_resolution_before_engine_resume():
    svc, db, workflow_service, engine = service()
    workflow, run, approval, checkpoint = rows()
    resolved = SimpleNamespace(**{**checkpoint.__dict__, "sequence": 3, "completed_node_ids": ["start", "approval"], "node_outputs": {"start": {}, "approval": {"decision": "approved"}}, "pending_node_id": None, "interrupt": None})
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    events = []
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch("app.services.workflow.application.approval.service.checkpoint_repo") as checkpoint_repo,
        patch("app.services.workflow.application.approval.service.DurableWorkflowExecutionPersistence") as durability,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        approval_repo.update_approval_request_state = AsyncMock(side_effect=lambda *_, **__: events.append("approval") or approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(side_effect=[checkpoint, resolved])
        persistence = MagicMock()
        persistence.persist_node_completion = AsyncMock(side_effect=lambda *_, **__: events.append("checkpoint"))
        durability.return_value = persistence
        engine.resume.side_effect = lambda *_, **__: events.append("resume")
        result = await svc.approve(workflow.id, run.id, approval.id, uuid4(), note="ok")

    assert result is approval
    assert events == ["approval", "checkpoint", "resume"]
    approval_repo.get_approval_request_by_id_for_update.assert_awaited_once()
    definition = engine.resume.await_args.args[0]
    assert definition.nodes[2].config["value"] == "old"
    assert engine.resume.await_args.args[2].completed_node_ids == ("start", "approval")


@pytest.mark.anyio
async def test_reject_cancels_without_resume_or_checkpoint():
    svc, db, workflow_service, engine = service()
    workflow, run, approval, checkpoint = rows()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch("app.services.workflow.application.approval.service.checkpoint_repo") as checkpoint_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        run_repo.update_workflow_run_state = AsyncMock()
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        approval_repo.update_approval_request_state = AsyncMock(return_value=approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(return_value=checkpoint)
        await svc.reject(workflow.id, run.id, approval.id, uuid4())

    assert approval.status == "pending"
    persisted = run_repo.update_workflow_run_state.await_args.kwargs["run"]
    assert persisted.status.value == "cancelled" and persisted.finished_at is not None
    engine.resume.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["approved", "rejected"])
async def test_repeated_decision_is_locked_conflict(status):
    svc, _, workflow_service, engine = service()
    workflow, run, approval, _ = rows(status)
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        with pytest.raises(WorkflowApprovalConflictError) as exc:
            await svc.approve(workflow.id, run.id, approval.id, uuid4())
    assert exc.value.code == "APPROVAL_ALREADY_DECIDED"
    engine.resume.assert_not_awaited()


@pytest.mark.anyio
async def test_invalid_checkpoint_is_resume_state_conflict():
    svc, _, workflow_service, _ = service()
    workflow, run, approval, checkpoint = rows()
    checkpoint.pending_node_id = "wrong"
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch("app.services.workflow.application.approval.service.checkpoint_repo") as checkpoint_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(return_value=checkpoint)
        with pytest.raises(WorkflowApprovalConflictError) as exc:
            await svc.approve(workflow.id, run.id, approval.id, uuid4())
    assert exc.value.code == "APPROVAL_RESUME_STATE_INVALID"
