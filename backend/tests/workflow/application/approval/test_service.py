"""Approval continuation and cancellation application tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.workflow.application.approval.service import (
    WorkflowApprovalConflictError,
    WorkflowApprovalService,
)
from app.services.workflow.execution.run import WorkflowRunStatus


def graph(value="old"):
    return {
        "schema_version": 1,
        "entry_node_id": "start",
        "metadata": {},
        "nodes": [
            {"id": "start", "kind": "start", "config": {}, "metadata": {}},
            {
                "id": "approval",
                "kind": "approval",
                "config": {"prompt": "Continue?"},
                "metadata": {},
            },
            {"id": "value", "kind": "value", "config": {"value": value}, "metadata": {}},
            {"id": "end", "kind": "end", "config": {}, "metadata": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "approval", "condition": None, "metadata": {}},
            {"id": "b", "source": "approval", "target": "value", "condition": None, "metadata": {}},
            {"id": "c", "source": "value", "target": "end", "condition": None, "metadata": {}},
        ],
    }


def rows(status="pending"):
    now, workflow_id, run_id, approval_id = (
        datetime(2026, 9, 15, tzinfo=UTC),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    workflow = SimpleNamespace(
        id=workflow_id, name="Current", description=None, definition=graph("new"), revision=2
    )
    run = SimpleNamespace(
        id=run_id,
        workflow_id=workflow_id,
        workflow_revision=1,
        definition_snapshot=graph("old"),
        status="paused",
        input={},
        node_outputs={"stale": True},
        output=None,
        error=None,
        started_at=now,
        finished_at=None,
    )
    approval = SimpleNamespace(
        id=approval_id,
        run_id=run_id,
        workflow_revision=1,
        node_id="approval",
        prompt="Continue?",
        status=status,
        created_at=now,
        decided_at=None,
        decided_by=None,
        decision_note=None,
    )
    checkpoint = SimpleNamespace(
        id=uuid4(),
        run_id=run_id,
        workflow_revision=1,
        sequence=2,
        completed_node_ids=["start"],
        node_outputs={"start": {}},
        pending_node_id="approval",
        interrupt={
            "type": "approval_required",
            "payload": {"node_id": "approval", "prompt": "Continue?"},
        },
        created_at=now,
    )
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
    resolved = SimpleNamespace(
        **{
            **checkpoint.__dict__,
            "sequence": 3,
            "completed_node_ids": ["start", "approval"],
            "node_outputs": {"start": {}, "approval": {"decision": "approved"}},
            "pending_node_id": None,
            "interrupt": None,
        }
    )
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    events = []
    decided = {}
    resolution_outputs = {}
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch(
            "app.services.workflow.application.approval.service.checkpoint_repo"
        ) as checkpoint_repo,
        patch(
            "app.services.workflow.application.approval.service.DurableWorkflowExecutionPersistence"
        ) as durability,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)

        async def update_approval(*_args, **kwargs):
            decided["approval"] = kwargs["approval"]
            events.append("approval")
            return approval

        approval_repo.update_approval_request_state = AsyncMock(side_effect=update_approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(
            side_effect=[checkpoint, resolved]
        )
        persistence = MagicMock()

        async def persist_node_completion(decision_run, **kwargs):
            assert decision_run.status is WorkflowRunStatus.PAUSED
            assert kwargs == {
                "completed_node_ids": ("start", "approval"),
                "pending_node_id": None,
            }
            resolution_outputs.update(decision_run.node_outputs)
            events.append("checkpoint")

        persistence.persist_node_completion = AsyncMock(side_effect=persist_node_completion)
        durability.return_value = persistence
        engine.resume.side_effect = lambda *_, **__: events.append("resume")
        result = await svc.approve(workflow.id, run.id, approval.id, uuid4(), note="ok")

    assert result is approval
    assert events == ["approval", "checkpoint", "resume"]
    approval_repo.get_approval_request_by_id_for_update.assert_awaited_once()
    durability.assert_called_once_with(db, run, next_sequence=3)
    definition = engine.resume.await_args.args[0]
    assert definition.nodes[2].config["value"] == "old"
    assert engine.resume.await_args.args[2].completed_node_ids == ("start", "approval")
    decided_approval = decided["approval"]
    assert resolution_outputs["approval"] == {
        "decision": "approved",
        "approval_id": str(approval.id),
        "decided_by": str(decided_approval.decided_by),
        "decided_at": decided_approval.decided_at.isoformat(),
        "decision_note": "ok",
    }


@pytest.mark.anyio
async def test_reject_cancels_without_resume_or_checkpoint():
    svc, db, workflow_service, engine = service()
    workflow, run, approval, checkpoint = rows()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch(
            "app.services.workflow.application.approval.service.checkpoint_repo"
        ) as checkpoint_repo,
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
        patch(
            "app.services.workflow.application.approval.service.checkpoint_repo"
        ) as checkpoint_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(return_value=checkpoint)
        with pytest.raises(WorkflowApprovalConflictError) as exc:
            await svc.approve(workflow.id, run.id, approval.id, uuid4())
    assert exc.value.code == "APPROVAL_RESUME_STATE_INVALID"


@pytest.mark.anyio
async def test_get_pending_checks_workflow_ownership_first():
    svc, _, workflow_service, _ = service()
    workflow, run, approval, _ = rows()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_pending_approval_by_run = AsyncMock(return_value=approval)
        result = await svc.get_pending_approval(workflow.id, run.id, uuid4())

    assert result is approval
    workflow_service.get_owned_workflow.assert_awaited_once()


@pytest.mark.anyio
async def test_run_from_another_workflow_is_not_found():
    svc, _, workflow_service, _ = service()
    workflow, run, _, _ = rows()
    run.workflow_id = uuid4()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with patch("app.services.workflow.application.approval.service.run_repo") as run_repo:
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        with pytest.raises(NotFoundError, match="Workflow run not found"):
            await svc.get_pending_approval(workflow.id, run.id, uuid4())


@pytest.mark.anyio
async def test_approval_from_another_run_is_not_found():
    svc, _, workflow_service, _ = service()
    workflow, run, approval, _ = rows()
    approval.run_id = uuid4()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        with pytest.raises(NotFoundError, match="Approval request not found"):
            await svc.approve(workflow.id, run.id, approval.id, uuid4())


@pytest.mark.anyio
async def test_non_paused_run_is_conflict_without_resume_or_commit():
    svc, db, workflow_service, engine = service()
    workflow, run, approval, _ = rows()
    run.status = "running"
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        with pytest.raises(WorkflowApprovalConflictError) as exc:
            await svc.approve(workflow.id, run.id, approval.id, uuid4())
    assert exc.value.code == "WORKFLOW_RUN_NOT_PAUSED"
    engine.resume.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_checkpoint_is_conflict_without_changes_or_resume():
    svc, _, workflow_service, engine = service()
    workflow, run, approval, _ = rows()
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch(
            "app.services.workflow.application.approval.service.checkpoint_repo"
        ) as checkpoint_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(return_value=None)
        with pytest.raises(WorkflowApprovalConflictError) as exc:
            await svc.approve(workflow.id, run.id, approval.id, uuid4())
    assert exc.value.code == "WORKFLOW_CHECKPOINT_NOT_FOUND"
    assert approval.status == "pending"
    assert run.status == "paused"
    engine.resume.assert_not_awaited()


@pytest.mark.anyio
async def test_downstream_failure_is_durably_persisted_after_approval():
    svc, db, workflow_service, engine = service()
    workflow, run, approval, checkpoint = rows()
    resolved = SimpleNamespace(
        **{
            **checkpoint.__dict__,
            "sequence": 3,
            "completed_node_ids": ["start", "approval"],
            "node_outputs": {"start": {}, "approval": {"decision": "approved"}},
            "pending_node_id": None,
            "interrupt": None,
        }
    )
    workflow_service.get_owned_workflow = AsyncMock(return_value=workflow)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
        patch(
            "app.services.workflow.application.approval.service.checkpoint_repo"
        ) as checkpoint_repo,
        patch(
            "app.services.workflow.application.approval.service.DurableWorkflowExecutionPersistence"
        ) as durability,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        run_repo.update_workflow_run_state = AsyncMock()
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)
        decided = {}

        async def update_approval(*_args, **kwargs):
            decided["approval"] = kwargs["approval"]
            return approval

        approval_repo.update_approval_request_state = AsyncMock(side_effect=update_approval)
        checkpoint_repo.get_latest_workflow_checkpoint = AsyncMock(
            side_effect=[checkpoint, resolved]
        )
        persistence = MagicMock()
        persistence.persist_node_completion = AsyncMock()
        durability.return_value = persistence

        async def fail_downstream(*_args, **_kwargs):
            _args[1].status = WorkflowRunStatus.FAILED

        engine.resume.side_effect = fail_downstream
        await svc.approve(workflow.id, run.id, approval.id, uuid4())

    assert decided["approval"].status.value == "approved"
    run_repo.update_workflow_run_state.assert_awaited_once_with(db, db_run=run, run=ANY)
    assert (
        run_repo.update_workflow_run_state.await_args.kwargs["run"].status
        is WorkflowRunStatus.FAILED
    )
    db.commit.assert_awaited_once()
