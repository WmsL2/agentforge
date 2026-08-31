"""Tests for the pure workflow domain contracts."""

from uuid import uuid4

from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
)


def test_workflow_node_kinds_have_only_initial_semantic_values():
    assert {kind.value for kind in WorkflowNodeKind} == {"start", "value", "end"}


def test_workflow_node_mutable_defaults_are_isolated():
    first = WorkflowNode(id="first", kind=WorkflowNodeKind.VALUE)
    second = WorkflowNode(id="second", kind=WorkflowNodeKind.VALUE)

    first.config["value"] = 1
    first.metadata["label"] = "first"

    assert second.config == {}
    assert second.metadata == {}


def test_workflow_edge_metadata_defaults_are_isolated():
    first = WorkflowEdge(id="first", source="start", target="end")
    second = WorkflowEdge(id="second", source="start", target="end")

    first.metadata["label"] = "first"

    assert second.metadata == {}


def test_workflow_edge_keeps_future_condition_payload_without_interpretation():
    condition = {"operator": "equals", "value": "approved"}

    edge = WorkflowEdge(
        id="conditional",
        source="review",
        target="end",
        condition=condition,
    )

    assert edge.condition is condition


def test_workflow_definition_preserves_declared_node_order():
    start = WorkflowNode(id="start", kind=WorkflowNodeKind.START)
    value = WorkflowNode(id="value", kind=WorkflowNodeKind.VALUE)
    end = WorkflowNode(id="end", kind=WorkflowNodeKind.END)

    definition = WorkflowDefinition(
        id=uuid4(),
        name="Ordered workflow",
        entry_node_id="start",
        nodes=(start, value, end),
    )

    assert definition.nodes == (start, value, end)


def test_workflow_definition_preserves_declared_edge_order():
    first_edge = WorkflowEdge(id="first", source="start", target="value")
    second_edge = WorkflowEdge(id="second", source="value", target="end")

    definition = WorkflowDefinition(
        id=uuid4(),
        name="Ordered workflow",
        entry_node_id="start",
        edges=(first_edge, second_edge),
    )

    assert definition.edges == (first_edge, second_edge)


def test_workflow_definition_uses_initial_version_defaults():
    definition = WorkflowDefinition(id=uuid4(), name="Defaults", entry_node_id="start")

    assert definition.schema_version == 1
    assert definition.revision == 1


def test_workflow_definition_metadata_defaults_are_isolated():
    first = WorkflowDefinition(id=uuid4(), name="First", entry_node_id="start")
    second = WorkflowDefinition(id=uuid4(), name="Second", entry_node_id="start")

    first.metadata["owner"] = "team-a"

    assert second.metadata == {}


def test_invalid_graph_structure_can_be_represented_without_validation():
    duplicate_first = WorkflowNode(id="duplicate", kind=WorkflowNodeKind.START)
    duplicate_second = WorkflowNode(id="duplicate", kind=WorkflowNodeKind.END)
    self_loop = WorkflowEdge(id="self-loop", source="duplicate", target="duplicate")

    definition = WorkflowDefinition(
        id=uuid4(),
        name="Invalid but representable",
        entry_node_id="missing",
        nodes=(duplicate_first, duplicate_second),
        edges=(self_loop,),
    )

    assert definition.nodes == (duplicate_first, duplicate_second)
    assert definition.edges == (self_loop,)
