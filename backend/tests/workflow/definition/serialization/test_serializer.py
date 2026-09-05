"""Tests for workflow graph persistence serialization."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    deserialize_workflow_graph,
    serialize_workflow_graph,
)


def definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(),
        name="Graph",
        description="Description",
        entry_node_id="start",
        revision=3,
        schema_version=2,
        metadata={"team": "core"},
        nodes=(
            WorkflowNode("start", WorkflowNodeKind.START, {"input": 1}, {"label": "Start"}),
            WorkflowNode("value", WorkflowNodeKind.VALUE, {"value": 2}, {"label": "Value"}),
            WorkflowNode("end", WorkflowNodeKind.END),
        ),
        edges=(
            WorkflowEdge("first", "start", "value", metadata={"rank": 1}),
            WorkflowEdge(
                "second", "value", "end", condition={"future": True}, metadata={"rank": 2}
            ),
        ),
    )


def test_serialization_uses_graph_only_payload_and_preserves_order_and_values():
    payload = serialize_workflow_graph(definition())

    assert list(payload) == ["schema_version", "entry_node_id", "nodes", "edges", "metadata"]
    assert [node["id"] for node in payload["nodes"]] == ["start", "value", "end"]
    assert [edge["id"] for edge in payload["edges"]] == ["first", "second"]
    assert payload["nodes"][0]["kind"] == "start"
    assert payload["nodes"][1]["config"] == {"value": 2}
    assert payload["nodes"][0]["metadata"] == {"label": "Start"}
    assert payload["edges"][1]["condition"] == {"future": True}
    assert payload["edges"][0]["metadata"] == {"rank": 1}
    assert payload["metadata"] == {"team": "core"}


def test_serialization_does_not_mutate_source_definition():
    source = definition()
    before = deepcopy(source)

    serialize_workflow_graph(source)

    assert source == before


def test_deserialization_round_trips_domain_data_and_resource_columns():
    source = definition()
    restored = deserialize_workflow_graph(
        serialize_workflow_graph(source),
        workflow_id=source.id,
        name=source.name,
        description=source.description,
        revision=source.revision,
    )

    assert restored == source
    assert restored.nodes[0].kind is WorkflowNodeKind.START


def test_agent_node_round_trips_without_serializer_changes():
    source = definition()
    agent = WorkflowNode(
        "agent",
        WorkflowNodeKind.AGENT,
        {"runner": "langgraph", "instruction": "Analyze input.", "model": "gpt-5-mini"},
        {"label": "Agent"},
    )
    source.nodes = (source.nodes[0], agent, source.nodes[1], source.nodes[2])
    source.edges = (
        WorkflowEdge("first", "start", "agent"),
        WorkflowEdge("agent-value", "agent", "value"),
        source.edges[1],
    )

    restored = deserialize_workflow_graph(
        serialize_workflow_graph(source),
        workflow_id=source.id,
        name=source.name,
        description=source.description,
        revision=source.revision,
    )

    assert restored == source


def test_persisted_resource_columns_and_json_payload_reconstruct_definition():
    source = definition()
    persisted_row = type(
        "PersistedWorkflow",
        (),
        {
            "id": source.id,
            "name": source.name,
            "description": source.description,
            "revision": source.revision,
            "definition": serialize_workflow_graph(source),
        },
    )()

    restored = deserialize_workflow_graph(
        persisted_row.definition,
        workflow_id=persisted_row.id,
        name=persisted_row.name,
        description=persisted_row.description,
        revision=persisted_row.revision,
    )

    assert restored == source


def test_deserialization_rejects_invalid_kind_and_malformed_structure():
    payload = serialize_workflow_graph(definition())
    payload["nodes"][0]["kind"] = "unsupported"
    with pytest.raises(ValueError, match="Invalid workflow node kind"):
        deserialize_workflow_graph(
            payload, workflow_id=uuid4(), name="Graph", description=None, revision=1
        )

    with pytest.raises(ValueError, match="missing required keys"):
        deserialize_workflow_graph(
            {}, workflow_id=uuid4(), name="Graph", description=None, revision=1
        )
