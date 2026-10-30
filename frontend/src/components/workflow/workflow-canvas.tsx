"use client";

import { useCallback, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui";
import type { CanvasEdge, CanvasGraph, CanvasNode } from "@/lib/workflow/canvas-adapter";
import {
  canDeleteNode,
  connectionProblem,
  nextValueNode,
  removeNode,
  type ConnectionProblem,
} from "@/lib/workflow/canvas-rules";
import { cn } from "@/lib/utils";

export interface WorkflowCanvasProps {
  graph: CanvasGraph;
  editable: boolean;
  invalidNodeIds?: ReadonlySet<string>;
  invalidEdgeIds?: ReadonlySet<string>;
  onChange: (graph: CanvasGraph, dirty: boolean) => void;
  onConnectionRejected: (problem: ConnectionProblem) => void;
  labels: {
    addValue: string;
    deleteNode: string;
    deleteEdge: string;
  };
}

function WorkflowNodeView({ id, data }: NodeProps<CanvasNode>) {
  return (
    <div className="bg-background min-w-36 rounded-lg border border-current px-4 py-3 shadow-sm">
      {data.kind !== "start" && <Handle type="target" position={Position.Left} />}
      <p className="text-muted-foreground text-[10px] font-semibold tracking-wider uppercase">
        {data.kind}
      </p>
      <p className="font-mono text-sm font-medium">{id}</p>
      {data.kind !== "end" && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

const nodeTypes: NodeTypes = { workflowNode: WorkflowNodeView };

function edgeId(graph: CanvasGraph, connection: Connection): string {
  const base = `${connection.source}-to-${connection.target}`;
  if (!graph.edges.some((edge) => edge.id === base)) return base;
  let suffix = 2;
  while (graph.edges.some((edge) => edge.id === `${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

export function WorkflowCanvas({
  graph,
  editable,
  invalidNodeIds = new Set(),
  invalidEdgeIds = new Set(),
  onChange,
  onConnectionRejected,
  labels,
}: WorkflowCanvasProps) {
  const selectedNode = graph.nodes.find((node) => node.selected);
  const selectedEdge = graph.edges.find((edge) => edge.selected);

  const nodes = useMemo(
    () =>
      graph.nodes.map((node) => ({
        ...node,
        draggable: editable,
        connectable: editable,
        deletable: editable && canDeleteNode(graph, node.id),
        className: cn(node.className, invalidNodeIds.has(node.id) && "ring-2 ring-destructive"),
      })),
    [editable, graph, invalidNodeIds],
  );
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        deletable: editable,
        className: cn(edge.className, invalidEdgeIds.has(edge.id) && "stroke-destructive"),
      })),
    [editable, graph.edges, invalidEdgeIds],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      const editableChanges = editable
        ? changes
        : changes.filter((change) => change.type === "select" || change.type === "dimensions");
      let remainingEnds = graph.nodes.filter((node) => node.data.kind === "end").length;
      const allowed = editableChanges.filter((change) => {
        if (change.type !== "remove") return true;
        const node = graph.nodes.find((item) => item.id === change.id);
        if (!node || node.data.kind === "start") return false;
        if (node.data.kind !== "end") return true;
        if (remainingEnds <= 1) return false;
        remainingEnds -= 1;
        return true;
      });
      const removedIds = new Set(
        allowed.filter((change) => change.type === "remove").map((change) => change.id),
      );
      const nextNodes = applyNodeChanges(allowed, graph.nodes);
      const nextEdges = removedIds.size
        ? graph.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target))
        : graph.edges;
      const dirty = allowed.some(
        (change) => change.type !== "select" && change.type !== "dimensions",
      );
      onChange({ nodes: nextNodes, edges: nextEdges }, dirty);
    },
    [editable, graph, onChange],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) => {
      const allowed = editable ? changes : changes.filter((change) => change.type === "select");
      const dirty = allowed.some(
        (change) => change.type === "add" || change.type === "remove" || change.type === "replace",
      );
      onChange({ ...graph, edges: applyEdgeChanges(allowed, graph.edges) }, dirty);
    },
    [editable, graph, onChange],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!editable) return;
      const problem = connectionProblem(graph, connection);
      if (problem) {
        onConnectionRejected(problem);
        return;
      }
      const edge: CanvasEdge = {
        id: edgeId(graph, connection),
        source: connection.source!,
        target: connection.target!,
        data: { condition: null, metadata: {} },
      };
      onChange({ ...graph, edges: addEdge(edge, graph.edges) }, true);
    },
    [editable, graph, onChange, onConnectionRejected],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!editable}
          onClick={() =>
            onChange({ ...graph, nodes: [...graph.nodes, nextValueNode(graph)] }, true)
          }
        >
          <Plus className="h-4 w-4" />
          {labels.addValue}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!editable || !selectedNode || !canDeleteNode(graph, selectedNode.id)}
          onClick={() => selectedNode && onChange(removeNode(graph, selectedNode.id), true)}
        >
          <Trash2 className="h-4 w-4" />
          {labels.deleteNode}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!editable || !selectedEdge}
          onClick={() =>
            selectedEdge &&
            onChange(
              { ...graph, edges: graph.edges.filter((edge) => edge.id !== selectedEdge.id) },
              true,
            )
          }
        >
          <Trash2 className="h-4 w-4" />
          {labels.deleteEdge}
        </Button>
      </div>

      <div className="bg-muted/20 h-[34rem] overflow-hidden rounded-xl border">
        <ReactFlow<CanvasNode, CanvasEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodesDraggable={editable}
          nodesConnectable={editable}
          elementsSelectable
          deleteKeyCode={null}
          fitView
          minZoom={0.2}
          maxZoom={2}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls showInteractive={editable} />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  );
}
