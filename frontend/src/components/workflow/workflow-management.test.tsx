import { NextIntlClientProvider } from "next-intl";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ApiError } from "@/lib/api-client";
import type { WorkspaceMemberRead, WorkspaceRead, WorkflowRead } from "@/types";

const mocks = vi.hoisted(() => ({
  search: "workspace_id=workspace-1",
  pathname: "/workflows",
  push: vi.fn(),
  replace: vi.fn(),
  useWorkspaces: vi.fn(),
  useWorkspaceMembers: vi.fn(),
  useWorkflows: vi.fn(),
  useWorkspaceMutations: vi.fn(),
  useMemberMutations: vi.fn(),
  useWorkflowMutations: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/hooks", () => ({
  useWorkspaces: mocks.useWorkspaces,
  useWorkspaceMembers: mocks.useWorkspaceMembers,
  useWorkflows: mocks.useWorkflows,
  useWorkspaceMutations: mocks.useWorkspaceMutations,
  useMemberMutations: mocks.useMemberMutations,
  useWorkflowMutations: mocks.useWorkflowMutations,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { WorkflowManagement } from "./workflow-management";

const workspaces: WorkspaceRead[] = [
  {
    id: "workspace-1",
    name: "Primary workspace",
    created_by_user_id: "user-1",
    created_at: "2026-10-28T00:00:00Z",
    updated_at: null,
  },
  {
    id: "workspace-2",
    name: "Secondary workspace",
    created_by_user_id: "user-2",
    created_at: "2026-10-28T00:00:00Z",
    updated_at: null,
  },
];

const workflow: WorkflowRead = {
  id: "workflow-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  name: "Review flow",
  description: "A workflow",
  definition: {
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
  },
  revision: 1,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: null,
};

const owner: WorkspaceMemberRead = {
  workspace_id: "workspace-1",
  user_id: "user-1",
  role: "owner",
  created_at: "2026-10-28T00:00:00Z",
  updated_at: null,
};

function query<T>(data: T) {
  return {
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  };
}

function mutations() {
  return {
    create: { isPending: false, mutateAsync: vi.fn() },
    update: { isPending: false, mutateAsync: vi.fn() },
    remove: { isPending: false, mutateAsync: vi.fn() },
    add: { isPending: false, mutateAsync: vi.fn() },
  };
}

function renderPage() {
  return render(
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <WorkflowManagement userId="user-1" />
    </NextIntlClientProvider>,
  );
}

describe("WorkflowManagement", () => {
  beforeAll(() => {
    Object.defineProperties(HTMLElement.prototype, {
      hasPointerCapture: { configurable: true, value: () => false },
      setPointerCapture: { configurable: true, value: () => undefined },
      releasePointerCapture: { configurable: true, value: () => undefined },
      scrollIntoView: { configurable: true, value: () => undefined },
    });
  });

  beforeEach(() => {
    mocks.search = "workspace_id=workspace-1";
    mocks.pathname = "/workflows";
    mocks.push.mockReset();
    mocks.replace.mockReset();
    mocks.useWorkspaces.mockReturnValue(query(workspaces));
    mocks.useWorkspaceMembers.mockReturnValue(query([owner]));
    mocks.useWorkflows.mockReturnValue(query({ items: [workflow], total: 1 }));
    mocks.useWorkspaceMutations.mockReturnValue(mutations());
    mocks.useMemberMutations.mockReturnValue(mutations());
    mocks.useWorkflowMutations.mockReturnValue(mutations());
  });

  it("shows the no-workspace state and creation entry", () => {
    mocks.search = "";
    mocks.useWorkspaces.mockReturnValue(query([]));
    renderPage();
    expect(screen.getByText("No workspaces yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Create workspace" }).length).toBeGreaterThan(0);
  });

  it("creates a workspace from the empty state", async () => {
    const workspaceMutations = mutations();
    workspaceMutations.create.mutateAsync.mockResolvedValue(workspaces[0]);
    mocks.search = "";
    mocks.useWorkspaces.mockReturnValue(query([]));
    mocks.useWorkspaceMutations.mockReturnValue(workspaceMutations);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getAllByRole("button", { name: "Create workspace" })[0]!);
    await user.type(await screen.findByLabelText(/^Name/), "Research workspace");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(workspaceMutations.create.mutateAsync).toHaveBeenCalledWith({
        name: "Research workspace",
      }),
    );
  });

  it("recovers an invalid workspace selection through the URL", async () => {
    mocks.search = "workspace_id=missing";
    renderPage();
    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith("/workflows?workspace_id=workspace-1");
    });
    expect(screen.queryByText("Review flow")).not.toBeInTheDocument();
  });

  it("switches workspaces using the URL query parameter", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("combobox", { name: "Workspace" }));
    await user.click(await screen.findByRole("option", { name: "Secondary workspace" }));
    expect(mocks.push).toHaveBeenCalledWith("/workflows?workspace_id=workspace-2");
  });

  it("shows owner management controls and protects the owner membership", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add member/i })).toBeInTheDocument();
    expect(screen.getByText("Owner membership is protected.")).toBeInTheDocument();
  });

  it("requires the workspace name before deleting a workspace", async () => {
    const workspaceMutations = mutations();
    workspaceMutations.remove.mutateAsync.mockResolvedValue(undefined);
    mocks.useWorkspaceMutations.mockReturnValue(workspaceMutations);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).toBeDisabled();
    await user.type(
      screen.getByLabelText(/Type Primary workspace to confirm/),
      "Primary workspace",
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(workspaceMutations.remove.mutateAsync).toHaveBeenCalledWith("workspace-1"),
    );
  });

  it("hides destructive and member-management controls from members", () => {
    mocks.useWorkspaceMembers.mockReturnValue(query([{ ...owner, role: "member" }]));
    renderPage();
    expect(screen.queryByRole("button", { name: "Delete workspace" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add member/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete workflow" })).not.toBeInTheDocument();
    expect(screen.getByText(/Members can create and edit workflows/)).toBeInTheDocument();
  });

  it("creates a workflow with the legal START to END graph", async () => {
    const workflowMutations = mutations();
    workflowMutations.create.mutateAsync.mockResolvedValue(workflow);
    mocks.useWorkflowMutations.mockReturnValue(workflowMutations);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Create workflow" }));
    await user.type(await screen.findByLabelText(/^Name/), "New flow");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(workflowMutations.create.mutateAsync).toHaveBeenCalled());
    expect(workflowMutations.create.mutateAsync.mock.calls[0]?.[0]).toMatchObject({
      name: "New flow",
      definition: {
        entry_node_id: "start",
        nodes: [{ kind: "start" }, { kind: "end" }],
        edges: [{ source: "start", target: "end", condition: null }],
      },
    });
  });

  it("updates a workflow and opens its delete confirmation", async () => {
    const workflowMutations = mutations();
    workflowMutations.update.mutateAsync.mockResolvedValue({ ...workflow, name: "Updated flow" });
    mocks.useWorkflowMutations.mockReturnValue(workflowMutations);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Edit workflow" }));
    expect(screen.getByRole("dialog", { name: "Edit workflow" })).toBeInTheDocument();
    const name = screen.getByLabelText(/^Name/);
    await user.clear(name);
    await user.type(name, "Updated flow");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(workflowMutations.update.mutateAsync).toHaveBeenCalledWith({
        workflowId: "workflow-1",
        payload: { name: "Updated flow", description: "A workflow" },
      }),
    );
    await user.click(screen.getByRole("button", { name: "Delete workflow" }));
    expect(screen.getByRole("dialog", { name: "Delete workflow" })).toBeInTheDocument();
    expect(screen.getByText(/Delete Review flow/)).toBeInTheDocument();
  });

  it("requests the next isolated page", async () => {
    mocks.useWorkflows.mockReturnValue(query({ items: [workflow], total: 11 }));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(mocks.useWorkflows).toHaveBeenLastCalledWith("user-1", "workspace-1", 10, 10);
  });

  it.each([
    [403, "You do not have permission"],
    [404, "no longer exists"],
    [422, "Invalid workflow name"],
  ])("shows actionable HTTP %i feedback", (status, message) => {
    const data = status === 422 ? { detail: "Invalid workflow name" } : { detail: "failed" };
    mocks.useWorkflows.mockReturnValue({
      ...query(undefined),
      isError: true,
      isSuccess: false,
      error: new ApiError(status, "failed", data),
    });
    renderPage();
    expect(screen.getByText(new RegExp(message))).toBeInTheDocument();
  });
});
