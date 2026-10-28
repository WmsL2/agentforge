import { describe, expect, it } from "vitest";

import { toCanvasGraph } from "./canvas-adapter";
import { canDeleteNode, connectionProblem, nextValueNode, removeNode } from "./canvas-rules";
import { createDefaultWorkflowGraph } from "./default-graph";

describe("workflow canvas graph rules", () => {
  it("adds VALUE nodes with engine-compatible configuration", () => {
    const node = nextValueNode(toCanvasGraph(createDefaultWorkflowGraph()));
    expect(node).toMatchObject({ id: "value-1", data: { kind: "value", config: { value: null } } });
  });

  it("protects START and the final END", () => {
    const canvas = toCanvasGraph(createDefaultWorkflowGraph());
    expect(canDeleteNode(canvas, "start")).toBe(false);
    expect(canDeleteNode(canvas, "end")).toBe(false);
    expect(removeNode(canvas, "start")).toBe(canvas);
    expect(removeNode(canvas, "end")).toBe(canvas);

    canvas.nodes.push({
      id: "end-2",
      type: "workflowNode",
      position: { x: 480, y: 0 },
      data: { kind: "end", config: {}, metadata: {} },
    });
    expect(canDeleteNode(canvas, "end-2")).toBe(true);
    expect(removeNode(canvas, "end-2").nodes.some((node) => node.id === "end-2")).toBe(false);
  });

  it("removes a deletable node and all incident edges", () => {
    const canvas = toCanvasGraph(createDefaultWorkflowGraph());
    const value = nextValueNode(canvas);
    canvas.nodes.push(value);
    expect(connectionProblem(canvas, { source: "end", target: value.id })).toBe("from_end");
    canvas.edges.push({
      id: "value-end",
      source: value.id,
      target: "end",
      data: { condition: null, metadata: {} },
    });

    const result = removeNode(canvas, value.id);
    expect(result.nodes.some((node) => node.id === value.id)).toBe(false);
    expect(result.edges.some((edge) => edge.source === value.id || edge.target === value.id)).toBe(
      false,
    );
  });

  it.each([
    ["self loop", { source: "start", target: "start" }, "self_loop"],
    ["duplicate", { source: "start", target: "end" }, "duplicate_edge"],
    ["into START", { source: "end", target: "start" }, "into_start"],
    ["from END", { source: "end", target: "missing" }, "missing_endpoint"],
    ["missing endpoint", { source: "missing", target: "end" }, "missing_endpoint"],
  ])("rejects %s connections", (_label, connection, expected) => {
    expect(connectionProblem(toCanvasGraph(createDefaultWorkflowGraph()), connection)).toBe(
      expected,
    );
  });

  it("rejects directed cycles and accepts a legal connection", () => {
    const canvas = toCanvasGraph(createDefaultWorkflowGraph());
    const value = nextValueNode(canvas);
    canvas.nodes.push(value);
    canvas.edges = [
      {
        id: "start-value",
        source: "start",
        target: value.id,
        data: { condition: null, metadata: {} },
      },
      { id: "value-end", source: value.id, target: "end", data: { condition: null, metadata: {} } },
    ];

    expect(connectionProblem(canvas, { source: "end", target: "start" })).toBe("into_start");
    expect(connectionProblem(canvas, { source: value.id, target: "start" })).toBe("into_start");
    canvas.nodes.push({
      id: "value-2",
      type: "workflowNode",
      position: { x: 0, y: 0 },
      data: { kind: "value", config: {}, metadata: {} },
    });
    expect(connectionProblem(canvas, { source: "value-2", target: value.id })).toBe(null);
    canvas.edges.push({
      id: "value-2-value",
      source: "value-2",
      target: value.id,
      data: { condition: null, metadata: {} },
    });
    expect(connectionProblem(canvas, { source: value.id, target: "value-2" })).toBe("cycle");
  });
});
