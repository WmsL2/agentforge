import type { Edge, Node, XYPosition } from "@xyflow/react";

import type {
  JsonObject,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeKind,
} from "@/types";

export const CANVAS_METADATA_KEY = "agentforge_canvas";
const DEFAULT_X_GAP = 240;

export interface CanvasNodeData extends Record<string, unknown> {
  kind: WorkflowNodeKind;
  config: JsonObject;
  metadata: JsonObject;
}

export interface CanvasEdgeData extends Record<string, unknown> {
  condition: JsonObject | null;
  metadata: JsonObject;
}

export type CanvasNode = Node<CanvasNodeData>;
export type CanvasEdge = Edge<CanvasEdgeData>;

export interface CanvasGraph {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function isFinitePosition(value: unknown): value is XYPosition {
  if (!value || typeof value !== "object") return false;
  const position = value as Record<string, unknown>;
  return Number.isFinite(position.x) && Number.isFinite(position.y);
}

function fallbackPosition(index: number): XYPosition {
  return { x: index * DEFAULT_X_GAP, y: 0 };
}

function readPosition(metadata: JsonObject, index: number): XYPosition {
  const namespace = metadata[CANVAS_METADATA_KEY];
  if (namespace && typeof namespace === "object" && !Array.isArray(namespace)) {
    const position = (namespace as JsonObject).position;
    if (isFinitePosition(position)) return clone(position);
  }
  return fallbackPosition(index);
}

export function toCanvasGraph(graph: WorkflowGraph): CanvasGraph {
  return {
    nodes: graph.nodes.map((node, index) => ({
      id: node.id,
      type: "workflowNode",
      position: readPosition(node.metadata, index),
      data: {
        kind: node.kind,
        config: clone(node.config),
        metadata: clone(node.metadata),
      },
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: {
        condition: clone(edge.condition),
        metadata: clone(edge.metadata),
      },
    })),
  };
}

function nodeFromCanvas(original: WorkflowGraph, node: CanvasNode, index: number): WorkflowNode {
  const previous = original.nodes.find((item) => item.id === node.id);
  const metadata = clone(node.data.metadata ?? previous?.metadata ?? {});
  const existingNamespace = metadata[CANVAS_METADATA_KEY];
  const namespace =
    existingNamespace && typeof existingNamespace === "object" && !Array.isArray(existingNamespace)
      ? clone(existingNamespace as JsonObject)
      : {};
  const position = isFinitePosition(node.position) ? clone(node.position) : fallbackPosition(index);

  return {
    id: node.id,
    kind: node.data.kind ?? previous?.kind ?? "value",
    config: clone(node.data.config ?? previous?.config ?? {}),
    metadata: {
      ...metadata,
      [CANVAS_METADATA_KEY]: { ...namespace, position },
    },
  };
}

function edgeFromCanvas(original: WorkflowGraph, edge: CanvasEdge): WorkflowEdge {
  const previous = original.edges.find((item) => item.id === edge.id);
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    condition: clone(edge.data?.condition ?? previous?.condition ?? null),
    metadata: clone(edge.data?.metadata ?? previous?.metadata ?? {}),
  };
}

export function fromCanvasGraph(original: WorkflowGraph, canvas: CanvasGraph): WorkflowGraph {
  return {
    entry_node_id: original.entry_node_id,
    schema_version: original.schema_version,
    metadata: clone(original.metadata),
    nodes: canvas.nodes.map((node, index) => nodeFromCanvas(original, node, index)),
    edges: canvas.edges.map((edge) => edgeFromCanvas(original, edge)),
  };
}
