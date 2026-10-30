import { NextIntlClientProvider } from "next-intl";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ApiError } from "@/lib/api-client";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type { WorkflowRead, WorkflowValidationRead, WorkspaceRole } from "@/types";
import type { WorkflowCanvasProps } from "./workflow-canvas";

const mocks = vi.hoisted(() => ({
  useWorkspaceMembers: vi.fn(),
  useWorkflowMutations: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useWorkspaceMembers: mocks.useWorkspaceMembers,
  useWorkflowMutations: mocks.useWorkflowMutations,
}));

function FakeWorkflowCanvas({ graph, editable, onChange }: WorkflowCanvasProps) {
  return (
    <div>
      <p>editable:{String(editable)}</p>
      <p>canvas:{graph.nodes.map((node) => `${node.id}@${node.position.x}`).join(",")}</p>
      <p>
        measured:
        {graph.nodes
          .map(
            (node) =>
              `${node.id}@${node.measured?.width ?? "unset"}x${node.measured?.height ?? "unset"}`,
          )
          .join(",")}
      </p>
      <p>
        selected:
        {graph.nodes
          .filter((node) => node.selected)
          .map((node) => node.id)
          .join(",")}
      </p>
      <p>config:{String(graph.nodes[0]?.data.config.spoofed ?? "clean")}</p>
      <p>metadata:{String(graph.nodes[0]?.data.metadata.spoofed ?? "clean")}</p>
      <p>
        structure:{graph.nodes.length} nodes/{graph.edges.length} edges
      </p>
      <button
        disabled={!editable}
        onClick={() =>
          onChange(
            {
              ...graph,
              nodes: graph.nodes.map((node, index) =>
                index === 0 ? { ...node, position: { x: 999, y: 50 } } : node,
              ),
            },
            true,
          )
        }
      >
        edit graph
      </button>
      <button
        onClick={() =>
          onChange(
            {
              ...graph,
              nodes: graph.nodes.map((node, index) =>
                index === 0 ? { ...node, position: { x: 777, y: 75 } } : node,
              ),
            },
            true,
          )
        }
      >
        force business change
      </button>
      <button
        onClick={() =>
          onChange(
            {
              ...graph,
              nodes: graph.nodes.map((node, index) =>
                index === 0 ? { ...node, measured: { width: 160, height: 80 } } : node,
              ),
            },
            false,
          )
        }
      >
        measure node
      </button>
      <button
        onClick={() =>
          onChange(
            {
              nodes: [
                ...graph.nodes.map((node, index) =>
                  index === 0
                    ? {
                        ...node,
                        position: { x: 444, y: 555 },
                        data: {
                          ...node.data,
                          config: { ...node.data.config, spoofed: true },
                          metadata: { ...node.data.metadata, spoofed: true },
                        },
                      }
                    : node,
                ),
                { ...graph.nodes[0]!, id: "spoofed-node" },
              ],
              edges: [],
            },
            false,
          )
        }
      >
        spoof non-dirty business change
      </button>
      <button
        onClick={() =>
          onChange(
            {
              ...graph,
              nodes: graph.nodes.map((node, index) =>
                index === 0 ? { ...node, selected: true } : node,
              ),
            },
            false,
          )
        }
      >
        select only
      </button>
    </div>
  );
}

import { WorkflowCanvasEditor } from "./workflow-canvas-editor";

const workflow: WorkflowRead = {
  id: "workflow-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "Canvas flow",
  description: null,
  definition: createDefaultWorkflowGraph(),
  revision: 1,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: null,
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function members(role: WorkspaceRole | null = "owner") {
  return {
    data: role
      ? [
          {
            workspace_id: "workspace-1",
            user_id: "user-1",
            role,
            created_at: "2026-10-28T00:00:00Z",
            updated_at: null,
          },
        ]
      : [],
    isLoading: false,
    isSuccess: true,
    isError: false,
  };
}

function mutation() {
  return {
    create: { mutateAsync: vi.fn(), isPending: false },
    update: { mutateAsync: vi.fn(), isPending: false },
    remove: { mutateAsync: vi.fn(), isPending: false },
  };
}

function renderEditor(props: Partial<React.ComponentProps<typeof WorkflowCanvasEditor>> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <WorkflowCanvasEditor
        workflow={workflow}
        userId="user-1"
        CanvasComponent={FakeWorkflowCanvas}
        {...props}
      />
    </NextIntlClientProvider>,
  );
}

