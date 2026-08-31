"""Infrastructure-free JSON-compatible workflow graph serialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.services.workflow.domain import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
)


def serialize_workflow_graph(definition: WorkflowDefinition) -> dict[str, Any]:
    """Serialize graph-only workflow data for JSONB persistence."""
    return {
        "schema_version": definition.schema_version,
        "entry_node_id": definition.entry_node_id,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind.value,
                "config": node.config,
                "metadata": node.metadata,
            }
            for node in definition.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition,
                "metadata": edge.metadata,
            }
            for edge in definition.edges
        ],
        "metadata": definition.metadata,
    }


def deserialize_workflow_graph(
    payload: Mapping[str, Any],
    *,
    workflow_id: UUID,
    name: str,
    description: str | None,
    revision: int,
) -> WorkflowDefinition:
    """Reconstruct a domain definition from graph JSONB and resource columns."""
    required = ("schema_version", "entry_node_id", "nodes", "edges", "metadata")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Workflow graph payload is missing required keys: {', '.join(missing)}")
    nodes_data = payload["nodes"]
    edges_data = payload["edges"]
    metadata = payload["metadata"]
    if (
        not isinstance(nodes_data, list)
        or not isinstance(edges_data, list)
        or not isinstance(metadata, dict)
    ):
        raise TypeError("Workflow graph nodes/edges must be lists and metadata must be a dict.")
    nodes = tuple(_deserialize_node(item) for item in nodes_data)
    edges = tuple(_deserialize_edge(item) for item in edges_data)
    if not isinstance(payload["schema_version"], int) or not isinstance(
        payload["entry_node_id"], str
    ):
        raise TypeError("Workflow graph schema_version must be int and entry_node_id must be str.")
    return WorkflowDefinition(
        id=workflow_id,
        name=name,
        description=description,
        revision=revision,
        schema_version=payload["schema_version"],
        entry_node_id=payload["entry_node_id"],
        nodes=nodes,
        edges=edges,
        metadata=metadata,
    )


def _deserialize_node(data: Any) -> WorkflowNode:
    if not isinstance(data, Mapping):
        raise TypeError("Workflow node payload must be a mapping.")
    try:
        return WorkflowNode(
            id=_required_str(data, "id"),
            kind=WorkflowNodeKind(_required_str(data, "kind")),
            config=_required_dict(data, "config"),
            metadata=_required_dict(data, "metadata"),
        )
    except ValueError as error:
        raise ValueError(f"Invalid workflow node kind: {data.get('kind')!r}") from error


def _deserialize_edge(data: Any) -> WorkflowEdge:
    if not isinstance(data, Mapping):
        raise TypeError("Workflow edge payload must be a mapping.")
    return WorkflowEdge(
        id=_required_str(data, "id"),
        source=_required_str(data, "source"),
        target=_required_str(data, "target"),
        condition=data.get("condition"),
        metadata=_required_dict(data, "metadata"),
    )


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Workflow payload {key!r} must be a string.")
    return value


def _required_dict(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"Workflow payload {key!r} must be a dict.")
    return value
