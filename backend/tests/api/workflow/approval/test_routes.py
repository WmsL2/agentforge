"""Approval API tests using dependency overrides."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_workflow_approval_service
from app.core.exceptions import NotFoundError
from app.main import app
from app.services.workflow.application.approval import WorkflowApprovalConflictError


def approval_row(status="pending") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        workflow_revision=1,
        node_id="approval",
        prompt="Continue?",
        status=status,
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
        decided_at=None,
        decided_by=None,
        decision_note=None,
    )


@pytest.mark.anyio
async def test_pending_approval_route_returns_schema() -> None:
    user = SimpleNamespace(id=uuid4())
    approval = approval_row()

    class ApprovalService:
        async def get_pending_approval(self, workflow_id, run_id, user_id):
            assert (workflow_id, run_id, user_id) == (workflow_id, approval.run_id, user.id)
            return approval

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_approval_service] = ApprovalService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/workflows/{uuid4()}/runs/{approval.run_id}/approvals/pending"
            )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        assert response.json()["node_id"] == "approval"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_decision_routes_pass_note_and_return_updated_schema() -> None:
    user = SimpleNamespace(id=uuid4())
    approval = approval_row()
    calls = []

    class ApprovalService:
        async def approve(self, *args, note=None):
            calls.append(("approve", args, note))
            approval.status = "approved"
            approval.decided_by = user.id
            approval.decision_note = note
            approval.decided_at = datetime(2026, 9, 15, tzinfo=UTC)
            return approval

        async def reject(self, *args, note=None):
            calls.append(("reject", args, note))
            approval.status = "rejected"
            return approval

    workflow_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_approval_service] = ApprovalService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs/{approval.run_id}/approvals/{approval.id}/approve",
                json={"note": "Looks good"},
            )
            rejected = await client.post(
                f"/api/v1/workflows/{workflow_id}/runs/{approval.run_id}/approvals/{approval.id}/reject",
                json={"note": "Needs changes"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        assert rejected.status_code == 200
        assert calls[0][2] == "Looks good"
        assert calls[1][2] == "Needs changes"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_pending_not_found_and_already_decided_are_mapped_to_http_errors() -> None:
    user = SimpleNamespace(id=uuid4())
    approval = approval_row("approved")

    class ApprovalService:
        async def get_pending_approval(self, *_):
            raise NotFoundError(message="Pending approval request not found")

        async def approve(self, *_args, **_kwargs):
            raise WorkflowApprovalConflictError(code="APPROVAL_ALREADY_DECIDED")

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workflow_approval_service] = ApprovalService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            pending = await client.get(
                f"/api/v1/workflows/{uuid4()}/runs/{approval.run_id}/approvals/pending"
            )
            decided = await client.post(
                f"/api/v1/workflows/{uuid4()}/runs/{approval.run_id}/approvals/{approval.id}/approve",
                json={},
            )
        assert pending.status_code == 404
        assert decided.status_code == 409
        assert decided.json()["error"]["code"] == "APPROVAL_ALREADY_DECIDED"
    finally:
        app.dependency_overrides.clear()