describe("WorkflowCanvasEditor lifecycle", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mocks.useWorkspaceMembers.mockReturnValue(members());
    mocks.useWorkflowMutations.mockReturnValue(mutation());
  });

  it.each(["owner", "admin", "member"] as const)("allows a %s member to edit", async (role) => {
    mocks.useWorkspaceMembers.mockReturnValue(members(role));
    const user = userEvent.setup();
    renderEditor();

    expect(screen.getByText("editable:true")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "edit graph" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save graph" })).toBeEnabled();
  });

  it("stays read-only for a non-member or failed permission request", () => {
    mocks.useWorkspaceMembers.mockReturnValue(members(null));
    const view = renderEditor();
    expect(screen.getByText("editable:false")).toBeInTheDocument();
    expect(screen.getByText(/not a workspace member/i)).toBeInTheDocument();

    mocks.useWorkspaceMembers.mockReturnValue({
      data: undefined,
      isLoading: false,
      isSuccess: false,
      isError: true,
    });
    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={workflow}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
        />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText(/permission could not be verified/i)).toBeInTheDocument();
    expect(screen.getByText("editable:false")).toBeInTheDocument();
  });

  it("validates before save, adopts the returned revision, and clears dirty state", async () => {
    const mutations = mutation();
    const updated = { ...workflow, revision: 2 };
    mutations.update.mutateAsync.mockResolvedValue(updated);
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    vi.spyOn(workflowApi, "validateWorkflow").mockResolvedValue({ is_valid: true, issues: [] });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderEditor({ onSaved });

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));

    await waitFor(() => expect(mutations.update.mutateAsync).toHaveBeenCalledOnce());
    expect(mutations.update.mutateAsync.mock.calls[0]?.[0]).toMatchObject({
      workflowId: "workflow-1",
      payload: { definition: { entry_node_id: "start", schema_version: 1 } },
    });
    expect(onSaved).toHaveBeenCalledWith(updated);
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("locks editing and prevents duplicate requests while validation is pending", async () => {
    const pending = deferred<{ is_valid: boolean; issues: [] }>();
    const validate = vi.spyOn(workflowApi, "validateWorkflow").mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    const validateButton = screen.getByRole("button", { name: "Validate" });
    fireEvent.click(validateButton);
    fireEvent.click(validateButton);

    expect(validate).toHaveBeenCalledOnce();
    expect(screen.getByText("editable:false")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();

    await act(async () => pending.resolve({ is_valid: true, issues: [] }));
    expect(await screen.findByText("editable:true")).toBeInTheDocument();
  });

  it("validates and patches the same snapshot while rejecting pending edits", async () => {
    const validation = deferred<{ is_valid: boolean; issues: [] }>();
    const validate = vi.spyOn(workflowApi, "validateWorkflow").mockReturnValue(validation.promise);
    const mutations = mutation();
    mutations.update.mutateAsync.mockImplementation(async ({ payload }) => ({
      ...workflow,
      revision: 2,
      definition: payload.definition,
    }));
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));
    expect(screen.getByText("editable:false")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "force business change" }));
    expect(screen.getByText(/start@999/)).toBeInTheDocument();

    await act(async () => validation.resolve({ is_valid: true, issues: [] }));
    await waitFor(() => expect(mutations.update.mutateAsync).toHaveBeenCalledOnce());
    const validatedGraph = validate.mock.calls[0]?.[0];
    const patchedGraph = mutations.update.mutateAsync.mock.calls[0]?.[0].payload.definition;
    expect(patchedGraph).toEqual(validatedGraph);
    expect(patchedGraph.nodes[0]?.metadata.agentforge_canvas).toEqual({
      position: { x: 999, y: 50 },
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("keeps destructive actions locked and prevents duplicate PATCH while PATCH is pending", async () => {
    const patch = deferred<WorkflowRead>();
    const mutations = mutation();
    mutations.update.mutateAsync.mockReturnValue(patch.promise);
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    vi.spyOn(workflowApi, "validateWorkflow").mockResolvedValue({ is_valid: true, issues: [] });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    const view = renderEditor({ onSaved });

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));
    await waitFor(() => expect(mutations.update.mutateAsync).toHaveBeenCalledOnce());
    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={{ ...workflow, revision: 2 }}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
          onSaved={onSaved}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("editable:false")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload server version" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Saving…" }));
    expect(mutations.update.mutateAsync).toHaveBeenCalledOnce();

    const updated = { ...workflow, revision: 3 };
    await act(async () => patch.resolve(updated));
    expect(onSaved).toHaveBeenCalledWith(updated);
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("shows validator issues and blocks PATCH", async () => {
    const mutations = mutation();
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    vi.spyOn(workflowApi, "validateWorkflow").mockResolvedValue({
      is_valid: false,
      issues: [
        { code: "cycle_detected", message: "Cycle detected", node_id: "start", edge_id: null },
      ],
    });
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));

    expect(await screen.findByText(/Cycle detected \[node: start\]/)).toBeInTheDocument();
    expect(mutations.update.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByText("editable:true")).toBeInTheDocument();
  });

  it("distinguishes validation service failures and blocks PATCH", async () => {
    const mutations = mutation();
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    vi.spyOn(workflowApi, "validateWorkflow").mockRejectedValue(new Error("network unavailable"));
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));

    expect(await screen.findByText("network unavailable")).toBeInTheDocument();
    expect(mutations.update.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByText("editable:true")).toBeInTheDocument();
  });

  it.each([
    [403, "Forbidden"],
    [404, "Workflow not found"],
  ])("keeps edits after a %s PATCH error", async (status, message) => {
    const mutations = mutation();
    mutations.update.mutateAsync.mockRejectedValue(new ApiError(status, message));
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    vi.spyOn(workflowApi, "validateWorkflow").mockResolvedValue({ is_valid: true, issues: [] });
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByText(/start@999/)).toBeInTheDocument();
    expect(screen.getByText("editable:true")).toBeInTheDocument();
  });

  it("does not dirty on selection and discards back to the last saved graph", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "select only" }));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "edit graph" }));
    expect(screen.getByText(/start@999/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByText(/start@0/)).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("keeps measured dimensions and selection while rejecting non-dirty business changes", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: "measure node" }));
    expect(screen.getByText(/measured:start@160x80/)).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select only" }));
    expect(screen.getByText("selected:start")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "spoof non-dirty business change" }));
    expect(screen.getByText(/canvas:start@0,end@240/)).toBeInTheDocument();
    expect(screen.getByText("config:clean")).toBeInTheDocument();
    expect(screen.getByText("metadata:clean")).toBeInTheDocument();
    expect(screen.getByText("structure:2 nodes/1 edges")).toBeInTheDocument();
    expect(screen.getByText(/measured:start@160x80/)).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("resets local canvas state when the workflow changes", async () => {
    const user = userEvent.setup();
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "edit graph" }));
    expect(screen.getByText(/start@999/)).toBeInTheDocument();
    const next = {
      ...workflow,
      id: "workflow-2",
      definition: {
        ...createDefaultWorkflowGraph(),
        nodes: [
          { id: "other-start", kind: "start" as const, config: {}, metadata: {} },
          { id: "other-end", kind: "end" as const, config: {}, metadata: {} },
        ],
        edges: [],
        entry_node_id: "other-start",
      },
    };
    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={next}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
        />
      </NextIntlClientProvider>,
    );

    expect(await screen.findByText(/canvas:other-start@0,other-end@240/)).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("does not silently overwrite unsaved edits when a newer revision arrives", async () => {
    const user = userEvent.setup();
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "edit graph" }));

    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={{ ...workflow, revision: 2 }}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
        />
      </NextIntlClientProvider>,
    );

    expect(await screen.findByText(/Revision 2 is available/)).toBeInTheDocument();
    expect(screen.getByText(/start@999/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Reload server version" }));
    expect(screen.getByText(/start@0/)).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("ignores an old validation result after switching workflows", async () => {
    const validation = deferred<{ is_valid: boolean; issues: WorkflowValidationRead["issues"] }>();
    vi.spyOn(workflowApi, "validateWorkflow").mockReturnValue(validation.promise);
    const user = userEvent.setup();
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const next = {
      ...workflow,
      id: "workflow-2",
      definition: {
        ...createDefaultWorkflowGraph(),
        nodes: [
          { id: "new-start", kind: "start" as const, config: {}, metadata: {} },
          { id: "new-end", kind: "end" as const, config: {}, metadata: {} },
        ],
        edges: [],
        entry_node_id: "new-start",
      },
    };
    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={next}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
        />
      </NextIntlClientProvider>,
    );

    await act(async () =>
      validation.resolve({
        is_valid: false,
        issues: [
          {
            code: "cycle_detected",
            message: "Old validation",
            node_id: "start",
            edge_id: null,
          },
        ],
      }),
    );
    expect(screen.getByText(/canvas:new-start@0,new-end@240/)).toBeInTheDocument();
    expect(screen.queryByText(/Old validation/)).not.toBeInTheDocument();
  });

  it("aborts PATCH when a newer revision arrives during validation", async () => {
    const validation = deferred<{ is_valid: boolean; issues: [] }>();
    vi.spyOn(workflowApi, "validateWorkflow").mockReturnValue(validation.promise);
    const mutations = mutation();
    mocks.useWorkflowMutations.mockReturnValue(mutations);
    const user = userEvent.setup();
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "edit graph" }));
    await user.click(screen.getByRole("button", { name: "Save graph" }));
    view.rerender(
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <WorkflowCanvasEditor
          workflow={{ ...workflow, revision: 2 }}
          userId="user-1"
          CanvasComponent={FakeWorkflowCanvas}
        />
      </NextIntlClientProvider>,
    );

    await act(async () => validation.resolve({ is_valid: true, issues: [] }));
    expect(mutations.update.mutateAsync).not.toHaveBeenCalled();
    expect(await screen.findByText(/Revision 2 is available/)).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("does not write stale state after unmount", async () => {
    const validation = deferred<{ is_valid: boolean; issues: [] }>();
    vi.spyOn(workflowApi, "validateWorkflow").mockReturnValue(validation.promise);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const user = userEvent.setup();
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    view.unmount();

    await act(async () => validation.resolve({ is_valid: true, issues: [] }));
    expect(error).not.toHaveBeenCalled();
  });
});
