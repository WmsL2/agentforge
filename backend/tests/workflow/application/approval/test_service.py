"""Tests for ownership-safe approval application orchestration."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.workflow.application.approval.service import (
    WorkflowApprovalConflictError,
    WorkflowApprovalService,
)


def row(*, run_id=None, status="pending", workflow_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        run_id=run_id or uuid4(),
        workflow_revision=1,
        node_id="approval",
        prompt="Continue?",
        status=status,
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
        decided_at=None,
        decided_by=None,
        decision_note=None,
        workflow_id=workflow_id,
    )


def service() -> tuple[WorkflowApprovalService, AsyncMock, AsyncMock]:
    db = AsyncMock()
    workflow_service = AsyncMock()
    return WorkflowApprovalService(db, workflow_service), db, workflow_service


@pytest.mark.anyio
async def test_get_pending_checks_owner_and_run_parent() -> None:
    approval_service, _, workflow_service = service()
    workflow_id, run_id, user_id = uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(workflow_id=workflow_id)
    approval = row(run_id=run_id)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_pending_approval_by_run = AsyncMock(return_value=approval)

        assert await approval_service.get_pending_approval(workflow_id, run_id, user_id) is approval

    workflow_service.get_owned_workflow.assert_awaited_once_with(workflow_id, user_id)
    approval_repo.get_pending_approval_by_run.assert_awaited_once_with(approval_service.db, run_id)


@pytest.mark.anyio
async def test_get_pending_hides_run_workflow_mismatch() -> None:
    approval_service, _, _ = service()
    with patch("app.services.workflow.application.approval.service.run_repo") as run_repo:
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=SimpleNamespace(workflow_id=uuid4()))
        with pytest.raises(NotFoundError, match="Workflow run not found"):
            await approval_service.get_pending_approval(uuid4(), uuid4(), uuid4())


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "status", "note"), [("approve", "approved", "Looks good"), ("reject", "rejected", "Needs work")])
async def test_decision_updates_request_once_and_keeps_run_paused(method, status, note) -> None:
    approval_service, db, _ = service()
    workflow_id, run_id, approval_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(workflow_id=workflow_id, status="paused")
    approval = row(run_id=run_id)
    approval.id = approval_id
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(return_value=run)
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=approval)

        async def update(_, *, db_approval, approval):
            db_approval.status = approval.status.value
            db_approval.decided_by = approval.decided_by
            db_approval.decision_note = approval.decision_note
            db_approval.decided_at = approval.decided_at
            return db_approval

        approval_repo.update_approval_request_state = AsyncMock(side_effect=update)
        result = await getattr(approval_service, method)(
            workflow_id, run_id, approval_id, user_id, note=note
        )

    assert (result.status, result.decided_by, result.decision_note) == (status, user_id, note)
    assert result.decided_at is not None
    assert run.status == "paused"
    db.commit.assert_awaited_once()
    approval_repo.get_approval_request_by_id_for_update.assert_awaited_once_with(
        approval_service.db, approval_id
    )
    approval_repo.get_approval_request_by_id.assert_not_called()


@pytest.mark.anyio
async def test_decision_hides_approval_from_another_run() -> None:
    approval_service, _, _ = service()
    workflow_id, run_id = uuid4(), uuid4()
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(
            return_value=SimpleNamespace(workflow_id=workflow_id, status="paused")
        )
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=row(run_id=uuid4()))
        with pytest.raises(NotFoundError, match="Approval request not found"):
            await approval_service.approve(workflow_id, run_id, uuid4(), uuid4())


@pytest.mark.anyio
@pytest.mark.parametrize("approval_status", ["approved", "rejected"])
async def test_already_decided_request_is_conflict(approval_status) -> None:
    approval_service, db, _ = service()
    workflow_id, run_id = uuid4(), uuid4()
    stored = row(run_id=run_id, status=approval_status)
    with (
        patch("app.services.workflow.application.approval.service.run_repo") as run_repo,
        patch("app.services.workflow.application.approval.service.approval_repo") as approval_repo,
    ):
        run_repo.get_workflow_run_by_id = AsyncMock(
            return_value=SimpleNamespace(workflow_id=workflow_id, status="paused")
        )
        approval_repo.get_approval_request_by_id_for_update = AsyncMock(return_value=stored)
        with pytest.raises(WorkflowApprovalConflictError) as exception:
            await approval_service.approve(workflow_id, run_id, stored.id, uuid4())

    assert exception.value.code == "APPROVAL_ALREADY_DECIDED"
    assert db.commit.await_count == 0


@pytest.mark.anyio
async def test_decision_requires_paused_run() -> None:
    approval_service, db, _ = service()
    workflow_id, run_id = uuid4(), uuid4()
    with patch("app.services.workflow.application.approval.service.run_repo") as run_repo:
        run_repo.get_workflow_run_by_id = AsyncMock(
            return_value=SimpleNamespace(workflow_id=workflow_id, status="completed")
        )
        with pytest.raises(WorkflowApprovalConflictError) as exception:
            await approval_service.reject(workflow_id, run_id, uuid4(), uuid4())

    assert exception.value.code == "WORKFLOW_RUN_NOT_PAUSED"
    assert db.commit.await_count == 0
