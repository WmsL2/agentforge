import { useState, type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Connection, EdgeChange, NodeChange } from "@xyflow/react";

import {
  toCanvasGraph,
  type CanvasEdge,
  type CanvasGraph,
  type CanvasNode,
} from "@/lib/workflow/canvas-adapter";
import type { ConnectionProblem } from "@/lib/workflow/canvas-rules";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return {
    ...actual,
    ReactFlow: ({
      nodes,
      edges,
      onNodesChange,
      onEdgesChange,
      onConnect,
      children,
    }: {
      nodes: CanvasNode[];
      edges: CanvasEdge[];
      onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
      onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
      onConnect: (connection: Connection) => void;
      children: ReactNode;
    }) => (
      <div>
        <p>nodes:{nodes.map((node) => node.id).join(",")}</p>
        <p>edges:{edges.map((edge) => edge.id).join(",")}</p>
        <p>positions:{nodes.map((node) => `${node.id}@${node.position.x}`).join(",")}</p>
        <p>
          measured:
          {nodes
            .map(
              (node) =>
                `${node.id}@${node.measured?.width ?? "unset"}x${node.measured?.height ?? "unset"}`,
            )
            .join(",")}
        </p>
        <p>
          selected-nodes:
          {nodes
            .filter((node) => node.selected)
            .map((node) => node.id)
            .join(",")}
        </p>
        <p>
          selected-edges:
          {edges
            .filter((edge) => edge.selected)
            .map((edge) => edge.id)
            .join(",")}
        </p>
        {nodes.map((node) => (
          <div key={node.id}>
            <button
              onClick={() => onNodesChange([{ type: "select", id: node.id, selected: true }])}
            >
              select node {node.id}
            </button>
            <button
              onClick={() =>
                onNodesChange([
                  { type: "position", id: node.id, position: { x: 500, y: 200 }, dragging: false },
                ])
              }
            >
              move node {node.id}
            </button>
            <button onClick={() => onNodesChange([{ type: "remove", id: node.id }])}>
              remove node event {node.id}
            </button>
            <button
              onClick={() =>
                onNodesChange([
                  {
                    type: "dimensions",
                    id: node.id,
                    dimensions: { width: 180, height: 72 },
                    setAttributes: true,
                  },
                ])
              }
            >
              measure node {node.id}
            </button>
          </div>
        ))}
        {edges.map((edge) => (
          <div key={edge.id}>
            <button
              onClick={() => onEdgesChange([{ type: "select", id: edge.id, selected: true }])}
            >
              select edge {edge.id}
            </button>
            <button onClick={() => onEdgesChange([{ type: "remove", id: edge.id }])}>
              remove edge event {edge.id}
            </button>
          </div>
        ))}
        <button
          onClick={() =>
            onConnect({ source: "start", target: "start", sourceHandle: null, targetHandle: null })
          }
        >
          self connect
        </button>
        <button
          onClick={() =>
            onConnect({
              source: "start",
              target: "value-1",
              sourceHandle: null,
              targetHandle: null,
            })
          }
        >
          connect value
        </button>
        {children}
      </div>
    ),
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    MiniMap: () => null,
  };
});

import { WorkflowCanvas } from "./workflow-canvas";

function Harness({ editable = true }: { editable?: boolean }) {
  const [graph, setGraph] = useState(() => toCanvasGraph(createDefaultWorkflowGraph()));
  const [dirty, setDirty] = useState(false);
  const [problem, setProblem] = useState<ConnectionProblem | null>(null);
  return (
    <>
      <p>dirty:{String(dirty)}</p>
      <p>problem:{problem ?? "none"}</p>
      <WorkflowCanvas
        graph={graph}
        editable={editable}
        onChange={(next: CanvasGraph, marksDirty: boolean) => {
          setGraph(next);
          if (marksDirty) setDirty(true);
        }}
        onConnectionRejected={setProblem}
        labels={{ addValue: "Add VALUE", deleteNode: "Delete node", deleteEdge: "Delete edge" }}
      />
    </>
  );
}

describe("WorkflowCanvas interactions", () => {
  it("renders the saved graph and selection alone does not mark it dirty", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByText("nodes:start,end")).toBeInTheDocument();
    expect(screen.getByText("edges:start-to-end")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select node start" }));
    expect(screen.getByText("dirty:false")).toBeInTheDocument();
  });

  it("adds, moves, connects, and removes a VALUE node with its edge", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Add VALUE" }));
    expect(screen.getByText("nodes:start,end,value-1")).toBeInTheDocument();
    expect(screen.getByText("dirty:true")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "move node value-1" }));
    await user.click(screen.getByRole("button", { name: "connect value" }));
    expect(screen.getByText(/edges:start-to-end,start-to-value-1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select node value-1" }));
    await user.click(screen.getByRole("button", { name: "Delete node" }));
    expect(screen.getByText("nodes:start,end")).toBeInTheDocument();
    expect(screen.getByText("edges:start-to-end")).toBeInTheDocument();
  });

  it("retains measured dimensions without marking the graph dirty", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "measure node start" }));
    expect(screen.getByText(/measured:start@180x72/)).toBeInTheDocument();
    expect(screen.getByText("dirty:false")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select node start" }));
    expect(screen.getByText("selected-nodes:start")).toBeInTheDocument();
    expect(screen.getByText(/measured:start@180x72/)).toBeInTheDocument();
    expect(screen.getByText("dirty:false")).toBeInTheDocument();
  });

  it("deletes selected edges and rejects illegal connections", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "select edge start-to-end" }));
    await user.click(screen.getByRole("button", { name: "Delete edge" }));
    expect(screen.getByText("edges:")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "self connect" }));
    expect(screen.getByText("problem:self_loop")).toBeInTheDocument();
  });

  it("does not allow START or the final END to be deleted", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "select node start" }));
    expect(screen.getByRole("button", { name: "Delete node" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "select node end" }));
    expect(screen.getByRole("button", { name: "Delete node" })).toBeDisabled();
  });

  it("allows selection but ignores node and edge mutations while read-only", async () => {
    const user = userEvent.setup();
    render(<Harness editable={false} />);

    await user.click(screen.getByRole("button", { name: "move node start" }));
    await user.click(screen.getByRole("button", { name: "remove node event end" }));
    await user.click(screen.getByRole("button", { name: "remove edge event start-to-end" }));
    await user.click(screen.getByRole("button", { name: "measure node start" }));
    expect(screen.getByText("positions:start@0,end@240")).toBeInTheDocument();
    expect(screen.getByText(/measured:start@180x72/)).toBeInTheDocument();
    expect(screen.getByText("nodes:start,end")).toBeInTheDocument();
    expect(screen.getByText("edges:start-to-end")).toBeInTheDocument();
    expect(screen.getByText("dirty:false")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select node start" }));
    await user.click(screen.getByRole("button", { name: "select edge start-to-end" }));
    expect(screen.getByText("selected-nodes:start")).toBeInTheDocument();
    expect(screen.getByText("selected-edges:start-to-end")).toBeInTheDocument();
    expect(screen.getByText("dirty:false")).toBeInTheDocument();
  });
});
