import { describe, expect, it } from "vitest";

import { createDefaultWorkflowGraph } from "./default-graph";

describe("createDefaultWorkflowGraph", () => {
  it("creates a valid minimal START to END graph without sharing mutable state", () => {
    const first = createDefaultWorkflowGraph();
    const second = createDefaultWorkflowGraph();

    expect(first).toEqual({
      entry_node_id: "start",
      nodes: [
        { id: "start", kind: "start", config: {}, metadata: {} },
        { id: "end", kind: "end", config: {}, metadata: {} },
      ],
      edges: [
        {
          id: "start-to-end",
          source: "start",
          target: "end",
          condition: null,
          metadata: {},
        },
      ],
      schema_version: 1,
      metadata: {},
    });
    expect(first).not.toBe(second);
    expect(first.nodes).not.toBe(second.nodes);
  });
});
