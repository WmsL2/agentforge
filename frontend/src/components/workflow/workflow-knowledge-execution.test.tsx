import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { WorkflowExecutionPanel } from "./workflow-execution-panel";
import { useAuthStore } from "@/stores/auth-store";
import { qk } from "@/lib/query-keys";
import { createDefaultWorkflowGraph } from "@/lib/workflow/default-graph";
import type { RunStepRead, User, WorkflowRead, WorkflowRunRead } from "@/types";

const uuid = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const A: User = { id: uuid(1), email: "a@test", is_active: true, role: "user", created_at: "now" };
const B: User = { ...A, id: uuid(2) };
const r3 = uuid(3),
  r4 = uuid(4);
const item = {
  chunk_id: "real-chunk",
  document_id: "real-document",
  filename: "evidence.pdf",
  page_start: 1,
  page_end: null,
  similarity_score: 0,
};
const evidence = {
  query: "actual retrieval",
  total: 1,
  results: [{ ...item, content: "actual evidence" }],
};
let workflow: WorkflowRead, runs: Map<string, WorkflowRunRead>, steps: Map<string, RunStepRead[]>;
let client: QueryClient;
let intercept: ((path: string) => Promise<Response> | undefined) | undefined;
const fetchMock = vi.fn();
function makeRun(
  id = r3,
  kind: "agent" | "knowledge" = "knowledge",
  bound = true,
): WorkflowRunRead {
  return {
    id,
    workflow_id: workflow.id,
    workflow_revision: id === r3 ? 3 : 4,
    definition_snapshot: {
      ...createDefaultWorkflowGraph(),
      nodes: [
        { id: "node", kind, config: bound ? { knowledge_base_id: uuid(20) } : {}, metadata: {} },
      ],
    },
    status: "completed",
    input: {},
    node_outputs: {},
    output: null,
    error: null,
    started_at: "2026-11-23T00:00:00Z",
    finished_at: "2026-11-23T00:00:01Z",
    created_at: "2026-11-23T00:00:00Z",
    updated_at: null,
  };
}
function makeStep(
  run_id = r3,
  output: unknown = evidence,
  node_kind: "agent" | "knowledge" = "knowledge",
): RunStepRead {
  return {
    id: uuid(30),
    run_id,
    sequence: 1,
    node_id: "node",
    node_kind,
    status: "completed",
    input: {},
    output,
    error: null,
    metadata: {},
    started_at: "2026-11-23T00:00:00Z",
    finished_at: "2026-11-23T00:00:01Z",
    duration_ms: 1000,
  };
}
const pathFor = (id = r3, suffix = "") => `/api/workflows/${workflow.id}/runs/${id}${suffix}`;
async function response(input: string) {
  const path = String(input).split("?")[0]!;
  const overridden = intercept?.(path);
  if (overridden) return overridden;
  if (path.includes("/members"))
    return Response.json([
      {
        user_id: useAuthStore.getState().user?.id,
        workspace_id: workflow.workspace_id,
        role: "owner",
      },
    ]);
  if (path.endsWith("/runs")) return Response.json({ items: [...runs.values()], total: runs.size });
  for (const [id, run] of runs) {
    if (path.endsWith(`/runs/${id}`)) return Response.json(run);
    if (path.endsWith(`/runs/${id}/steps`)) return Response.json(steps.get(id) ?? []);
    if (path.endsWith(`/runs/${id}/trace`))
      return Response.json([
        {
          id: uuid(40),
          run_id: id,
          step_id: null,
          kind: "tool_completed",
          payload: { sources: [{ ...item, filename: "TRACE-ONLY-FAKE.pdf" }] },
          created_at: "now",
        },
      ]);
  }
  throw new Error(`Unexpected HTTP ${path}`);
}
function panel(user = A.id, selectedWorkflow = workflow) {
  return (
    <WorkflowExecutionPanel
      workflow={selectedWorkflow}
      userId={user}
      editorState={{ hasUnsavedChanges: false, hasRevisionConflict: false, operation: "idle" }}
    />
  );
}
function mount() {
  return render(panel(), {
    wrapper: ({ children }) => (
      <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </NextIntlClientProvider>
    ),
  });
}
async function select(id = r3) {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(id) }));
}
const region = () => screen.findByRole("region", { name: "Knowledge Retrieval" });
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
beforeEach(() => {
  useAuthStore.getState().setUser(A);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  workflow = {
    id: uuid(10),
    workspace_id: uuid(11),
    user_id: A.id,
    name: "Workflow",
    description: null,
    definition: createDefaultWorkflowGraph(),
    revision: 4,
    created_at: "now",
    updated_at: null,
  };
  runs = new Map([
    [r3, makeRun()],
    [r4, makeRun(r4)],
  ]);
  steps = new Map([
    [r3, [makeStep()]],
    [r4, [makeStep(r4, { ...evidence, query: "r4 query" })]],
  ]);
  intercept = undefined;
  fetchMock.mockReset().mockImplementation(response);
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.unstubAllGlobals();
  useAuthStore.getState().setUser(null);
});

