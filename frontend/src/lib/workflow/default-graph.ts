import type { WorkflowGraph } from "@/types";

export function createDefaultWorkflowGraph(): WorkflowGraph {
  return {
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
  };
}
