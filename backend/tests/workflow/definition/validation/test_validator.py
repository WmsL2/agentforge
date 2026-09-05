"""Tests for workflow definition validation."""

from uuid import uuid4

import pytest

from app.services.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowValidationCode,
    WorkflowValidator,
)


def node(node_id: str, kind: WorkflowNodeKind) -> WorkflowNode:
    return WorkflowNode(id=node_id, kind=kind)


def edge(edge_id: str, source: str, target: str, **kwargs: object) -> WorkflowEdge:
    return WorkflowEdge(id=edge_id, source=source, target=target, **kwargs)


def workflow(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...], entry: str = "start"
) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=uuid4(), name="Test workflow", entry_node_id=entry, nodes=nodes, edges=edges
    )


def codes(definition: WorkflowDefinition) -> set[WorkflowValidationCode]:
    return {issue.code for issue in WorkflowValidator().validate(definition).issues}


def linear_workflow() -> WorkflowDefinition:
    return workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("value", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("start-value", "start", "value"), edge("value-end", "value", "end")),
    )


def agent_workflow(config: dict[str, object]) -> WorkflowDefinition:
    return workflow(
        (
            node("start", WorkflowNodeKind.START),
            WorkflowNode(id="agent", kind=WorkflowNodeKind.AGENT, config=config),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("start-agent", "start", "agent"), edge("agent-end", "agent", "end")),
    )


def test_valid_linear_workflow():
    result = WorkflowValidator().validate(linear_workflow())

    assert result.is_valid
    assert result.issues == ()


def test_valid_branching_dag():
    definition = workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE),
            node("b", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-a", "start", "a"),
            edge("start-b", "start", "b"),
            edge("a-end", "a", "end"),
            edge("b-end", "b", "end"),
        ),
    )

    assert WorkflowValidator().validate(definition).is_valid


