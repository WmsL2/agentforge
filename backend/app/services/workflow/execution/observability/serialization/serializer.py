"""Pure JSONB-compatible mappings for execution-observability domain contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.workflow.definition.model.domain import WorkflowNodeKind
from app.services.workflow.execution.observability.domain import (
    RunStep,
    RunStepError,
    RunStepStatus,
    TraceEvent,
    TraceEventKind,
)


def serialize_run_step_state(step: RunStep) -> dict[str, Any]:
    """Map a run step's persisted state to JSONB-compatible values."""
    return {
        "status": step.status.value,
        "input": dict(step.input),
        "output": step.output,
        "error": None if step.error is None else {"code": step.error.code, "message": step.error.message},
        "metadata": dict(step.metadata),
        "started_at": step.started_at,
        "finished_at": step.finished_at,
    }


def deserialize_run_step(values: Mapping[str, Any]) -> RunStep:
    """Reconstruct a run step while restoring its domain enums and snapshots."""
    return RunStep(
        id=_uuid(values, "id"),
        run_id=_uuid(values, "run_id"),
        sequence=_int(values, "sequence"),
        node_id=_str(values, "node_id"),
        node_kind=WorkflowNodeKind(_str(values, "node_kind")),
        status=RunStepStatus(_str(values, "status")),
        input=_mapping(values, "input"),
        output=values.get("output"),
        error=_deserialize_run_step_error(values.get("error")),
        metadata=_mapping(values, "metadata"),
        started_at=_datetime(values, "started_at"),
        finished_at=_datetime_or_none(values, "finished_at"),
    )


def serialize_trace_event_state(event: TraceEvent) -> dict[str, Any]:
    """Map an append-only trace event's state to JSONB-compatible values."""
    return {
        "kind": event.kind.value,
        "payload": dict(event.payload),
        "created_at": event.created_at,
    }


def deserialize_trace_event(values: Mapping[str, Any]) -> TraceEvent:
    """Reconstruct an immutable trace event and reapply its payload snapshot."""
    return TraceEvent(
        id=_uuid(values, "id"),
        run_id=_uuid(values, "run_id"),
        step_id=_uuid_or_none(values, "step_id"),
        kind=TraceEventKind(_str(values, "kind")),
        payload=_mapping(values, "payload"),
        created_at=_datetime(values, "created_at"),
    )


def _deserialize_run_step_error(value: Any) -> RunStepError | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("Run step error persistence value must be a mapping or None.")
    return RunStepError(code=_str(value, "code"), message=_str(value, "message"))


def _uuid(values: Mapping[str, Any], key: str) -> UUID:
    value = values[key]
    if not isinstance(value, UUID):
        raise TypeError(f"Observability persistence field {key!r} must be UUID.")
    return value


def _uuid_or_none(values: Mapping[str, Any], key: str) -> UUID | None:
    value = values.get(key)
    if value is not None and not isinstance(value, UUID):
        raise TypeError(f"Observability persistence field {key!r} must be UUID or None.")
    return value


def _int(values: Mapping[str, Any], key: str) -> int:
    value = values[key]
    if not isinstance(value, int):
        raise TypeError(f"Observability persistence field {key!r} must be int.")
    return value


def _str(values: Mapping[str, Any], key: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise TypeError(f"Observability persistence field {key!r} must be str.")
    return value


def _mapping(values: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = values[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"Observability persistence field {key!r} must be a mapping.")
    return value


def _datetime(values: Mapping[str, Any], key: str) -> datetime:
    value = values[key]
    if not isinstance(value, datetime):
        raise TypeError(f"Observability persistence field {key!r} must be datetime.")
    return value


def _datetime_or_none(values: Mapping[str, Any], key: str) -> datetime | None:
    value = values.get(key)
    if value is not None and not isinstance(value, datetime):
        raise TypeError(f"Observability persistence field {key!r} must be datetime or None.")
    return value
