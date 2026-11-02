import { expect, test, type Page, type Route } from "@playwright/test";

test.use({ storageState: ".playwright/.auth/user.json" });

const USER = {
  id: "e2e-user",
  email: "workflow-e2e@example.com",
  full_name: "Workflow E2E",
  is_active: true,
  role: "user",
  created_at: "2026-11-01T00:00:00Z",
  onboarding_completed_at: "2026-11-01T00:00:00Z",
  access_token: "controlled-browser-token",
};

const WORKSPACE = {
  id: "workspace-1",
  name: "Workflow browser workspace",
  description: null,
  owner_id: USER.id,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: null,
};

const graph = {
  entry_node_id: "start",
  nodes: [
    { id: "start", kind: "start", config: {}, metadata: { position: { x: 0, y: 0 } } },
    {
      id: "value-1",
      kind: "value",
      config: { value: "saved" },
      metadata: { position: { x: 220, y: 0 } },
    },
    { id: "end", kind: "end", config: {}, metadata: { position: { x: 440, y: 0 } } },
  ],
  edges: [
    { id: "start-value", source: "start", target: "value-1", condition: null, metadata: {} },
    { id: "value-end", source: "value-1", target: "end", condition: null, metadata: {} },
  ],
  schema_version: 1,
  metadata: { source: "controlled-browser-fixture" },
};

const workflow = (id: string, name: string) => ({
  id,
  user_id: USER.id,
  workspace_id: WORKSPACE.id,
  name,
  description: "Controlled browser integration fixture",
  definition: graph,
  revision: 7,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: null,
});

type Role = "owner" | "admin" | "member";
type RunStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";

interface ControlledState {
  role: Role;
  workflows: Record<string, ReturnType<typeof workflow>>;
  runs: Record<string, ReturnType<typeof makeRun>[]>;
  steps: Record<string, unknown[]>;
  traces: Record<string, unknown[]>;
  approvals: Record<string, ReturnType<typeof makeApproval> | null>;
  detailSequences: Record<string, RunStatus[]>;
  submitCount: number;
  approveCount: number;
  rejectCount: number;
  pendingApprovalCount: number;
  historyCount: number;
  stepCount: number;
  traceCount: number;
  submitResponse?: () => Promise<{ status: number; body: unknown }>;
  approveResponse?: () => Promise<{ status: number; body: unknown }>;
}

