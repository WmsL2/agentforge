"""AsyncMock unit tests for approval-request persistence."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories.workflow.approval import repository as approval_repo
from app.services.workflow import ApprovalRequest, ApprovalRequestStatus


def approval(**kwargs: object) -> ApprovalRequest:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "workflow_revision": 3,
        "node_id": "approval",
        "prompt": "Continue?",
        "created_at": datetime(2026, 9, 15, tzinfo=UTC),
    }
    values.update(kwargs)
    return ApprovalRequest(**values)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_create_maps_domain_request_without_committing() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    request = approval()

    created = await approval_repo.create_approval_request(db, approval=request)

    assert (created.id, created.run_id, created.workflow_revision) == (
        request.id,
        request.run_id,
        3,
    )
    assert (created.node_id, created.prompt, created.status) == ("approval", "Continue?", "pending")
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(created)
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_get_by_id_and_pending_lookup_are_scoped() -> None:
    db = AsyncMock()
    stored = SimpleNamespace(id=uuid4())
    db.get.return_value = stored
    assert await approval_repo.get_approval_request_by_id(db, stored.id) is stored

    result = MagicMock()
    result.scalar_one_or_none.return_value = stored
    db.execute.return_value = result
    assert await approval_repo.get_pending_approval_by_run(db, uuid4()) is stored
    statement = db.execute.await_args.args[0]
    assert "approval_requests.status" in str(statement)
    assert statement.compile().params["status_1"] == "pending"
    assert "ORDER BY approval_requests.created_at DESC" in str(statement)


@pytest.mark.anyio
async def test_get_by_id_for_update_uses_row_lock_without_committing() -> None:
    db = AsyncMock()
    stored = SimpleNamespace(id=uuid4())
    result = MagicMock()
    result.scalar_one_or_none.return_value = stored
    db.execute.return_value = result

    assert await approval_repo.get_approval_request_by_id_for_update(db, stored.id) is stored

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "approval_requests.id" in sql
    db.commit.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [ApprovalRequestStatus.APPROVED, ApprovalRequestStatus.REJECTED])
async def test_update_maps_decision_without_committing(status: ApprovalRequestStatus) -> None:
    db = AsyncMock()
    db.add = MagicMock()
    request = approval()
    actor = uuid4()
    if status is ApprovalRequestStatus.APPROVED:
        request.approve(decided_by=actor, note="Approved")
    else:
        request.reject(decided_by=actor, note="Rejected")
    row = SimpleNamespace()

    updated = await approval_repo.update_approval_request_state(
        db, db_approval=row, approval=request
    )

    assert updated is row
    assert (row.status, row.decided_by, row.decision_note) == (
        status.value,
        actor,
        request.decision_note,
    )
    assert row.decided_at is not None
    db.commit.assert_not_awaited()