@pytest.mark.parametrize(
    "config",
    [
        {"runner": "langgraph", "instruction": "Analyze input."},
        {
            "runner": "langgraph",
            "instruction": " Analyze input. ",
            "model": "gpt-5-mini",
        },
    ],
)
def test_valid_agent_config(config: dict[str, object]):
    assert WorkflowValidator().validate(agent_workflow(config)).is_valid


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_REQUIRED),
        ({"runner": None, "instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_INVALID),
        ({"runner": 123, "instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_INVALID),
        ({"runner": "", "instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_INVALID),
        ({"runner": "   ", "instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_INVALID),
        ({"runner": "native", "instruction": "Run"}, WorkflowValidationCode.AGENT_RUNNER_INVALID),
        (
            {"runner": "LangGraph", "instruction": "Run"},
            WorkflowValidationCode.AGENT_RUNNER_INVALID,
        ),
        (
            {"runner": " langgraph ", "instruction": "Run"},
            WorkflowValidationCode.AGENT_RUNNER_INVALID,
        ),
    ],
)
def test_agent_runner_validation(config: dict[str, object], code: WorkflowValidationCode):
    issues = WorkflowValidator().validate(agent_workflow(config)).issues

    assert any(issue.code is code and issue.node_id == "agent" for issue in issues)


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"runner": "langgraph"}, WorkflowValidationCode.AGENT_INSTRUCTION_REQUIRED),
        (
            {"runner": "langgraph", "instruction": None},
            WorkflowValidationCode.AGENT_INSTRUCTION_INVALID,
        ),
        (
            {"runner": "langgraph", "instruction": 123},
            WorkflowValidationCode.AGENT_INSTRUCTION_INVALID,
        ),
        (
            {"runner": "langgraph", "instruction": ""},
            WorkflowValidationCode.AGENT_INSTRUCTION_INVALID,
        ),
        (
            {"runner": "langgraph", "instruction": "   "},
            WorkflowValidationCode.AGENT_INSTRUCTION_INVALID,
        ),
    ],
)
def test_agent_instruction_validation(config: dict[str, object], code: WorkflowValidationCode):
    issues = WorkflowValidator().validate(agent_workflow(config)).issues

    assert any(issue.code is code and issue.node_id == "agent" for issue in issues)


@pytest.mark.parametrize("model", [None, 123, "", "   "])
def test_agent_model_validation(model: object):
    issues = (
        WorkflowValidator()
        .validate(agent_workflow({"runner": "langgraph", "instruction": "Run", "model": model}))
        .issues
    )

    assert any(
        issue.code is WorkflowValidationCode.AGENT_MODEL_INVALID and issue.node_id == "agent"
        for issue in issues
    )


def test_agent_config_aggregates_all_field_issues():
    issues = (
        WorkflowValidator()
        .validate(
            agent_workflow(
                {
                    "runner": "native",
                    "instruction": "",
                    "model": 123,
                    "temperature": 0.5,
                }
            )
        )
        .issues
    )
    agent_issues = [issue for issue in issues if issue.node_id == "agent"]

    assert [issue.code for issue in agent_issues] == [
        WorkflowValidationCode.AGENT_RUNNER_INVALID,
        WorkflowValidationCode.AGENT_INSTRUCTION_INVALID,
        WorkflowValidationCode.AGENT_MODEL_INVALID,
        WorkflowValidationCode.AGENT_CONFIG_UNKNOWN_FIELD,
    ]


def test_agent_config_rejects_each_unknown_field_in_insertion_order():
    issues = (
        WorkflowValidator()
        .validate(
            agent_workflow(
                {
                    "runner": "langgraph",
                    "instruction": "Run",
                    "temperature": 0.5,
                    "tools": [],
                }
            )
        )
        .issues
    )
    unknown_issues = [
        issue for issue in issues if issue.code is WorkflowValidationCode.AGENT_CONFIG_UNKNOWN_FIELD
    ]

    assert [issue.message for issue in unknown_issues] == [
        "AGENT config field 'temperature' is not supported.",
        "AGENT config field 'tools' is not supported.",
    ]
    assert all(issue.node_id == "agent" for issue in unknown_issues)


def test_agent_validation_does_not_apply_to_other_node_kinds():
    definition = linear_workflow()
    definition.nodes[1].config["temperature"] = 0.5

    assert WorkflowValidator().validate(definition).is_valid


def test_agent_validation_does_not_mutate_node_config():
    definition = agent_workflow({"runner": "langgraph", "instruction": "Run"})
    config = definition.nodes[1].config
    before = config.copy()

    WorkflowValidator().validate(definition)

    assert config == before


@pytest.mark.parametrize(
    ("definition", "code"),
    [
        (workflow((), ()), WorkflowValidationCode.EMPTY_WORKFLOW),
        (
            workflow(
                (
                    node("start", WorkflowNodeKind.START),
                    node("start", WorkflowNodeKind.VALUE),
                    node("end", WorkflowNodeKind.END),
                ),
                (),
            ),
            WorkflowValidationCode.DUPLICATE_NODE_ID,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("same", "start", "end"), edge("same", "start", "end")),
            ),
            WorkflowValidationCode.DUPLICATE_EDGE_ID,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("one", "start", "end"), edge("two", "start", "end")),
            ),
            WorkflowValidationCode.DUPLICATE_EDGE,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("bad", "missing", "end"),),
            ),
            WorkflowValidationCode.MISSING_EDGE_SOURCE,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("bad", "start", "missing"),),
            ),
            WorkflowValidationCode.MISSING_EDGE_TARGET,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("loop", "start", "start"),),
            ),
            WorkflowValidationCode.SELF_LOOP,
        ),
        (
            workflow(
                (node("value", WorkflowNodeKind.VALUE), node("end", WorkflowNodeKind.END)),
                (),
                "value",
            ),
            WorkflowValidationCode.MISSING_START_NODE,
        ),
        (
            workflow(
                (
                    node("start", WorkflowNodeKind.START),
                    node("other", WorkflowNodeKind.START),
                    node("end", WorkflowNodeKind.END),
                ),
                (),
            ),
            WorkflowValidationCode.MULTIPLE_START_NODES,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (),
                "missing",
            ),
            WorkflowValidationCode.MISSING_ENTRY_NODE,
        ),
        (
            workflow(
                (
                    node("start", WorkflowNodeKind.START),
                    node("value", WorkflowNodeKind.VALUE),
                    node("end", WorkflowNodeKind.END),
                ),
                (),
                "value",
            ),
            WorkflowValidationCode.INVALID_ENTRY_KIND,
        ),
        (
            workflow(
                (
                    node("start", WorkflowNodeKind.START),
                    node("other", WorkflowNodeKind.VALUE),
                    node("end", WorkflowNodeKind.END),
                ),
                (),
                "other",
            ),
            WorkflowValidationCode.ENTRY_NODE_MISMATCH,
        ),
        (
            workflow(
                (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
                (edge("incoming", "end", "start"),),
            ),
            WorkflowValidationCode.START_HAS_INCOMING_EDGE,
        ),
        (
            workflow((node("start", WorkflowNodeKind.START),), ()),
            WorkflowValidationCode.MISSING_END_NODE,
        ),
        (
            workflow(
                (
                    node("start", WorkflowNodeKind.START),
                    node("end", WorkflowNodeKind.END),
                    node("value", WorkflowNodeKind.VALUE),
                ),
                (edge("start-end", "start", "end"), edge("end-value", "end", "value")),
            ),
            WorkflowValidationCode.END_HAS_OUTGOING_EDGE,
        ),
    ],
)
def test_reports_basic_structural_issues(
    definition: WorkflowDefinition, code: WorkflowValidationCode
):
    assert code in codes(definition)


