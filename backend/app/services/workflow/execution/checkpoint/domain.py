"""Immutable execution snapshots for durable workflow runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class WorkflowCheckpoint:
    """One append-only, framework-independent workflow execution snapshot."""

    id: UUID
    run_id: UUID
    workflow_revision: int
    sequence: int
    completed_node_ids: tuple[str, ...]
    node_outputs: Mapping[str, Any]
    pending_node_id: str | None = None
    interrupt: Mapping[str, Any] | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        completed_node_ids = tuple(self.completed_node_ids)
        if self.sequence < 1:
            raise ValueError("Workflow checkpoint sequence must be at least 1.")
        if len(set(completed_node_ids)) != len(completed_node_ids):
            raise ValueError("Workflow checkpoint completed node IDs must be unique.")
        if self.pending_node_id in completed_node_ids:
            raise ValueError("Workflow checkpoint pending node cannot already be completed.")

        object.__setattr__(self, "completed_node_ids", completed_node_ids)
        object.__setattr__(self, "node_outputs", MappingProxyType(dict(self.node_outputs)))
        if self.interrupt is not None:
            object.__setattr__(self, "interrupt", MappingProxyType(dict(self.interrupt)))
