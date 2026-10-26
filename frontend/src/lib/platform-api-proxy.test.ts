import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server-api", () => {
  class BackendApiError extends Error {
    constructor(
      public status: number,
      public statusText: string,
      public data?: unknown,
    ) {
      super(`Backend API error: ${status} ${statusText}`);
    }
  }
  return { backendFetch: vi.fn(), BackendApiError };
});

import {
  DELETE as deleteWorkspace,
  GET as getWorkspace,
  PATCH as patchWorkspace,
} from "@/app/api/workspaces/[workspaceId]/route";
import {
  GET as listMembers,
  POST as addMember,
} from "@/app/api/workspaces/[workspaceId]/members/route";
import {
  DELETE as removeMember,
  PATCH as updateMember,
} from "@/app/api/workspaces/[workspaceId]/members/[userId]/route";
import { GET as listWorkspaces, POST as createWorkspace } from "@/app/api/workspaces/route";
import {
  DELETE as deleteWorkflow,
  GET as getWorkflow,
  PATCH as patchWorkflow,
} from "@/app/api/workflows/[workflowId]/route";
import { GET as getRun } from "@/app/api/workflows/[workflowId]/runs/[runId]/route";
import { GET as getSteps } from "@/app/api/workflows/[workflowId]/runs/[runId]/steps/route";
import { GET as getTrace } from "@/app/api/workflows/[workflowId]/runs/[runId]/trace/route";
import { GET as getPendingApproval } from "@/app/api/workflows/[workflowId]/runs/[runId]/approvals/pending/route";
import { POST as approveAsync } from "@/app/api/workflows/[workflowId]/runs/[runId]/approvals/[approvalId]/approve/async/route";
import { POST as rejectApproval } from "@/app/api/workflows/[workflowId]/runs/[runId]/approvals/[approvalId]/reject/route";
import { POST as submitAsyncRun } from "@/app/api/workflows/[workflowId]/runs/async/route";
import { GET as listRuns } from "@/app/api/workflows/[workflowId]/runs/route";
import { GET as listWorkflows, POST as createWorkflow } from "@/app/api/workflows/route";
import { POST as validateWorkflow } from "@/app/api/workflows/validate/route";
import { backendFetch, BackendApiError } from "@/lib/server-api";

const backendMock = vi.mocked(backendFetch);
const workspaceParams = { params: Promise.resolve({ workspaceId: "workspace/one" }) };
const memberParams = {
  params: Promise.resolve({ workspaceId: "workspace/one", userId: "user/two" }),
};
const workflowParams = { params: Promise.resolve({ workflowId: "workflow/one" }) };
const runParams = {
  params: Promise.resolve({ workflowId: "workflow/one", runId: "run/two" }),
};
const approvalParams = {
  params: Promise.resolve({
    workflowId: "workflow/one",
    runId: "run/two",
    approvalId: "approval/three",
  }),
};