function makeRun(
  id: string,
  workflowId: string,
  status: RunStatus,
  overrides: Record<string, unknown> = {},
) {
  return {
    id,
    workflow_id: workflowId,
    workflow_revision: 7,
    definition_snapshot: graph,
    status,
    input: { request: id },
    node_outputs: { "value-1": { value: "server-output" } },
    output: status === "completed" ? { result: "done" } : null,
    error:
      status === "failed"
        ? { code: "NODE_FAILED", message: "Agent execution failed", node_id: "value-1" }
        : null,
    started_at: status === "pending" ? null : "2026-11-01T00:00:01Z",
    finished_at: ["completed", "failed", "cancelled"].includes(status)
      ? "2026-11-01T00:00:02Z"
      : null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function makeApproval(runId: string, status: "pending" | "approved" | "rejected" = "pending") {
  return {
    id: `approval-${runId}`,
    run_id: runId,
    workflow_revision: 7,
    node_id: "approval-1",
    prompt: "Approve controlled browser execution?",
    status,
    created_at: "2026-11-01T00:00:01Z",
    decided_at: status === "pending" ? null : "2026-11-01T00:00:02Z",
    decided_by: status === "pending" ? null : USER.id,
    decision_note: null,
  };
}

function initialState(role: Role = "owner"): ControlledState {
  return {
    role,
    workflows: {
      "workflow-a": workflow("workflow-a", "Workflow A"),
      "workflow-b": workflow("workflow-b", "Workflow B"),
    },
    runs: { "workflow-a": [], "workflow-b": [] },
    steps: {},
    traces: {},
    approvals: {},
    detailSequences: {},
    submitCount: 0,
    approveCount: 0,
    rejectCount: 0,
    pendingApprovalCount: 0,
    historyCount: 0,
    stepCount: 0,
    traceCount: 0,
  };
}

function listItem(run: ReturnType<typeof makeRun>) {
  const {
    definition_snapshot: _definition,
    input: _input,
    node_outputs: _outputs,
    output: _output,
    ...item
  } = run;
  return item;
}

async function fulfill(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installControlledApi(page: Page, state: ControlledState) {
  await page.addInitScript((user) => {
    window.localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: { user, isAuthenticated: true },
        version: 0,
      }),
    );
  }, USER);

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/auth/me") return fulfill(route, 200, USER);
    if (path === "/api/workspaces" && method === "GET")
      return fulfill(route, 200, { items: [WORKSPACE], total: 1 });
    if (path === `/api/workspaces/${WORKSPACE.id}/members` && method === "GET")
      return fulfill(route, 200, [
        {
          workspace_id: WORKSPACE.id,
          user_id: USER.id,
          role: state.role,
          created_at: "2026-11-01T00:00:00Z",
          updated_at: null,
        },
      ]);

    if (path === "/api/workflows" && method === "GET")
      return fulfill(route, 200, { items: Object.values(state.workflows), total: 2 });

    const workflowMatch = path.match(/^\/api\/workflows\/([^/]+)$/);
    if (workflowMatch && method === "GET") {
      const selected = state.workflows[decodeURIComponent(workflowMatch[1]!)];
      return selected
        ? fulfill(route, 200, selected)
        : fulfill(route, 404, { detail: "Not found" });
    }

    const runListMatch = path.match(/^\/api\/workflows\/([^/]+)\/runs$/);
    if (runListMatch && method === "GET") {
      state.historyCount += 1;
      const workflowId = decodeURIComponent(runListMatch[1]!);
      const items = state.runs[workflowId] ?? [];
      return fulfill(route, 200, { items: items.map(listItem), total: items.length });
    }

    const submitMatch = path.match(/^\/api\/workflows\/([^/]+)\/runs\/async$/);
    if (submitMatch && method === "POST") {
      state.submitCount += 1;
      if (state.submitResponse) {
        const response = await state.submitResponse();
        return fulfill(route, response.status, response.body);
      }
      const workflowId = decodeURIComponent(submitMatch[1]!);
      const created = makeRun(`run-created-${state.submitCount}`, workflowId, "pending");
      (state.runs[workflowId] ??= []).unshift(created);
      return fulfill(route, 202, created);
    }

    const detailMatch = path.match(/^\/api\/workflows\/([^/]+)\/runs\/([^/]+)$/);
    if (detailMatch && method === "GET") {
      const workflowId = decodeURIComponent(detailMatch[1]!);
      const runId = decodeURIComponent(detailMatch[2]!);
      const found = (state.runs[workflowId] ?? []).find((item) => item.id === runId);
      if (!found) return fulfill(route, 404, { detail: "Run not found" });
      const sequence = state.detailSequences[runId];
      if (sequence?.length) found.status = sequence.shift()!;
      if (["completed", "failed", "cancelled"].includes(found.status))
        found.finished_at = "2026-11-01T00:00:02Z";
      return fulfill(route, 200, found);
    }

    const stepsMatch = path.match(/^\/api\/workflows\/([^/]+)\/runs\/([^/]+)\/steps$/);
    if (stepsMatch && method === "GET") {
      state.stepCount += 1;
      return fulfill(route, 200, state.steps[decodeURIComponent(stepsMatch[2]!)] ?? []);
    }

    const traceMatch = path.match(/^\/api\/workflows\/([^/]+)\/runs\/([^/]+)\/trace$/);
    if (traceMatch && method === "GET") {
      state.traceCount += 1;
      return fulfill(route, 200, state.traces[decodeURIComponent(traceMatch[2]!)] ?? []);
    }

    const pendingMatch = path.match(
      /^\/api\/workflows\/([^/]+)\/runs\/([^/]+)\/approvals\/pending$/,
    );
    if (pendingMatch && method === "GET") {
      state.pendingApprovalCount += 1;
      const pending = state.approvals[decodeURIComponent(pendingMatch[2]!)];
      return pending ? fulfill(route, 200, pending) : fulfill(route, 404, { detail: "Not found" });
    }

    const decisionMatch = path.match(
      /^\/api\/workflows\/([^/]+)\/runs\/([^/]+)\/approvals\/([^/]+)\/(approve\/async|reject)$/,
    );
    if (decisionMatch && method === "POST") {
      const runId = decodeURIComponent(decisionMatch[2]!);
      const kind = decisionMatch[4];
      if (kind === "approve/async") {
        state.approveCount += 1;
        if (state.approveResponse) {
          const response = await state.approveResponse();
          return fulfill(route, response.status, response.body);
        }
        state.approvals[runId] = makeApproval(runId, "approved");
        return fulfill(route, 202, state.approvals[runId]);
      }
      state.rejectCount += 1;
      state.approvals[runId] = makeApproval(runId, "rejected");
      for (const runs of Object.values(state.runs)) {
        const selected = runs.find((item) => item.id === runId);
        if (selected) selected.status = "cancelled";
      }
      return fulfill(route, 200, state.approvals[runId]);
    }

    await route.continue();
  });
}

