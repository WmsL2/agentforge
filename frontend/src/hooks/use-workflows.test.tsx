import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";
import { workflowApi } from "@/lib/workflow/workflow-api";
import type { WorkflowList, WorkflowRead } from "@/types";

import { useWorkflowMutations } from "./use-workflows";

vi.mock("@/lib/workflow/workflow-api", () => ({
  workflowApi: {
    createWorkflow: vi.fn(),
    updateWorkflow: vi.fn(),
    deleteWorkflow: vi.fn(),
    listWorkflows: vi.fn(),
    getWorkflow: vi.fn(),
  },
}));

const workflow = {
  id: "flow-2",
  workspace_id: "workspace-1",
  user_id: "user-1",
  name: "Created flow",
  description: null,
  definition: { entry_node_id: "start", nodes: [], edges: [], schema_version: 1, metadata: {} },
  revision: 1,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: null,
} satisfies WorkflowRead;

describe("workflow query cache", () => {
  let queryClient: QueryClient;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(workflowApi.createWorkflow).mockReset();
  });

  it("isolates users, workspaces, and pagination in query keys", () => {
    expect(qk.workflows.list("user-a", "workspace-a", 0, 10)).not.toEqual(
      qk.workflows.list("user-b", "workspace-a", 0, 10),
    );
    expect(qk.workflows.list("user-a", "workspace-a", 0, 10)).not.toEqual(
      qk.workflows.list("user-a", "workspace-b", 0, 10),
    );
    expect(qk.workflows.list("user-a", "workspace-a", 0, 10)).not.toEqual(
      qk.workflows.list("user-a", "workspace-a", 10, 10),
    );
  });

  it("invalidates only the matching workspace without inserting into a full page", async () => {
    const firstPageKey = qk.workflows.list("user-1", "workspace-1", 0, 10);
    const secondPageKey = qk.workflows.list("user-1", "workspace-1", 10, 10);
    const otherWorkspaceKey = qk.workflows.list("user-1", "workspace-2", 0, 10);
    const otherUserKey = qk.workflows.list("user-2", "workspace-1", 0, 10);
    const fullPage = {
      items: Array.from({ length: 10 }, (_, index) => ({
        ...workflow,
        id: `flow-${index}`,
      })),
      total: 20,
    } satisfies WorkflowList;
    queryClient.setQueryData(firstPageKey, fullPage);
    queryClient.setQueryData(secondPageKey, fullPage);
    queryClient.setQueryData(otherWorkspaceKey, fullPage);
    queryClient.setQueryData(otherUserKey, fullPage);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    vi.mocked(workflowApi.createWorkflow).mockResolvedValue(workflow);
    const { result } = renderHook(() => useWorkflowMutations("user-1", "workspace-1"), {
      wrapper,
    });

    await act(async () => {
      await result.current.create.mutateAsync({
        name: "Created flow",
        definition: workflow.definition,
      });
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: qk.workflows.workspace("user-1", "workspace-1"),
    });
    expect(queryClient.getQueryData<WorkflowList>(firstPageKey)?.items).toHaveLength(10);
    expect(queryClient.getQueryData<WorkflowList>(secondPageKey)?.items).toHaveLength(10);
    expect(queryClient.getQueryData<WorkflowList>(otherWorkspaceKey)).toEqual(fullPage);
    expect(queryClient.getQueryData<WorkflowList>(otherUserKey)).toEqual(fullPage);
  });

  it("does not invalidate or alter pagination when creation fails", async () => {
    const key = qk.workflows.list("user-1", "workspace-1", 10, 10);
    const cached = { items: [workflow], total: 11 } satisfies WorkflowList;
    queryClient.setQueryData(key, cached);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    vi.mocked(workflowApi.createWorkflow).mockRejectedValue(new Error("create failed"));
    const { result } = renderHook(() => useWorkflowMutations("user-1", "workspace-1"), {
      wrapper,
    });

    await expect(
      result.current.create.mutateAsync({
        name: "Created flow",
        definition: workflow.definition,
      }),
    ).rejects.toThrow("create failed");

    expect(invalidate).not.toHaveBeenCalled();
    expect(queryClient.getQueryData<WorkflowList>(key)).toEqual(cached);
  });
});