def test_reports_isolated_node_and_unreachable_connected_subgraph():
    definition = workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
            node("x", WorkflowNodeKind.VALUE),
            node("y", WorkflowNodeKind.VALUE),
            node("isolated", WorkflowNodeKind.VALUE),
        ),
        (edge("start-a", "start", "a"), edge("a-end", "a", "end"), edge("x-y", "x", "y")),
    )
    issues = WorkflowValidator().validate(definition).issues

    assert any(
        issue.code is WorkflowValidationCode.ISOLATED_NODE and issue.node_id == "isolated"
        for issue in issues
    )
    assert {
        issue.node_id for issue in issues if issue.code is WorkflowValidationCode.UNREACHABLE_NODE
    } == {"x", "y", "isolated"}


def test_reports_multi_node_cycle_without_self_loop_cycle_noise():
    definition = workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE),
            node("b", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (
            edge("start-a", "start", "a"),
            edge("a-b", "a", "b"),
            edge("b-a", "b", "a"),
            edge("b-end", "b", "end"),
        ),
    )

    assert WorkflowValidationCode.CYCLE_DETECTED in codes(definition)


def test_self_loop_uses_its_dedicated_issue_without_generic_cycle_issue():
    definition = workflow(
        (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
        (edge("loop", "start", "start"),),
    )
    reported_codes = codes(definition)

    assert WorkflowValidationCode.SELF_LOOP in reported_codes
    assert WorkflowValidationCode.CYCLE_DETECTED not in reported_codes


def test_reports_reachable_non_end_sink():
    definition = workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("a", WorkflowNodeKind.VALUE),
            node("b", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("start-a", "start", "a"), edge("a-end", "a", "end"), edge("start-b", "start", "b")),
    )

    assert any(
        issue.code is WorkflowValidationCode.INVALID_TERMINAL_NODE and issue.node_id == "b"
        for issue in WorkflowValidator().validate(definition).issues
    )


def test_reports_no_terminal_path_when_end_is_unreachable():
    definition = workflow(
        (
            node("start", WorkflowNodeKind.START),
            node("value", WorkflowNodeKind.VALUE),
            node("end", WorkflowNodeKind.END),
        ),
        (edge("start-value", "start", "value"), edge("end-value", "end", "value")),
    )

    assert WorkflowValidationCode.NO_TERMINAL_PATH in codes(definition)


def test_rejects_every_non_none_edge_condition():
    definition = workflow(
        (node("start", WorkflowNodeKind.START), node("end", WorkflowNodeKind.END)),
        (edge("conditional", "start", "end", condition={}),),
    )

    assert WorkflowValidationCode.UNSUPPORTED_EDGE_CONDITION in codes(definition)


def test_validator_does_not_mutate_definition():
    definition = linear_workflow()
    before = (definition.nodes, definition.edges, definition.metadata.copy())

    WorkflowValidator().validate(definition)

    assert (definition.nodes, definition.edges, definition.metadata) == before


def test_malformed_graph_returns_issues_without_raising():
    definition = workflow(
        (node("start", WorkflowNodeKind.START), node("start", WorkflowNodeKind.VALUE)),
        (edge("bad", "missing", "start"),),
    )

    result = WorkflowValidator().validate(definition)

    assert not result.is_valid
    assert {issue.code for issue in result.issues} >= {
        WorkflowValidationCode.DUPLICATE_NODE_ID,
        WorkflowValidationCode.MISSING_EDGE_SOURCE,
    }
