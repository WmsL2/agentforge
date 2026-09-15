"""Tests for the pure approval-request domain."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.workflow import (
    ApprovalRequest,
    ApprovalRequestStatus,
    ApprovalRequestTransitionError,
)


def request(**kwargs: object) -> ApprovalRequest:
    values: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "workflow_revision": 1,
        "node_id": "approval",
        "prompt": "Approve execution?",
    }
    values.update(kwargs)
    return ApprovalRequest(**values)  # type: ignore[arg-type]


def test_request_defaults_to_pending() -> None:
    assert request().status is ApprovalRequestStatus.PENDING


@pytest.mark.parametrize(
    ("method", "status"),
    [("approve", ApprovalRequestStatus.APPROVED), ("reject", ApprovalRequestStatus.REJECTED)],
)
def test_pending_request_can_be_decided(method: str, status: ApprovalRequestStatus) -> None:
    approval = request()
    actor = uuid4()
    decided_at = datetime(2026, 9, 14, tzinfo=UTC)

    getattr(approval, method)(decided_by=actor, note="Reviewed", at=decided_at)

    assert approval.status is status
    assert approval.decided_by == actor
    assert approval.decision_note == "Reviewed"
    assert approval.decided_at == decided_at


def test_decided_request_rejects_repeated_and_cross_decisions() -> None:
    approval = request()
    approval.approve(decided_by=uuid4())

    with pytest.raises(ApprovalRequestTransitionError):
        approval.approve(decided_by=uuid4())
    with pytest.raises(ApprovalRequestTransitionError):
        approval.reject(decided_by=uuid4())

    rejected = request()
    rejected.reject(decided_by=uuid4())
    with pytest.raises(ApprovalRequestTransitionError):
        rejected.reject(decided_by=uuid4())
    with pytest.raises(ApprovalRequestTransitionError):
        rejected.approve(decided_by=uuid4())


@pytest.mark.parametrize("prompt", ["", "   ", None, 123])
def test_request_rejects_blank_or_non_string_prompt(prompt: object) -> None:
    with pytest.raises(ValueError):
        request(prompt=prompt)