async function openWorkflow(page: Page, state: ControlledState, workflowId = "workflow-a") {
  await installControlledApi(page, state);
  await page.goto(`/workflows/${workflowId}?workspace_id=${WORKSPACE.id}`);
  const workflow = state.workflows[workflowId];
  if (!workflow) throw new Error(`Missing controlled workflow ${workflowId}`);
  await expect(page.getByRole("heading", { name: workflow.name })).toBeVisible();
  await expect(page.getByRole("region", { name: "Workflow execution" })).toBeVisible();
}

function deferredResponse() {
  let resolve!: (value: { status: number; body: unknown }) => void;
  const promise = new Promise<{ status: number; body: unknown }>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function detailStatus(page: Page, status: string) {
  return page.locator("p").filter({ hasText: new RegExp(`^Status: ${status}$`) });
}

test.describe("Workflow execution browser integration", () => {
  test("renders server run details, steps, trace, failures, empty states, and safe large JSON", async ({
    page,
    context,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const state = initialState();
    const largeValue = "x".repeat(21_000);
    const completed = makeRun("run-completed", "workflow-a", "completed", {
      output: { payload: largeValue },
    });
    const failed = makeRun("run-failed", "workflow-a", "failed");
    state.runs["workflow-a"] = [completed, failed];
    state.steps[completed.id] = [
      {
        id: "step-1",
        run_id: completed.id,
        sequence: 1,
        node_id: "value-1",
        node_kind: "value",
        status: "completed",
        input: { source: "server-step" },
        output: null,
        error: null,
        metadata: {},
        started_at: "2026-11-01T00:00:01Z",
        finished_at: "2026-11-01T00:00:02Z",
        duration_ms: 1000,
      },
    ];
    state.traces[completed.id] = [
      {
        id: "trace-1",
        run_id: completed.id,
        step_id: null,
        kind: "node_completed",
        payload: { source: "server-trace" },
        created_at: "2026-11-01T00:00:02Z",
      },
    ];

    await openWorkflow(page, state);
    await page.getByRole("button", { name: /run-completed/i }).click();

    await expect(detailStatus(page, "completed")).toBeVisible();
    await expect(page.locator("p").filter({ hasText: /^Workflow revision: r7$/ })).toBeVisible();
    await expect(page.getByText(/#1 · value-1 · value · completed/)).toBeVisible();
    await expect(page.getByText("node_completed", { exact: true })).toBeVisible();
    await expect(page.getByText(/Step ID: —/)).toBeVisible();
    await expect(page.getByText('"source": "server-trace"')).toBeVisible();
    await expect(page.getByText("null", { exact: true }).first()).toBeVisible();

    const output = page
      .locator("details")
      .filter({ has: page.getByText("Output", { exact: true }) })
      .first();
    await output.locator("summary").click();
    const preview = output.locator("pre");
    await expect(preview).toContainText("…");
    expect((await preview.textContent())?.length).toBeLessThanOrEqual(20_002);
    await output.getByRole("button", { name: "Copy JSON" }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toContain(largeValue);

    await page.getByRole("button", { name: /run-failed/i }).click();
    await expect(detailStatus(page, "failed")).toBeVisible();
    await expect(page.getByText(/NODE_FAILED: Agent execution failed · value-1/)).toBeVisible();
    await expect(page.getByText("No execution steps have been recorded.")).toBeVisible();
    await expect(page.getByText("No trace events have been recorded.")).toBeVisible();
  });

  test("validates run input, submits once, preserves 202 semantics, and handles dispatch failure", async ({
    page,
  }) => {
    const state = initialState();
    const submitGate = deferredResponse();
    state.submitResponse = () => submitGate.promise;
    await openWorkflow(page, state);

    const input = page.getByLabel("Workflow input (JSON object)");
    const runButton = page.getByRole("button", { name: "Run workflow" });
    for (const invalid of [
      "{",
      "[]",
      "null",
      "4",
      '"text"',
      '{"value":1e400}',
      '{"value":9007199254740992}',
    ]) {
      await input.fill(invalid);
      await expect(runButton).toBeDisabled();
    }

    await input.fill('{"nested":{"items":[1,true,null]}}');
    await runButton.dblclick();
    await expect.poll(() => state.submitCount).toBe(1);
    const accepted = makeRun("run-accepted", "workflow-a", "pending");
    state.runs["workflow-a"]!.unshift(accepted);
    submitGate.resolve({ status: 202, body: accepted });
    await expect(page.getByText("Run accepted for saved revision r7.")).toBeVisible();
    await expect(detailStatus(page, "pending")).toBeVisible();
    await expect(detailStatus(page, "completed")).toHaveCount(0);

    state.submitResponse = async () => ({
      status: 503,
      body: {
        error: {
          code: "WORKFLOW_DISPATCH_FAILED",
          message: "dispatch failed",
          details: { run_id: "run-dispatch" },
        },
      },
    });
    state.runs["workflow-a"]!.unshift(makeRun("run-dispatch", "workflow-a", "pending"));
    await runButton.click();
    await expect(page.getByText(/Run run-dispatch was created/)).toBeVisible();
    expect(state.submitCount).toBe(2);
  });

  test("follows the server lifecycle and performs bounded terminal related-data refresh", async ({
    page,
  }) => {
    const state = initialState();
    const active = makeRun("run-active", "workflow-a", "pending");
    state.runs["workflow-a"] = [active];
    state.steps[active.id] = [];
    state.traces[active.id] = [];
    state.detailSequences[active.id] = ["pending", "running", "completed"];
    await openWorkflow(page, state);

    await page.getByRole("button", { name: /run-active/i }).click();
    await expect(detailStatus(page, "pending")).toBeVisible();
    await expect(detailStatus(page, "running")).toBeVisible({ timeout: 7000 });
    await expect(detailStatus(page, "completed")).toBeVisible({
      timeout: 7000,
    });
    await expect.poll(() => state.stepCount).toBeGreaterThanOrEqual(2);
    await expect.poll(() => state.traceCount).toBeGreaterThanOrEqual(2);
    await expect.poll(() => state.historyCount).toBeGreaterThanOrEqual(2);

    const before = {
      steps: state.stepCount,
      trace: state.traceCount,
      history: state.historyCount,
    };
    await page.getByRole("button", { name: "Refresh" }).click();
    await expect.poll(() => state.stepCount).toBeGreaterThan(before.steps);
    await expect.poll(() => state.traceCount).toBeGreaterThan(before.trace);
    await expect.poll(() => state.historyCount).toBeGreaterThan(before.history);
  });

  for (const role of ["owner", "admin"] as const) {
    test(`${role} can approve once without claiming run completion`, async ({ page }) => {
      const state = initialState(role);
      const paused = makeRun(`run-${role}`, "workflow-a", "paused");
      state.runs["workflow-a"] = [paused];
      state.approvals[paused.id] = makeApproval(paused.id);
      const approvalGate = deferredResponse();
      state.approveResponse = () => approvalGate.promise;
      await openWorkflow(page, state);

      await page.getByRole("button", { name: new RegExp(paused.id) }).click();
      await expect(page.getByText("Approve controlled browser execution?")).toBeVisible();
      await page.getByLabel("Decision note (optional)").fill(`${role} browser note`);
      page.once("dialog", (dialog) => void dialog.accept());
      await page.getByRole("button", { name: "Approve and resume" }).dblclick();
      await expect.poll(() => state.approveCount).toBe(1);
      const approved = makeApproval(paused.id, "approved");
      state.approvals[paused.id] = approved;
      approvalGate.resolve({ status: 202, body: approved });

      await expect(page.getByText(/accepted for asynchronous resume/i)).toBeVisible();
      await expect(detailStatus(page, "paused")).toBeVisible();
      await expect(detailStatus(page, "completed")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Approve and resume" })).toHaveCount(0);
    });
  }

  test("member can inspect a paused run without querying or deciding approval", async ({
    page,
  }) => {
    const state = initialState("member");
    const paused = makeRun("run-member", "workflow-a", "paused");
    state.runs["workflow-a"] = [paused];
    state.approvals[paused.id] = makeApproval(paused.id);
    await openWorkflow(page, state);

    await page.getByRole("button", { name: /run-member/i }).click();
    await expect(detailStatus(page, "paused")).toBeVisible();
    await expect(page.getByText(/role cannot decide approvals/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve and resume" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
    expect(state.pendingApprovalCount).toBe(0);
  });

  test("reject refreshes the run to cancelled and dirty graph blocks submission", async ({
    page,
  }) => {
    const state = initialState("admin");
    const paused = makeRun("run-reject", "workflow-a", "paused");
    state.runs["workflow-a"] = [paused];
    state.approvals[paused.id] = makeApproval(paused.id);
    await openWorkflow(page, state);

    await page.getByRole("button", { name: /run-reject/i }).click();
    page.once("dialog", (dialog) => void dialog.accept());
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect.poll(() => state.rejectCount).toBe(1);
    await expect(detailStatus(page, "cancelled")).toBeVisible();

    await page.getByRole("button", { name: "Add VALUE" }).click();
    await expect(page.getByText("Unsaved changes")).toBeVisible();
    await expect(page.getByRole("button", { name: "Run workflow" })).toBeDisabled();
    await expect(page.getByText(/Save or discard all graph changes/)).toBeVisible();
  });

  test("late workflow A submission cannot contaminate workflow B", async ({ page }) => {
    const state = initialState();
    const submitGate = deferredResponse();
    state.submitResponse = () => submitGate.promise;
    await openWorkflow(page, state);

    await page.getByRole("button", { name: "Run workflow" }).click();
    await expect.poll(() => state.submitCount).toBe(1);
    await page.getByRole("link", { name: "Back to workflows" }).click();
    await page.getByRole("link", { name: "Workflow B", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Workflow B" })).toBeVisible();

    const lateRun = makeRun("late-run-a", "workflow-a", "pending");
    state.runs["workflow-a"]!.unshift(lateRun);
    submitGate.resolve({ status: 202, body: lateRun });

    await expect(page.getByRole("region", { name: "Workflow execution" })).toBeVisible();
    await expect(page.getByText("late-run-a")).toHaveCount(0);
    await expect(page.getByText(/Run accepted for saved revision/)).toHaveCount(0);
    await expect(page.getByText("No runs have been recorded for this workflow.")).toBeVisible();
  });
});
