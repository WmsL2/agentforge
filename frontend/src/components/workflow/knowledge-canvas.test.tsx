import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkflowCanvas } from "./workflow-canvas";
import { nextNode, connectionProblem, removeNode } from "@/lib/workflow/canvas-rules";
import { fromCanvasGraph, toCanvasGraph, type CanvasGraph } from "@/lib/workflow/canvas-adapter";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import { canonicalKnowledgeUuid, validKnowledgeTopK } from "@/lib/workflow/knowledge-config";
vi.mock("@xyflow/react", async (original) => {
  const actual = await original<typeof import("@xyflow/react")>();
  return {
    ...actual,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    ReactFlow: (props: Record<string, unknown>) => {
      const nodes = props.nodes as { id: string }[],
        edges = props.edges as { id: string }[];
      const nodeChange = props.onNodesChange as (changes: unknown[]) => void,
        connect = props.onConnect as (value: object) => void;
      return (
        <div>
          <output data-testid="nodes">{nodes.map((n) => n.id).join(",")}</output>
          <output data-testid="edges">{edges.map((e) => e.id).join(",")}</output>
          <button
            onClick={() => nodeChange([{ type: "select", id: "knowledge-1", selected: true }])}
          >
            flow select
          </button>
          <button
            onClick={() =>
              nodeChange([{ type: "position", id: "knowledge-1", position: { x: 500, y: 200 } }])
            }
          >
            flow move
          </button>
          <button
            onClick={() =>
              connect({
                source: "start",
                target: "knowledge-1",
                sourceHandle: null,
                targetHandle: null,
              })
            }
          >
            flow connect
          </button>
          <button
            onClick={() =>
              connect({
                source: "knowledge-1",
                target: "knowledge-1",
                sourceHandle: null,
                targetHandle: null,
              })
            }
          >
            flow bad edge
          </button>
        </div>
      );
    },
  };
});
const labels = {
  addValue: "Value",
  addAgent: "Agent",
  addApproval: "Approval",
  addKnowledge: "Add Knowledge",
  deleteNode: "Delete node",
  deleteEdge: "Delete edge",
};
function Harness({
  editable = true,
  onChange = vi.fn(),
  rejected = vi.fn(),
}: {
  editable?: boolean;
  onChange?: (g: CanvasGraph, d: boolean) => void;
  rejected?: (p: string) => void;
}) {
  const [graph, setGraph] = useState(() => toCanvasGraph(createDefaultWorkflowGraph()));
  return (
    <WorkflowCanvas
      graph={graph}
      editable={editable}
      labels={labels}
      onChange={(g, d) => {
        setGraph(g);
        onChange(g, d);
      }}
      onConnectionRejected={rejected}
    />
  );
}
it("adds unique Knowledge nodes with existing positioning, defaults and no automatic edges", async () => {
  const changed = vi.fn();
  render(<Harness onChange={changed} />);
  await userEvent.click(screen.getByRole("button", { name: "Add Knowledge" }));
  await userEvent.click(screen.getByRole("button", { name: "Add Knowledge" }));
  const g = changed.mock.calls.at(-1)![0] as CanvasGraph;
  expect(g.nodes.map((n) => n.id)).toEqual(["start", "end", "knowledge-1", "knowledge-2"]);
  expect(g.nodes[2]!.position).toEqual({ x: 480, y: 140 });
  expect(g.nodes[2]!.data.config).toEqual({
    knowledge_base_id: "",
    query_source: "literal",
    query: "",
    top_k: 5,
  });
  expect(g.edges).toHaveLength(1);
  expect(changed.mock.calls.every((c) => c[1] === true)).toBe(true);
});
it("keeps selection clean, moves Knowledge and deletes its incident edge", async () => {
  const changed = vi.fn();
  render(<Harness onChange={changed} />);
  await userEvent.click(screen.getByRole("button", { name: "Add Knowledge" }));
  await userEvent.click(screen.getByRole("button", { name: "flow select" }));
  expect(changed.mock.calls.at(-1)![1]).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "flow connect" }));
  expect(changed.mock.calls.at(-1)![0].edges).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "flow move" }));
  expect(
    changed.mock.calls.at(-1)![0].nodes.find((n: { id: string }) => n.id === "knowledge-1")
      .position,
  ).toEqual({ x: 500, y: 200 });
  await userEvent.click(screen.getByRole("button", { name: "Delete node" }));
  expect(screen.getByTestId("nodes").textContent).not.toContain("knowledge-1");
  expect(changed.mock.calls.at(-1)![0].edges).toHaveLength(1);
});
it("rejects a Knowledge self-loop through the actual canvas callback", async () => {
  const rejected = vi.fn();
  render(<Harness rejected={rejected} />);
  await userEvent.click(screen.getByRole("button", { name: "Add Knowledge" }));
  await userEvent.click(screen.getByRole("button", { name: "flow bad edge" }));
  expect(rejected).toHaveBeenCalledWith("self_loop");
});
it("disables Knowledge creation in read-only canvas", () => {
  const changed = vi.fn();
  render(<Harness editable={false} onChange={changed} />);
  expect(screen.getByRole("button", { name: "Add Knowledge" })).toBeDisabled();
  expect(changed).not.toHaveBeenCalled();
});
it("round trips both Knowledge modes and Agent binding without losing metadata", () => {
  const original = createDefaultWorkflowGraph();
  original.metadata = { keep: "root" };
  const canvas = toCanvasGraph(original),
    knowledge = nextNode(canvas, "knowledge");
  knowledge.data.config = {
    knowledge_base_id: "00000000-0000-0000-0000-000000000001",
    query_source: "workflow_input",
    input_key: "question",
    top_k: 1,
  };
  knowledge.data.metadata = { keep: "node", agentforge_canvas: { color: "blue" } };
  const agent = nextNode({ ...canvas, nodes: [...canvas.nodes, knowledge] }, "agent");
  agent.data.config = {
    runner: "langgraph",
    instruction: "Use evidence",
    knowledge_base_id: "00000000-0000-0000-0000-000000000001",
  };
  const graph = fromCanvasGraph(original, {
    ...canvas,
    nodes: [...canvas.nodes, knowledge, agent],
  });
  const restored = toCanvasGraph(graph);
  expect(restored.nodes[2]!.data.config).toEqual(knowledge.data.config);
  expect(restored.nodes[3]!.data.config).toEqual(agent.data.config);
  expect(graph.metadata).toEqual({ keep: "root" });
  expect(graph.nodes[2]!.metadata).toMatchObject({
    keep: "node",
    agentforge_canvas: { color: "blue", position: knowledge.position },
  });
  expect(graph.schema_version).toBe(1);
  expect(original.nodes).toHaveLength(2);
});
for (const [source, target, problem] of [
  ["knowledge-1", "knowledge-1", "self_loop"],
  ["knowledge-1", "start", "into_start"],
  ["end", "knowledge-1", "from_end"],
  ["start", "end", "duplicate_edge"],
  ["knowledge-1", "missing", "missing_endpoint"],
] as const)
  it(`keeps ${problem} rejection with Knowledge`, () => {
    const g = toCanvasGraph(createDefaultWorkflowGraph());
    g.nodes.push(nextNode(g, "knowledge"));
    expect(connectionProblem(g, { source, target })).toBe(problem);
  });
it("rejects a cycle involving Knowledge and removes linked edges immutably", () => {
  const g = toCanvasGraph(createDefaultWorkflowGraph());
  g.nodes.push(nextNode(g, "knowledge"));
  g.nodes.push(nextNode(g, "value"));
  g.edges.push({
    id: "k-v",
    source: "knowledge-1",
    target: "value-1",
    data: { condition: null, metadata: {} },
  });
  expect(connectionProblem(g, { source: "value-1", target: "knowledge-1" })).toBe("cycle");
  expect(removeNode(g, "knowledge-1").edges).not.toContainEqual(g.edges[1]);
  expect(g.nodes).toHaveLength(4);
});
for (const invalid of ["", "0", "6", "1.1", "NaN", "Infinity", "1e0"])
  it(`rejects top_k grammar ${invalid}`, () => expect(validKnowledgeTopK(invalid)).toBe(false));
for (const value of [
  "00000000-0000-0000-0000-000000000000",
  "00000000000000000000000000000001",
  "{00000000-0000-0000-0000-000000000001}",
  "urn:uuid:00000000-0000-0000-0000-000000000001",
])
  it(`accepts actual UUID spelling ${value}`, () =>
    expect(canonicalKnowledgeUuid(value)).not.toBeNull());
