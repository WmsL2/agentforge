import { beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { getStructuredErrorIssues, type WorkflowList, type WorkflowRunRead } from "@/types";

import { workflowApi } from "./workflow-api";
import { workspaceApi } from "./workspace-api";

describe("typed platform API facades", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("builds workspace and membership requests", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue([]);
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({});
    await workspaceApi.listMembers("workspace/1");
    await workspaceApi.updateMember("workspace/1", "user/2", { role: "admin" });
    expect(get).toHaveBeenCalledWith("/workspaces/workspace%2F1/members");
    expect(patch).toHaveBeenCalledWith("/workspaces/workspace%2F1/members/user%2F2", {
      role: "admin",
    });
  });

  it("passes workflow workspace and pagination through query parameters", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ items: [], total: 0 });
    const result = workflowApi.listWorkflows("workspace-1", { skip: 5, limit: 20 });
    expectTypeOf(result).toEqualTypeOf<Promise<WorkflowList>>();
    await result;
    expect(get).toHaveBeenCalledWith("/workflows", {
      params: { workspace_id: "workspace-1", skip: "5", limit: "20" },
    });
  });

  it("wraps async run input and builds approval paths", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({});
    const run = workflowApi.submitAsyncRun("workflow/1", { prompt: "hello" });
    expectTypeOf(run).toEqualTypeOf<Promise<WorkflowRunRead>>();
    await run;
    await workflowApi.approveAsync("workflow/1", "run/2", "approval/3");
    await workflowApi.rejectApproval("workflow/1", "run/2", "approval/3", { note: null });
    expect(post.mock.calls).toEqual([
      ["/workflows/workflow%2F1/runs/async", { input: { prompt: "hello" } }],
      ["/workflows/workflow%2F1/runs/run%2F2/approvals/approval%2F3/approve/async", {}],
      ["/workflows/workflow%2F1/runs/run%2F2/approvals/approval%2F3/reject", { note: null }],
    ]);
  });

  it("narrows structured workflow issues without guessing other error shapes", () => {
    const issues = [{ code: "missing_start_node" }];
    expect(
      getStructuredErrorIssues({
        error: { code: "INVALID", message: "Invalid", details: { issues } },
      }),
    ).toEqual(issues);
    expect(getStructuredErrorIssues({ detail: "Invalid" })).toBeNull();
  });
});