function request(
  method = "GET",
  path = "/api/workspaces",
  options: { cookie?: boolean; headers?: Record<string, string>; body?: unknown } = {},
) {
  const headers = new Headers(options.headers);
  if (options.cookie !== false) headers.set("cookie", "access_token=cookie-token");
  if (options.body !== undefined) headers.set("content-type", "application/json");
  return new NextRequest(`https://app.example.test${path}`, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

beforeEach(() => {
  backendMock.mockReset();
  backendMock.mockResolvedValue({ ok: true });
});

describe("platform API routes", () => {
  it("returns 401 without a cookie and never calls the backend", async () => {
    const response = await listWorkspaces(request("GET", "/api/workspaces", { cookie: false }));
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(backendMock).not.toHaveBeenCalled();
  });

  it("uses only the cookie token for backend authorization", async () => {
    await listWorkspaces(
      request("GET", "/api/workspaces", {
        headers: { authorization: "Bearer attacker-token" },
      }),
    );
    expect(backendMock).toHaveBeenCalledWith(
      "/api/v1/workspaces",
      expect.objectContaining({ headers: { Authorization: "Bearer cookie-token" } }),
    );
  });

  it.each([
    ["origin", { origin: "https://evil.example" }],
    ["fetch metadata", { "sec-fetch-site": "cross-site" }],
  ])("rejects cross-site mutations indicated by %s", async (_label, headers) => {
    const response = await createWorkspace(
      request("POST", "/api/workspaces", { headers, body: { name: "A" } }),
    );
    expect(response.status).toBe(403);
    expect(backendMock).not.toHaveBeenCalled();
  });

  it("allows a same-origin mutation", async () => {
    const response = await createWorkspace(
      request("POST", "/api/workspaces", {
        headers: { origin: "https://app.example.test" },
        body: { name: "A" },
      }),
    );
    expect(response.status).toBe(201);
  });

  it("maps workspace CRUD routes, methods, and empty deletes", async () => {
    await createWorkspace(request("POST", "/api/workspaces", { body: { name: "A" } }));
    await getWorkspace(request(), workspaceParams);
    await patchWorkspace(request("PATCH", "/", { body: { name: "B" } }), workspaceParams);
    backendMock.mockResolvedValueOnce(null);
    const deleted = await deleteWorkspace(request("DELETE"), workspaceParams);

    expect(backendMock.mock.calls.map(([path, options]) => [path, options?.method])).toEqual([
      ["/api/v1/workspaces", "POST"],
      ["/api/v1/workspaces/workspace%2Fone", "GET"],
      ["/api/v1/workspaces/workspace%2Fone", "PATCH"],
      ["/api/v1/workspaces/workspace%2Fone", "DELETE"],
    ]);
    expect(deleted.status).toBe(204);
    expect(await deleted.text()).toBe("");
  });

  it("maps membership routes and methods", async () => {
    await listMembers(request(), workspaceParams);
    await addMember(request("POST", "/", { body: { user_id: "u" } }), workspaceParams);
    await updateMember(request("PATCH", "/", { body: { role: "admin" } }), memberParams);
    await removeMember(request("DELETE"), memberParams);
    expect(backendMock.mock.calls.map(([path, options]) => [path, options?.method])).toEqual([
      ["/api/v1/workspaces/workspace%2Fone/members", "GET"],
      ["/api/v1/workspaces/workspace%2Fone/members", "POST"],
      ["/api/v1/workspaces/workspace%2Fone/members/user%2Ftwo", "PATCH"],
      ["/api/v1/workspaces/workspace%2Fone/members/user%2Ftwo", "DELETE"],
    ]);
  });

  it("forwards only supported workflow list query parameters", async () => {
    await listWorkflows(
      request(
        "GET",
        "/api/workflows?workspace_id=w&skip=2&limit=10&backend_url=https://evil.example",
      ),
    );
    expect(backendMock).toHaveBeenCalledWith(
      "/api/v1/workflows",
      expect.objectContaining({ params: { workspace_id: "w", skip: "2", limit: "10" } }),
    );
  });

  it("maps workflow CRUD and returns create/delete status contracts", async () => {
    const created = await createWorkflow(
      request("POST", "/api/workflows?workspace_id=w", { body: { name: "Flow" } }),
    );
    await getWorkflow(request(), workflowParams);
    await patchWorkflow(request("PATCH", "/", { body: { name: "Flow 2" } }), workflowParams);
    const deleted = await deleteWorkflow(request("DELETE"), workflowParams);
    expect(created.status).toBe(201);
    expect(deleted.status).toBe(204);
    expect(backendMock.mock.calls.map(([path, options]) => [path, options?.method])).toEqual([
      ["/api/v1/workflows", "POST"],
      ["/api/v1/workflows/workflow%2Fone", "GET"],
      ["/api/v1/workflows/workflow%2Fone", "PATCH"],
      ["/api/v1/workflows/workflow%2Fone", "DELETE"],
    ]);
  });

  it("keeps validation on its static route and returns invalid graphs as HTTP 200", async () => {
    backendMock.mockResolvedValue({ is_valid: false, issues: [{ code: "empty_workflow" }] });
    const response = await validateWorkflow(
      request("POST", "/api/workflows/validate", { body: { nodes: [] } }),
    );
    expect(backendMock).toHaveBeenCalledWith(
      "/api/v1/workflows/validate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ is_valid: false });
  });

  it("maps run list, detail, steps, and trace routes", async () => {
    await listRuns(request("GET", "/api/x?skip=1&limit=5"), workflowParams);
    await getRun(request(), runParams);
    await getSteps(request(), runParams);
    await getTrace(request(), runParams);
    expect(backendMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/workflows/workflow%2Fone/runs",
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo",
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo/steps",
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo/trace",
    ]);
    expect(backendMock.mock.calls[0]?.[1]?.params).toEqual({ skip: "1", limit: "5" });
  });

  it("returns async submission as 202 with a frontend run Location", async () => {
    backendMock.mockResolvedValue({ id: "run/created" });
    const response = await submitAsyncRun(
      request("POST", "/", { body: { input: { value: 1 } } }),
      workflowParams,
    );
    expect(response.status).toBe(202);
    expect(response.headers.get("location")).toBe(
      "/api/workflows/workflow%2Fone/runs/run%2Fcreated",
    );
    expect(backendMock).toHaveBeenCalledWith(
      "/api/v1/workflows/workflow%2Fone/runs/async",
      expect.objectContaining({ body: JSON.stringify({ input: { value: 1 } }) }),
    );
  });

  it("maps pending approval, async approval, and rejection", async () => {
    await getPendingApproval(request(), runParams);
    const approved = await approveAsync(request("POST", "/", { body: {} }), approvalParams);
    await rejectApproval(request("POST", "/", { body: { note: null } }), approvalParams);
    expect(approved.status).toBe(202);
    expect(approved.headers.get("location")).toBe("/api/workflows/workflow%2Fone/runs/run%2Ftwo");
    expect(backendMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo/approvals/pending",
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo/approvals/approval%2Fthree/approve/async",
      "/api/v1/workflows/workflow%2Fone/runs/run%2Ftwo/approvals/approval%2Fthree/reject",
    ]);
  });

  it.each([400, 401, 403, 404, 409, 422, 503])(
    "preserves backend status %i and structured errors",
    async (status) => {
      const data = {
        error: {
          code: status === 503 ? "WORKFLOW_DISPATCH_FAILED" : "WORKFLOW_ERROR",
          message: "failed",
          details: { issues: [{ code: "bad_graph" }], run_id: "run-1" },
        },
      };
      backendMock.mockRejectedValue(new BackendApiError(status, "Error", data));
      const response = await listWorkspaces(request());
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual(data);
    },
  );

  it("preserves Pydantic detail arrays", async () => {
    const data = { detail: [{ type: "missing", loc: ["body", "name"], msg: "Required" }] };
    backendMock.mockRejectedValue(new BackendApiError(422, "Unprocessable Entity", data));
    const response = await createWorkspace(request("POST", "/", { body: {} }));
    expect(await response.json()).toEqual(data);
  });

  it("returns a safe gateway error for network failures", async () => {
    backendMock.mockRejectedValue(new Error("connect ECONNREFUSED http://secret:8000"));
    const response = await listWorkspaces(request());
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain("secret");
  });
});
