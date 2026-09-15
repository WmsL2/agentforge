"""Translate pure approval domain state to and from persistence values."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.workflow.execution.approval.domain import ApprovalRequest, ApprovalRequestStatus


def serialize_approval_request(approval: ApprovalRequest) -> dict[str, Any]:
    """Return persistence state excluding immutable identity and parent fields."""
    return {
        "status": approval.status.value,
        "decided_by": approval.decided_by,
        "decision_note": approval.decision_note,
        "created_at": approval.created_at,
        "decided_at": approval.decided_at,
    }


def deserialize_approval_request(values: Mapping[str, Any]) -> ApprovalRequest:
    """Reconstruct a pure approval request from one persistence record."""
    return ApprovalRequest(
        id=_uuid(values, "id"),
        run_id=_uuid(values, "run_id"),
        workflow_revision=_int(values, "workflow_revision"),
        node_id=_str(values, "node_id"),
        prompt=_str(values, "prompt"),
        status=ApprovalRequestStatus(_str(values, "status")),
        created_at=_datetime_or_none(values, "created_at"),
        decided_at=_datetime_or_none(values, "decided_at"),
        decided_by=_uuid_or_none(values, "decided_by"),
        decision_note=_str_or_none(values, "decision_note"),
    )


def _uuid(values: Mapping[str, Any], key: str) -> UUID:
    value = values[key]
    if not isinstance(value, UUID):
        raise TypeError(f"Approval persistence field {key!r} must be UUID.")
    return value


def _uuid_or_none(values: Mapping[str, Any], key: str) -> UUID | None:
    value = values.get(key)
    if value is not None and not isinstance(value, UUID):
        raise TypeError(f"Approval persistence field {key!r} must be UUID or None.")
    return value


def _int(values: Mapping[str, Any], key: str) -> int:
    value = values[key]
    if not isinstance(value, int):
        raise TypeError(f"Approval persistence field {key!r} must be int.")
    return value


def _str(values: Mapping[str, Any], key: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise TypeError(f"Approval persistence field {key!r} must be str.")
    return value


def _str_or_none(values: Mapping[str, Any], key: str) -> str | None:
    value = values.get(key)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"Approval persistence field {key!r} must be str or None.")
    return value


def _datetime_or_none(values: Mapping[str, Any], key: str) -> datetime | None:
    value = values.get(key)
    if value is not None and not isinstance(value, datetime):
        raise TypeError(f"Approval persistence field {key!r} must be datetime or None.")
    return value
