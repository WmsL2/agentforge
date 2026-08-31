"""Pure structural validation for AgentForge workflow definitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from app.services.workflow.domain import WorkflowDefinition, WorkflowEdge, WorkflowNodeKind


class WorkflowValidationCode(str, Enum):  # noqa: UP042
    """Stable machine-readable workflow validation codes."""

    EMPTY_WORKFLOW = "empty_workflow"
    DUPLICATE_NODE_ID = "duplicate_node_id"
    DUPLICATE_EDGE_ID = "duplicate_edge_id"
    DUPLICATE_EDGE = "duplicate_edge"
    MISSING_EDGE_SOURCE = "missing_edge_source"
    MISSING_EDGE_TARGET = "missing_edge_target"
    SELF_LOOP = "self_loop"
    MISSING_START_NODE = "missing_start_node"
    MULTIPLE_START_NODES = "multiple_start_nodes"
    MISSING_ENTRY_NODE = "missing_entry_node"
    INVALID_ENTRY_KIND = "invalid_entry_kind"
    ENTRY_NODE_MISMATCH = "entry_node_mismatch"
    START_HAS_INCOMING_EDGE = "start_has_incoming_edge"
    MISSING_END_NODE = "missing_end_node"
    END_HAS_OUTGOING_EDGE = "end_has_outgoing_edge"
    ISOLATED_NODE = "isolated_node"
    UNREACHABLE_NODE = "unreachable_node"
    CYCLE_DETECTED = "cycle_detected"
    INVALID_TERMINAL_NODE = "invalid_terminal_node"
    NO_TERMINAL_PATH = "no_terminal_path"
    UNSUPPORTED_EDGE_CONDITION = "unsupported_edge_condition"


@dataclass(frozen=True)
class WorkflowValidationIssue:
    """One structured workflow validation problem."""

    code: WorkflowValidationCode
    message: str
    node_id: str | None = None
    edge_id: str | None = None


@dataclass(frozen=True)
class WorkflowValidationResult:
    """The deterministic result of validating a workflow definition."""

    issues: tuple[WorkflowValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


class WorkflowValidator:
    """Validate workflow structure without mutating its domain representation."""

    def validate(self, definition: WorkflowDefinition) -> WorkflowValidationResult:
        issues: list[WorkflowValidationIssue] = []

        def issue(
            code: WorkflowValidationCode,
            message: str,
            *,
            node_id: str | None = None,
            edge_id: str | None = None,
        ) -> None:
            issues.append(WorkflowValidationIssue(code, message, node_id, edge_id))

        node_counts: dict[str, int] = {}
        node_by_id = {}
        for node in definition.nodes:
            node_counts[node.id] = node_counts.get(node.id, 0) + 1
            if node_counts[node.id] == 1:
                node_by_id[node.id] = node
            else:
                issue(
                    WorkflowValidationCode.DUPLICATE_NODE_ID,
                    "Node ID must be unique.",
                    node_id=node.id,
                )

        if not definition.nodes:
            issue(
                WorkflowValidationCode.EMPTY_WORKFLOW, "A workflow must contain at least one node."
            )

        seen_edge_ids: set[str] = set()
        seen_unconditional_edges: set[tuple[str, str]] = set()
        valid_edges: list[WorkflowEdge] = []
        for edge in definition.edges:
            if edge.id in seen_edge_ids:
                issue(
                    WorkflowValidationCode.DUPLICATE_EDGE_ID,
                    "Edge ID must be unique.",
                    edge_id=edge.id,
                )
            seen_edge_ids.add(edge.id)
            if edge.condition is not None:
                issue(
                    WorkflowValidationCode.UNSUPPORTED_EDGE_CONDITION,
                    "Edge conditions are not supported in v0.2.",
                    edge_id=edge.id,
                )
            if edge.condition is None:
                key = (edge.source, edge.target)
                if key in seen_unconditional_edges:
                    issue(
                        WorkflowValidationCode.DUPLICATE_EDGE,
                        "Duplicate unconditional edge.",
                        edge_id=edge.id,
                    )
                seen_unconditional_edges.add(key)

            source_exists = edge.source in node_by_id
            target_exists = edge.target in node_by_id
            if not source_exists:
                issue(
                    WorkflowValidationCode.MISSING_EDGE_SOURCE,
                    "Edge source does not exist.",
                    edge_id=edge.id,
                )
            if not target_exists:
                issue(
                    WorkflowValidationCode.MISSING_EDGE_TARGET,
                    "Edge target does not exist.",
                    edge_id=edge.id,
                )
            if edge.source == edge.target:
                issue(
                    WorkflowValidationCode.SELF_LOOP,
                    "Self-loops are not allowed.",
                    node_id=edge.source,
                    edge_id=edge.id,
                )
            if source_exists and target_exists and edge.source != edge.target:
                valid_edges.append(edge)

        start_nodes = [node for node in definition.nodes if node.kind is WorkflowNodeKind.START]
        end_nodes = [node for node in definition.nodes if node.kind is WorkflowNodeKind.END]
        if not start_nodes:
            issue(WorkflowValidationCode.MISSING_START_NODE, "A workflow requires one START node.")
        elif len(start_nodes) > 1:
            issue(
                WorkflowValidationCode.MULTIPLE_START_NODES,
                "A workflow allows only one START node.",
            )
        if not end_nodes:
            issue(WorkflowValidationCode.MISSING_END_NODE, "A workflow requires an END node.")

        entry = node_by_id.get(definition.entry_node_id)
        entry_is_unambiguous = node_counts.get(definition.entry_node_id) == 1
        if entry is None:
            issue(
                WorkflowValidationCode.MISSING_ENTRY_NODE,
                "Entry node does not exist.",
                node_id=definition.entry_node_id,
            )
        elif entry_is_unambiguous and entry.kind is not WorkflowNodeKind.START:
            issue(
                WorkflowValidationCode.INVALID_ENTRY_KIND,
                "Entry node must be a START node.",
                node_id=entry.id,
            )
        if (
            len(start_nodes) == 1
            and entry_is_unambiguous
            and entry is not None
            and entry.id != start_nodes[0].id
        ):
            issue(
                WorkflowValidationCode.ENTRY_NODE_MISMATCH,
                "Entry node must match the START node.",
                node_id=entry.id,
            )

        incoming = dict.fromkeys(node_by_id, 0)
        outgoing = dict.fromkeys(node_by_id, 0)
        adjacency = {node_id: [] for node_id in node_by_id}
        for edge in valid_edges:
            outgoing[edge.source] += 1
            incoming[edge.target] += 1
            adjacency[edge.source].append(edge.target)

        for start in start_nodes:
            for edge in valid_edges:
                if edge.target == start.id:
                    issue(
                        WorkflowValidationCode.START_HAS_INCOMING_EDGE,
                        "START nodes cannot have incoming edges.",
                        node_id=start.id,
                        edge_id=edge.id,
                    )
        for end in end_nodes:
            for edge in valid_edges:
                if edge.source == end.id:
                    issue(
                        WorkflowValidationCode.END_HAS_OUTGOING_EDGE,
                        "END nodes cannot have outgoing edges.",
                        node_id=end.id,
                        edge_id=edge.id,
                    )
        for node in definition.nodes:
            if node_counts[node.id] == 1 and incoming[node.id] == 0 and outgoing[node.id] == 0:
                issue(WorkflowValidationCode.ISOLATED_NODE, "Node is isolated.", node_id=node.id)

        graph_is_reliable = (
            all(count == 1 for count in node_counts.values()) and entry_is_unambiguous
        )
        reachable: set[str] = set()
        if graph_is_reliable and entry is not None:
            queue = deque([entry.id])
            reachable.add(entry.id)
            while queue:
                current = queue.popleft()
                for target in adjacency[current]:
                    if target not in reachable:
                        reachable.add(target)
                        queue.append(target)
            for node in definition.nodes:
                if node.id not in reachable:
                    issue(
                        WorkflowValidationCode.UNREACHABLE_NODE,
                        "Node is unreachable from entry.",
                        node_id=node.id,
                    )

            indegree = incoming.copy()
            pending = deque(node_id for node_id in node_by_id if indegree[node_id] == 0)
            processed = 0
            while pending:
                current = pending.popleft()
                processed += 1
                for target in adjacency[current]:
                    indegree[target] -= 1
                    if indegree[target] == 0:
                        pending.append(target)
            if processed != len(node_by_id):
                cycle_node = next(node_id for node_id in node_by_id if indegree[node_id] > 0)
                issue(
                    WorkflowValidationCode.CYCLE_DETECTED,
                    "Workflow must be acyclic.",
                    node_id=cycle_node,
                )

            if end_nodes and not any(end.id in reachable for end in end_nodes):
                issue(
                    WorkflowValidationCode.NO_TERMINAL_PATH, "No END node is reachable from entry."
                )

            for node in definition.nodes:
                if outgoing[node.id] == 0 and node.kind is not WorkflowNodeKind.END:
                    issue(
                        WorkflowValidationCode.INVALID_TERMINAL_NODE,
                        "Only END nodes may be graph sinks.",
                        node_id=node.id,
                    )

        return WorkflowValidationResult(issues=tuple(issues))
