import { describe, expect, it } from "vitest";

import type { JsonObject, WorkflowGraph, WorkflowNodeKind } from "@/types";

import {
  CANVAS_METADATA_KEY,
  fromCanvasGraph,
  toCanvasGraph,
  type CanvasGraph,
} from "./canvas-adapter";

function graph(
  nodes: Array<{
    id: string;
    kind: WorkflowNodeKind;
    config?: JsonObject;
    metadata?: JsonObject;
  }>,
): WorkflowGraph {
  return {
    entry_node_id: "start",
    schema_version: 7,
    metadata: { tenant: "alpha", nested: { keep: true } },
    nodes: nodes.map((node) => ({
      id: node.id,
      kind: node.kind,
      config: node.config ?? {},
      metadata: node.metadata ?? {},
    })),
    edges: nodes.slice(1).map((node, index) => ({
      id: `edge-${index}`,
      source: nodes[index]!.id,
      target: node.id,
      condition: index === 0 ? { when: "ready" } : null,
      metadata: { order: index },
    })),
  };
}

describe("workflow canvas adapter", () => {
  it.each([
    [
      "minimal",
      graph([
        { id: "start", kind: "start" },
        { id: "end", kind: "end" },
      ]),
    ],
    [
      "VALUE",
      graph([
        { id: "start", kind: "start" },
        { id: "value", kind: "value", config: { value: 42 } },
        { id: "end", kind: "end" },
      ]),
    ],
    [
      "AGENT",
      graph([
        { id: "start", kind: "start" },
        {
          id: "agent",
          kind: "agent",
          config: { runner: "openai", instruction: "Keep this", model: "gpt" },
        },
        { id: "end", kind: "end" },
      ]),
    ],
    [
      "APPROVAL",
      graph([
        { id: "start", kind: "start" },
        { id: "approval", kind: "approval", config: { prompt: "Approve this" } },
        { id: "end", kind: "end" },
      ]),
    ],
  ])("preserves business fields for a %s graph", (_label, definition) => {
    const canvas = toCanvasGraph(definition);
    const restored = fromCanvasGraph(definition, canvas);

    expect(restored.entry_node_id).toBe("start");
    expect(restored.schema_version).toBe(7);
    expect(restored.metadata).toEqual(definition.metadata);
    expect(restored.nodes.map(({ id, kind, config }) => ({ id, kind, config }))).toEqual(
      definition.nodes.map(({ id, kind, config }) => ({ id, kind, config })),
    );
    expect(restored.edges).toEqual(definition.edges);
  });

  it("preserves multiple END nodes and node/edge ordering", () => {
    const definition = graph([
      { id: "start", kind: "start" },
      { id: "end-a", kind: "end" },
      { id: "end-b", kind: "end" },
    ]);
    const canvas = toCanvasGraph(definition);
    canvas.nodes.reverse();
    canvas.edges.reverse();

    const restored = fromCanvasGraph(definition, canvas);
    expect(restored.nodes.map((node) => node.id)).toEqual(["end-b", "end-a", "start"]);
    expect(restored.edges.map((edge) => edge.id)).toEqual(["edge-1", "edge-0"]);
  });

  it("uses deterministic positions for historical nodes without valid coordinates", () => {
    const definition = graph([
      {
        id: "start",
        kind: "start",
        metadata: { [CANVAS_METADATA_KEY]: { position: { x: "bad", y: 4 }, keep: "yes" } },
      },
      { id: "end", kind: "end" },
    ]);

    const first = toCanvasGraph(definition);
    const second = toCanvasGraph(definition);
    expect(first.nodes.map((node) => node.position)).toEqual([
      { x: 0, y: 0 },
      { x: 240, y: 0 },
    ]);
    expect(second).toEqual(first);
  });

  it("loads finite coordinates and persists moved positions without overwriting canvas metadata", () => {
    const definition = graph([
      {
        id: "start",
        kind: "start",
        metadata: {
          business: { keep: true },
          [CANVAS_METADATA_KEY]: { position: { x: 12, y: 34 }, zoomHint: 0.8 },
        },
      },
      { id: "end", kind: "end" },
    ]);
    const canvas = toCanvasGraph(definition);
    expect(canvas.nodes[0]?.position).toEqual({ x: 12, y: 34 });
    canvas.nodes[0]!.position = { x: -50, y: 99 };

    const restored = fromCanvasGraph(definition, canvas);
    expect(restored.nodes[0]?.metadata).toEqual({
      business: { keep: true },
      [CANVAS_METADATA_KEY]: { position: { x: -50, y: 99 }, zoomHint: 0.8 },
    });
  });

  it("does not mutate graph or canvas inputs", () => {
    const definition = graph([
      { id: "start", kind: "start", metadata: { nested: { value: 1 } } },
      { id: "end", kind: "end" },
    ]);
    const originalSnapshot = structuredClone(definition);
    const canvas = toCanvasGraph(definition);
    const canvasSnapshot = structuredClone(canvas);

    fromCanvasGraph(definition, canvas);
    expect(definition).toEqual(originalSnapshot);
    expect(canvas).toEqual(canvasSnapshot);
  });

  it("falls back to safe finite coordinates when canvas positions are malformed", () => {
    const definition = graph([
      { id: "start", kind: "start" },
      { id: "end", kind: "end" },
    ]);
    const canvas = toCanvasGraph(definition) as CanvasGraph;
    canvas.nodes[1]!.position = { x: Number.NaN, y: Number.POSITIVE_INFINITY };

    const restored = fromCanvasGraph(definition, canvas);
    expect(restored.nodes[1]?.metadata[CANVAS_METADATA_KEY]).toEqual({
      position: { x: 240, y: 0 },
    });
  });
});
