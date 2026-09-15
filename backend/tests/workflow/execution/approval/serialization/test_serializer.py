"""Tests for approval persistence serialization."""

from datetime import UTC, datetime
from uuid import uuid4

from app.services.workflow import ApprovalRequest, ApprovalRequestStatus
from app.services.workflow.execution.approval.serialization import (
    deserialize_approval_request,
    serialize_approval_request,
)


def test_approval_serialization_round_trips_all_persisted_fields() -> None:
    created_at = datetime(2026, 9, 15, tzinfo=UTC)
    decided_at = datetime(2026, 9, 15, 1, tzinfo=UTC)
    approval = ApprovalRequest(
        id=uuid4(),
        run_id=uuid4(),
        workflow_revision=2,
        node_id="approval",
        prompt="Continue?",
        status=ApprovalRequestStatus.APPROVED,
        created_at=created_at,
        decided_at=decided_at,
        decided_by=uuid4(),
        decision_note="Reviewed",
    )

    state = serialize_approval_request(approval)
    restored = deserialize_approval_request(
        {
            "id": approval.id,
            "run_id": approval.run_id,
            "workflow_revision": approval.workflow_revision,
            "node_id": approval.node_id,
            "prompt": approval.prompt,
            **state,
        }
    )

    assert restored == approval
