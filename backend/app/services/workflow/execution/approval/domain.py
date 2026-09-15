"""Pure domain model for a human approval decision."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID


class ApprovalRequestStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRequestTransitionError(ValueError):
    """Raised when a decision is attempted after an approval is decided."""


@dataclass
class ApprovalRequest:
    id: UUID
    run_id: UUID
    workflow_revision: int
    node_id: str
    prompt: str
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    created_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decision_note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("Approval request prompt must be a non-blank string.")

    def approve(
        self,
        *,
        decided_by: UUID,
        note: str | None = None,
        at: datetime | None = None,
    ) -> None:
        self._decide(ApprovalRequestStatus.APPROVED, decided_by=decided_by, note=note, at=at)

    def reject(
        self,
        *,
        decided_by: UUID,
        note: str | None = None,
        at: datetime | None = None,
    ) -> None:
        self._decide(ApprovalRequestStatus.REJECTED, decided_by=decided_by, note=note, at=at)

    def _decide(
        self,
        status: ApprovalRequestStatus,
        *,
        decided_by: UUID,
        note: str | None,
        at: datetime | None,
    ) -> None:
        if self.status is not ApprovalRequestStatus.PENDING:
            raise ApprovalRequestTransitionError("Approval request has already been decided.")
        self.status = status
        self.decided_by = decided_by
        self.decision_note = note
        self.decided_at = at or datetime.now(UTC)
