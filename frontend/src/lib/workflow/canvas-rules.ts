import type { Connection } from "@xyflow/react";

import type { CanvasEdge, CanvasGraph, CanvasNode } from "./canvas-adapter";

export type ConnectionProblem =
  "missing_endpoint" | "self_loop" | "duplicate_edge" | "into_start" | "from_end" | "cycle";

function hasPath(edges: CanvasEdge[], start: string, target: string): boolean {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
  }
  const pending = [start];
  const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === target) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    pending.push(...(adjacency.get(current) ?? []));
  }
  return false;
}

export function connectionProblem(
  graph: CanvasGraph,
  connection: Pick<Connection, "source" | "target">,
): ConnectionProblem | null {
  const { source, target } = connection;
  if (!source || !target) return "missing_endpoint";
  if (source === target) return "self_loop";
  const sourceNode = graph.nodes.find((node) => node.id === source);
  const targetNode = graph.nodes.find((node) => node.id === target);
  if (!sourceNode || !targetNode) return "missing_endpoint";
  if (targetNode.data.kind === "start") return "into_start";
  if (sourceNode.data.kind === "end") return "from_end";
  if (graph.edges.some((edge) => edge.source === source && edge.target === target)) {
    return "duplicate_edge";
  }
  if (hasPath(graph.edges, target, source)) return "cycle";
  return null;
}

export function nextValueNode(graph: CanvasGraph): CanvasNode {
  let number = 1;
  while (graph.nodes.some((node) => node.id === `value-${number}`)) number += 1;
  return {
    id: `value-${number}`,
    type: "workflowNode",
    position: { x: graph.nodes.length * 240, y: 140 },
    data: { kind: "value", config: { value: null }, metadata: {} },
  };
}

export function canDeleteNode(graph: CanvasGraph, nodeId: string): boolean {
  const node = graph.nodes.find((item) => item.id === nodeId);
  if (!node || node.data.kind === "start") return false;
  if (node.data.kind !== "end") return true;
  return graph.nodes.filter((item) => item.data.kind === "end").length > 1;
}

export function removeNode(graph: CanvasGraph, nodeId: string): CanvasGraph {
  if (!canDeleteNode(graph, nodeId)) return graph;
  return {
    nodes: graph.nodes.filter((node) => node.id !== nodeId),
    edges: graph.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
  };
}