it("integrates actual results beside raw JSON and preserves Trace separately", async () => {
  mount();
  await select();
  const result = await region();
  expect(within(result).getByText("actual evidence")).toBeInTheDocument();
  expect(result).not.toHaveTextContent("TRACE-ONLY-FAKE.pdf");
  expect(screen.getByText("tool_completed")).toBeInTheDocument();
  expect(screen.getAllByText("Output", { selector: "summary" }).length).toBeGreaterThan(0);
  expect(screen.getByText(/#1 · node · knowledge · completed/)).toBeInTheDocument();
});
it.each([true, false])(
  "uses historical r3 binding=%s despite opposite current canvas config",
  async (bound) => {
    workflow.definition.nodes.push({
      id: "node",
      kind: "agent",
      config: bound ? {} : { knowledge_base_id: uuid(20) },
      metadata: {},
    });
    runs.set(r3, makeRun(r3, "agent", bound));
    steps.set(r3, [
      makeStep(r3, { answer: "historical answer", status: "answered", sources: [item] }, "agent"),
    ]);
    mount();
    await select();
    await screen.findByText(/#1 · node · agent · completed/);
    if (bound)
      expect(
        await screen.findByRole("region", { name: "Knowledge Agent Answer" }),
      ).toHaveTextContent("historical answer");
    else {
      expect(
        screen.queryByRole("region", { name: "Knowledge Agent Answer" }),
      ).not.toBeInTheDocument();
      expect(screen.getAllByText(/historical answer/).length).toBeGreaterThan(0);
    }
  },
);
it("preserves multiple historical attempts in actual sequence", async () => {
  steps.set(r3, [makeStep(), { ...makeStep(), id: uuid(31), sequence: 2 }]);
  mount();
  await select();
  await waitFor(() =>
    expect(screen.getAllByRole("region", { name: "Knowledge Retrieval" })).toHaveLength(2),
  );
  expect(screen.getByText(/#1 · node/)).toBeInTheDocument();
  expect(screen.getByText(/#2 · node/)).toBeInTheDocument();
});
it.each([true, false])(
  "switches between r3 and r4 using each run's own binding (%s)",
  async (bound) => {
    runs.set(r3, makeRun(r3, "agent", bound));
    runs.set(r4, makeRun(r4, "agent", !bound));
    for (const id of [r3, r4])
      steps.set(id, [
        makeStep(id, { answer: `answer ${id}`, status: "answered", sources: [item] }, "agent"),
      ]);
    mount();
    for (const [id, expected] of [
      [r3, bound],
      [r4, !bound],
      [r3, bound],
    ] as const) {
      await select(id);
      await waitFor(() =>
        expect(screen.getByText(/#1 · node · agent · completed/)).toBeInTheDocument(),
      );
      if (expected)
        expect(
          await screen.findByRole("region", { name: "Knowledge Agent Answer" }),
        ).toHaveTextContent(`answer ${id}`);
      else
        await waitFor(() =>
          expect(
            screen.queryByRole("region", { name: "Knowledge Agent Answer" }),
          ).not.toBeInTheDocument(),
        );
    }
  },
);
it("does not interpret cached detail/steps until both fresh HTTP reads finish", async () => {
  client.setQueryData(qk.workflowRuns.detail(A.id, workflow.id, r3), makeRun());
  client.setQueryData(qk.workflowRuns.steps(A.id, workflow.id, r3), [makeStep()]);
  const detail = deferred(),
    rows = deferred();
  intercept = (path) =>
    path === pathFor() ? detail.promise : path === pathFor(r3, "/steps") ? rows.promise : undefined;
  mount();
  await select();
  expect(await screen.findByText(/unavailable for interpretation/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
  await act(async () => detail.resolve(Response.json(makeRun())));
  expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
  await act(async () => rows.resolve(Response.json([makeStep()])));
  await region();
});
it("does not interpret a foreign-run step", async () => {
  steps.set(r3, [makeStep(r4)]);
  mount();
  await select();
  expect(await screen.findByText(/unavailable for interpretation/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
});
it("fails closed for a mismatched run ID", async () => {
  intercept = (path) =>
    path === pathFor() ? Promise.resolve(Response.json({ ...makeRun(), id: r4 })) : undefined;
  mount();
  await select();
  expect(await screen.findByText(/does not belong to this workflow/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
});
it("late old-run details cannot replace the newly selected run", async () => {
  const old = deferred();
  intercept = (path) => (path === pathFor() ? old.promise : undefined);
  mount();
  await select();
  await select(r4);
  expect(await region()).toHaveTextContent("r4 query");
  await act(async () => old.resolve(Response.json(makeRun())));
  expect(await region()).toHaveTextContent("r4 query");
  expect(await region()).not.toHaveTextContent("actual retrieval");
});
it("late old-run steps cannot replace new results", async () => {
  const old = deferred();
  intercept = (path) => (path === pathFor(r3, "/steps") ? old.promise : undefined);
  mount();
  await select();
  await select(r4);
  expect(await region()).toHaveTextContent("r4 query");
  await act(async () => old.resolve(Response.json([makeStep()])));
  expect(await region()).toHaveTextContent("r4 query");
});
it.each(["detail", "steps"])(
  "hides structured results during %s refetch and restores only verified output",
  async (target) => {
    mount();
    await select();
    await region();
    const pending = deferred();
    intercept = (path) =>
      path === pathFor(r3, target === "steps" ? "/steps" : "") ? pending.promise : undefined;
    await act(async () => {
      void client.invalidateQueries({
        queryKey:
          target === "steps"
            ? qk.workflowRuns.steps(A.id, workflow.id, r3)
            : qk.workflowRuns.detail(A.id, workflow.id, r3),
      });
    });
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/unavailable for interpretation/)).toBeInTheDocument();
    await act(async () =>
      pending.resolve(Response.json(target === "steps" ? [makeStep()] : makeRun())),
    );
    await region();
  },
);
it.each(["account", "workspace", "workflow", "logout", "same-user"])(
  "isolates pending results after %s change",
  async (change) => {
    const pending = deferred();
    intercept = (path) => (path === pathFor(r3, "/steps") ? pending.promise : undefined);
    const view = mount();
    await select();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).split("?")[0] === pathFor(r3, "/steps")),
      ).toBe(true),
    );
    await act(async () => {
      if (change === "account") useAuthStore.getState().setUser(B);
      if (change === "logout" || change === "same-user") useAuthStore.getState().logout();
      if (change === "same-user") useAuthStore.getState().setUser(A);
    });
    if (change === "workspace") view.rerender(panel(A.id, { ...workflow, workspace_id: uuid(12) }));
    if (change === "workflow") view.rerender(panel(A.id, { ...workflow, id: uuid(13) }));
    if (change === "account") view.rerender(panel(B.id));
    await act(async () => pending.resolve(Response.json([makeStep()])));
    expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
    expect(screen.queryByText(/#1 · node/)).not.toBeInTheDocument();
  },
);
it.each(["detail", "steps", "trace"])(
  "distinguishes %s API failure from empty evidence",
  async (target) => {
    intercept = (path) =>
      path === pathFor(r3, target === "detail" ? "" : `/${target}`)
        ? Promise.resolve(Response.json({ detail: "PRIVATE_PROVIDER_SECRET" }, { status: 503 }))
        : undefined;
    mount();
    await select();
    const text =
      target === "detail"
        ? "The selected run could not be loaded."
        : target === "steps"
          ? "Run steps could not be loaded. The run itself has not been marked failed."
          : "Trace events could not be loaded. The run itself has not been marked failed.";
    expect(await screen.findByText(text, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_PROVIDER_SECRET/)).not.toBeInTheDocument();
    expect(screen.queryByText("No retrieval matches were returned.")).not.toBeInTheDocument();
    if (target === "trace") await region();
    else
      expect(screen.queryByRole("region", { name: "Knowledge Retrieval" })).not.toBeInTheDocument();
  },
);
