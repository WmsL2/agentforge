import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { WorkflowCanvasEditor } from "./workflow-canvas-editor";
import {
  NodeConfigurationEditor,
  type NodeConfigurationEditorProps,
} from "./node-configuration-editor";
import type { WorkflowCanvasProps } from "./workflow-canvas";
import { nextNode, removeNode } from "@/lib/workflow/canvas-rules";
import { useAuthStore } from "@/stores/auth-store";
import { qk } from "@/lib/query-keys";
import { bindKnowledgeLifecycle, clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import type { KnowledgeBaseRead, User, WorkflowRead, WorkflowGraph } from "@/types";
const uuid = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const W = uuid(100),
  W2 = uuid(200),
  A: User = {
    id: uuid(1000),
    email: "a@test",
    is_active: true,
    role: "admin",
    created_at: "2026-11-23",
  },
  B: User = { ...A, id: uuid(2000) };
const root = `/api/workspaces/${W}/knowledge-bases`;
const base = (n = 1, w = W): KnowledgeBaseRead => ({
  id: uuid(n),
  workspace_id: w,
  name: `Base ${n}`,
  description: null,
  created_by_user_id: A.id,
  created_at: "2026-11-23",
  updated_at: null,
});
const config = () => ({
  knowledge_base_id: uuid(1),
  query_source: "literal",
  query: "Original query",
  top_k: 5,
});
function definition(): WorkflowGraph {
  return {
    schema_version: 1,
    entry_node_id: "start",
    metadata: { root: "keep" },
    nodes: [
      { id: "start", kind: "start", config: {}, metadata: {} },
      { id: "knowledge-1", kind: "knowledge", config: config(), metadata: { node: "keep" } },
      {
        id: "agent-1",
        kind: "agent",
        config: {
          runner: "langgraph",
          instruction: "Original instruction",
          model: "original-model",
        },
        metadata: { agent: "keep" },
      },
      { id: "end", kind: "end", config: {}, metadata: {} },
    ],
    edges: [
      {
        id: "s-k",
        source: "start",
        target: "knowledge-1",
        condition: null,
        metadata: { edge: "keep" },
      },
      { id: "k-a", source: "knowledge-1", target: "agent-1", condition: null, metadata: {} },
      { id: "a-e", source: "agent-1", target: "end", condition: null, metadata: {} },
    ],
  };
}
function makeWorkflow(): WorkflowRead {
  return {
    id: uuid(5000),
    workspace_id: W,
    user_id: A.id,
    name: "Workflow",
    description: null,
    definition: definition(),
    revision: 1,
    created_at: "2026-11-23",
    updated_at: null,
  };
}
function FakeCanvas({ graph, editable, onChange, labels }: WorkflowCanvasProps) {
  return (
    <div>
      <output data-testid="canvas">{JSON.stringify(graph)}</output>
      <button
        disabled={!editable}
        onClick={() =>
          onChange({ ...graph, nodes: [...graph.nodes, nextNode(graph, "knowledge")] }, true)
        }
      >
        {labels.addKnowledge}
      </button>
      {graph.nodes.map((n) => (
        <button
          key={n.id}
          onClick={() =>
            onChange(
              { ...graph, nodes: graph.nodes.map((x) => ({ ...x, selected: x.id === n.id })) },
              false,
            )
          }
        >
          select {n.id}
        </button>
      ))}
      <button
        disabled={!editable}
        onClick={() =>
          onChange(
            {
              ...graph,
              nodes: graph.nodes.map((n) =>
                n.id === "knowledge-1" ? { ...n, position: { x: 999, y: 111 } } : n,
              ),
            },
            true,
          )
        }
      >
        move knowledge
      </button>
      <button disabled={!editable} onClick={() => onChange(removeNode(graph, "knowledge-1"), true)}>
        remove knowledge
      </button>
    </div>
  );
}
let client: QueryClient,
  unbind: () => void,
  workflow: WorkflowRead,
  bases: KnowledgeBaseRead[],
  members: boolean,
  overrides: Map<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn(),
  saved = vi.fn();
function response(url: string, options: RequestInit = {}) {
  const parsed = new URL(url, "https://app.test"),
    path = parsed.pathname,
    method = options.method ?? "GET",
    custom = overrides.get(`${method} ${path}`);
  if (custom) return custom();
  const parts = path.split("/");
  if (parts[2] === "workspaces" && parts[4] === "members")
    return Response.json(
      members
        ? [
            {
              user_id: useAuthStore.getState().user?.id,
              workspace_id: parts[3],
              role: "member",
              created_at: "2026-11-23",
              updated_at: null,
            },
          ]
        : [],
    );
  if (parts[2] === "workspaces" && parts[4] === "knowledge-bases") {
    if (parts[5]) {
      const found = bases.find((b) => b.id === parts[5] && b.workspace_id === parts[3]);
      return found ? Response.json(found) : Response.json({}, { status: 404 });
    }
    const rows = bases.filter((b) => b.workspace_id === parts[3]),
      skip = Number(parsed.searchParams.get("skip")),
      limit = Number(parsed.searchParams.get("limit"));
    return Response.json({ items: rows.slice(skip, skip + limit), total: rows.length });
  }
  if (parts[2] === "workspaces") return Response.json({ id: parts[3] });
  if (path === "/api/workflows/validate") return Response.json({ is_valid: true, issues: [] });
  if (parts[2] === "workflows" && method === "PATCH") {
    const payload = JSON.parse(String(options.body));
    return Response.json({
      ...workflow,
      definition: payload.definition,
      revision: workflow.revision + 1,
    });
  }
  throw new Error(`Unexpected HTTP: ${method} ${path}`);
}
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={{ workflows: messages.workflows }}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </NextIntlClientProvider>
  );
}
function mount() {
  const view = render(
    <WorkflowCanvasEditor
      workflow={workflow}
      userId={A.id}
      CanvasComponent={FakeCanvas}
      onSaved={saved}
    />,
    { wrapper },
  );
  return {
    ...view,
    change: (next = workflow, user = A.id) =>
      view.rerender(
        <WorkflowCanvasEditor
          workflow={next}
          userId={user}
          CanvasComponent={FakeCanvas}
          onSaved={saved}
        />,
      ),
  };
}
const graph = () =>
  JSON.parse(screen.getByTestId("canvas").textContent!) as {
    nodes: { id: string; data: { config: Record<string, unknown>; metadata: unknown } }[];
  };
const nodeConfig = (id = "knowledge-1") => graph().nodes.find((n) => n.id === id)!.data.config;
const calls = (method: string, path?: string) =>
  fetchMock.mock.calls.filter(
    ([u, o]) => o.method === method && (!path || String(u).split("?")[0] === path),
  );
async function select(id = "knowledge-1") {
  await userEvent.click(screen.getByRole("button", { name: `select ${id}` }));
}
async function ready(id = "knowledge-1") {
  const view = mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select(id);
  await waitFor(() => expect(screen.getByRole("option", { name: "Base 1" })).toBeInTheDocument());
  return view;
}
async function editQuery(value = "New query") {
  fireEvent.change(screen.getByLabelText("Literal query text"), { target: { value } });
}
async function apply() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
}
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
beforeEach(() => {
  useAuthStore.getState().setUser(A);
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  unbind = bindKnowledgeLifecycle(client);
  workflow = makeWorkflow();
  bases = Array.from({ length: 12 }, (_, i) => base(i + 1));
  members = true;
  overrides = new Map();
  saved.mockReset();
  fetchMock.mockReset().mockImplementation(response);
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  unbind();
  client.clear();
  vi.mocked(window.confirm).mockRestore();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});
it("loads existing knowledge config without dirtying it or fetching indexes", async () => {
  await ready();
  expect(nodeConfig()).toEqual(config());
  expect(screen.getByLabelText("Literal query text")).toHaveValue("Original query");
  expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();
  expect(fetchMock.mock.calls.some(([u]) => /index|search|ask/.test(String(u)))).toBe(false);
});
it("keeps an unapplied draft across selection, then applies immutably with metadata", async () => {
  await ready();
  await editQuery();
  expect(nodeConfig().query).toBe("Original query");
  expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
  await select("agent-1");
  await select();
  expect(screen.getByLabelText("Literal query text")).toHaveValue("New query");
  await apply();
  expect(nodeConfig().query).toBe("New query");
  expect(graph().nodes.find((n) => n.id === "knowledge-1")!.data.metadata).toEqual({
    node: "keep",
  });
  expect(calls("PATCH")).toHaveLength(0);
});
it("switches source and removes opposite fields only on Apply", async () => {
  await ready();
  fireEvent.change(screen.getByLabelText("Query source"), { target: { value: "workflow_input" } });
  fireEvent.change(screen.getByLabelText("Workflow input key"), { target: { value: "question" } });
  expect(nodeConfig()).toHaveProperty("query", "Original query");
  await apply();
  expect(nodeConfig()).toEqual({
    knowledge_base_id: uuid(1),
    query_source: "workflow_input",
    input_key: "question",
    top_k: 5,
  });
  fireEvent.change(screen.getByLabelText("Query source"), { target: { value: "literal" } });
  await editQuery("Literal again");
  await apply();
  expect(nodeConfig()).toEqual({ ...config(), query: "Literal again" });
});
for (const text of ["", "   ", "😀".repeat(2001)])
  it(`rejects invalid literal query length ${text.length}`, async () => {
    await ready();
    await editQuery(text);
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(nodeConfig()).toEqual(config());
  });
it("accepts 2000 Unicode code points", async () => {
  await ready();
  await editQuery("😀".repeat(2000));
  await apply();
  expect(nodeConfig().query).toBe("😀".repeat(2000));
});
for (const top of ["0", "6", "1.5", "NaN", "Infinity", "", "1e0"])
  it(`rejects Knowledge top_k ${top}`, async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Top K (1–5)"), { target: { value: top } });
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(nodeConfig().top_k).toBe(5);
  });
for (const top of ["1", "5"])
  it(`accepts Knowledge top_k ${top}`, async () => {
    await ready();
    await editQuery("changed");
    fireEvent.change(screen.getByLabelText("Top K (1–5)"), { target: { value: top } });
    await apply();
    expect(nodeConfig().top_k).toBe(Number(top));
  });
it("rejects a blank workflow input key", async () => {
  await ready();
  fireEvent.change(screen.getByLabelText("Query source"), { target: { value: "workflow_input" } });
  fireEvent.change(screen.getByLabelText("Workflow input key"), { target: { value: " " } });
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
});
for (const value of ["", "not-a-uuid", null, 42])
  it(`rejects invalid existing UUID ${JSON.stringify(value)}`, async () => {
    workflow.definition.nodes[1]!.config.knowledge_base_id = value;
    mount();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled(),
    );
    await select();
    await editQuery();
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(nodeConfig().knowledge_base_id).toBe(value);
  });
for (const field of ["workspace_id", "actor_user_id", "min_score", "output_mapping"])
  it(`does not apply unsupported knowledge field ${field}`, async () => {
    workflow.definition.nodes[1]!.config[field] = "untrusted";
    await ready();
    await editQuery();
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
    expect(nodeConfig()[field]).toBe("untrusted");
  });
it("preserves an ordinary Agent without introducing a binding", async () => {
  await ready("agent-1");
  fireEvent.change(screen.getByLabelText(/Instruction/), {
    target: { value: "Updated instruction" },
  });
  await apply();
  expect(nodeConfig("agent-1")).toEqual({
    runner: "langgraph",
    instruction: "Updated instruction",
    model: "original-model",
  });
});
it("binds and clears Agent knowledge without changing other fields", async () => {
  await ready("agent-1");
  fireEvent.change(screen.getByLabelText("Bind knowledge base (optional)"), {
    target: { value: uuid(2) },
  });
  await apply();
  expect(nodeConfig("agent-1")).toEqual({
    runner: "langgraph",
    instruction: "Original instruction",
    model: "original-model",
    knowledge_base_id: uuid(2),
  });
  fireEvent.change(screen.getByLabelText("Bind knowledge base (optional)"), {
    target: { value: "" },
  });
  await apply();
  expect(nodeConfig("agent-1")).not.toHaveProperty("knowledge_base_id");
  expect(nodeConfig("agent-1").instruction).toBe("Original instruction");
});
it("keeps an existing bound Agent recognized by its allowlist", async () => {
  workflow.definition.nodes[2]!.config.knowledge_base_id = uuid(1);
  await ready("agent-1");
  fireEvent.change(screen.getByLabelText(/Instruction/), {
    target: { value: "New instruction" },
  });
  await apply();
  expect(nodeConfig("agent-1").knowledge_base_id).toBe(uuid(1));
});
for (const field of ["query_source", "top_k", "actor_user_id"])
  it(`rejects unrelated Agent config field ${field}`, async () => {
    workflow.definition.nodes[2]!.config[field] = "untrusted";
    await ready("agent-1");
    fireEvent.change(screen.getByLabelText(/Instruction/), { target: { value: "new" } });
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  });
it("paginates without forgetting a historical binding on page two", async () => {
  workflow.definition.nodes[1]!.config.knowledge_base_id = uuid(12);
  await ready();
  expect(screen.getByDisplayValue("Base 12")).toBeInTheDocument();
  expect(nodeConfig().knowledge_base_id).toBe(uuid(12));
  await userEvent.click(screen.getByRole("button", { name: "Next knowledge bases" }));
  await screen.findByRole("option", { name: "Base 11" });
  fireEvent.change(screen.getByLabelText("Knowledge base"), { target: { value: uuid(11) } });
  await apply();
  expect(nodeConfig().knowledge_base_id).toBe(uuid(11));
  expect(fetchMock.mock.calls.some(([u]) => String(u).includes("skip=10&limit=10"))).toBe(true);
});
it("filters foreign Workspace options and refuses arbitrary injected options", async () => {
  overrides.set(`GET ${root}`, () => Response.json({ items: [base(), base(21, W2)], total: 2 }));
  await ready();
  expect(screen.queryByRole("option", { name: "Base 21" })).not.toBeInTheDocument();
  const picker = screen.getByLabelText("Knowledge base");
  const option = document.createElement("option");
  option.value = uuid(99);
  option.text = "injected";
  picker.appendChild(option);
  fireEvent.change(picker, { target: { value: uuid(99) } });
  expect(nodeConfig().knowledge_base_id).toBe(uuid(1));
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
});
it("does not mislabel a loading historical binding as deleted", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${root}/${uuid(1)}`, () => pending.promise);
  await ready();
  await screen.findByText("Verifying the current knowledge base…");
  expect(
    screen.queryByText("The current knowledge base or its access is unavailable."),
  ).not.toBeInTheDocument();
  await editQuery();
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  await act(async () => pending.resolve(Response.json(base())));
  await apply();
});
it("shows an unavailable missing binding without clearing stored config", async () => {
  bases = [];
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select();
  await screen.findByText("The current knowledge base or its access is unavailable.");
  await editQuery();
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  expect(nodeConfig().knowledge_base_id).toBe(uuid(1));
});
it("shows a safe list error and retry without losing a draft", async () => {
  overrides.set(`GET ${root}`, () =>
    Response.json({ detail: "private token stack" }, { status: 500 }),
  );
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select();
  await screen.findByText("Failed to load knowledge bases.");
  await editQuery("draft survives");
  expect(screen.queryByText("private token stack")).not.toBeInTheDocument();
  overrides.delete(`GET ${root}`);
  await userEvent.click(screen.getByRole("button", { name: "Retry knowledge bases" }));
  await screen.findByRole("option", { name: "Base 1" });
  expect(screen.getByLabelText("Literal query text")).toHaveValue("draft survives");
});
it("selection alone does not dirty the graph", async () => {
  await ready();
  expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();
  expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
});
it("discards unapplied drafts and confirms deleting a drafted node", async () => {
  await ready();
  await editQuery();
  vi.mocked(window.confirm).mockReturnValue(false);
  await userEvent.click(screen.getByRole("button", { name: "remove knowledge" }));
  expect(graph().nodes.some((n) => n.id === "knowledge-1")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(screen.getByLabelText("Literal query text")).toHaveValue("New query");
  vi.mocked(window.confirm).mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  await select();
  expect(screen.getByLabelText("Literal query text")).toHaveValue("Original query");
});
it("validates the applied snapshot before PATCH and preserves graph metadata", async () => {
  await ready();
  await editQuery();
  await apply();
  await userEvent.click(screen.getByRole("button", { name: "Save graph" }));
  await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
  const validated = JSON.parse(calls("POST", "/api/workflows/validate")[0]![1].body),
    patched = JSON.parse(calls("PATCH")[0]![1].body).definition;
  expect(patched).toEqual(validated);
  expect(patched.metadata).toEqual({ root: "keep" });
  expect(patched.nodes.find((n: { id: string }) => n.id === "knowledge-1").metadata.node).toBe(
    "keep",
  );
  expect(patched.schema_version).toBe(1);
});
it("blocks PATCH for rejected server validation and hides private issue text", async () => {
  overrides.set("POST /api/workflows/validate", () =>
    Response.json({
      is_valid: false,
      issues: [
        {
          code: "knowledge_query_invalid",
          message: "private server token path",
          node_id: "knowledge-1",
          edge_id: null,
        },
      ],
    }),
  );
  await ready();
  await editQuery();
  await apply();
  await userEvent.click(screen.getByRole("button", { name: "Save graph" }));
  await screen.findByText(/Knowledge configuration was rejected/);
  expect(calls("PATCH")).toHaveLength(0);
  expect(screen.queryByText("private server token path")).not.toBeInTheDocument();
});
it("retains applied edits after PATCH failure without exposing raw detail", async () => {
  overrides.set(`PATCH /api/workflows/${workflow.id}`, () =>
    Response.json({ detail: "private server key" }, { status: 503 }),
  );
  await ready();
  await editQuery();
  await apply();
  await userEvent.click(screen.getByRole("button", { name: "Save graph" }));
  await screen.findByText("Service unavailable");
  expect(nodeConfig().query).toBe("New query");
  expect(screen.queryByText("private server key")).not.toBeInTheDocument();
});
it("does not overwrite pending knowledge drafts on a remote revision", async () => {
  const view = await ready();
  await editQuery("local draft");
  view.change({
    ...workflow,
    revision: 2,
    definition: { ...workflow.definition, metadata: { remote: true } },
  });
  await screen.findByText(/revision 2/i);
  expect(screen.getByLabelText("Literal query text")).toHaveValue("local draft");
  expect(screen.getByRole("button", { name: "Save graph" })).toBeDisabled();
});
for (const change of ["workflow", "workspace", "account", "logout", "same-user"])
  it(`isolates pending binding/draft on ${change}`, async () => {
    const view = await ready();
    await editQuery("old draft");
    const pending = deferred<Response>();
    overrides.set(`GET ${root}/${uuid(2)}`, () => pending.promise);
    fireEvent.change(screen.getByLabelText("Knowledge base"), { target: { value: uuid(2) } });
    await waitFor(() => expect(calls("GET", `${root}/${uuid(2)}`)).toHaveLength(1));
    if (change === "workflow") view.change({ ...workflow, id: uuid(6000) });
    else if (change === "workspace") {
      bases.push(base(1, W2));
      view.change({ ...workflow, workspace_id: W2 });
    } else
      await act(async () => {
        useAuthStore.getState().logout();
        if (change !== "logout") useAuthStore.getState().setUser(change === "account" ? B : A);
        view.change(workflow, change === "account" ? B.id : A.id);
      });
    await act(async () => pending.resolve(Response.json(base(2))));
    expect(nodeConfig().knowledge_base_id).toBe(uuid(1));
    expect(screen.queryByDisplayValue("old draft")).not.toBeInTheDocument();
    expect(calls("PATCH")).toHaveLength(0);
  });
it("invalidates a deleted selected base and permits repairing to another verified option", async () => {
  await ready();
  await editQuery();
  await act(async () => clearKnowledgeScope(client, qk.knowledge.base(A.id, W, uuid(1))));
  expect(screen.queryByRole("option", { name: "Base 1" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Knowledge base"), { target: { value: uuid(2) } });
  await apply();
  expect(nodeConfig().knowledge_base_id).toBe(uuid(2));
});
it("blocks old selection after confirmed workspace access loss", async () => {
  await ready();
  await editQuery();
  await act(async () => clearKnowledgeScope(client, qk.knowledge.workspace(A.id, W)));
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  expect(screen.getByLabelText("Knowledge base")).toBeDisabled();
});
it("disables new controls when membership is missing", async () => {
  members = false;
  mount();
  await select();
  await screen.findByText(messages.workflows.canvas.readOnly);
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  expect(calls("GET", root)).toHaveLength(0);
});
it("handles StrictMode replay with scoped verification", async () => {
  render(
    <StrictMode>
      <WorkflowCanvasEditor workflow={workflow} userId={A.id} CanvasComponent={FakeCanvas} />
    </StrictMode>,
    { wrapper },
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select();
  await screen.findByRole("option", { name: "Base 1" });
  await editQuery();
  await apply();
  expect(nodeConfig().query).toBe("New query");
});
it("keeps English and Polish canvas keys in parity", () => {
  const keys = (v: object): string[] =>
    Object.entries(v)
      .flatMap(([k, v]) => (typeof v === "object" ? keys(v).map((c) => `${k}.${c}`) : [k]))
      .sort();
  expect(keys(messages.workflows.canvas)).toEqual(keys(polish.workflows.canvas));
});

it("shows empty choices without inventing IDs and still allows an unbound Agent", async () => {
  bases = [];
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select("agent-1");
  await screen.findByText("No knowledge bases on this page");
  expect(screen.getAllByRole("option")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText(/Instruction/), { target: { value: "Plain agent" } });
  await apply();
  expect(nodeConfig("agent-1")).not.toHaveProperty("knowledge_base_id");
});
it("does not verify selected metadata returned from another workspace", async () => {
  overrides.set(`GET ${root}/${uuid(1)}`, () =>
    Response.json({ ...base(1, W2), name: "foreign private name" }),
  );
  await ready();
  await editQuery();
  await waitFor(() =>
    expect(
      screen.getAllByText("Current knowledge base is not yet verified.").length,
    ).toBeGreaterThan(0),
  );
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  expect(screen.queryByText("foreign private name")).not.toBeInTheDocument();
});
it("does not adopt cached choices after membership is revoked", async () => {
  await ready();
  await editQuery();
  members = false;
  await act(async () => {
    await client.invalidateQueries({ queryKey: qk.workspaces.members(A.id, W) });
  });
  fireEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
  expect(nodeConfig().query).toBe("Original query");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled(),
  );
  expect(screen.queryByLabelText("Knowledge base")).not.toBeInTheDocument();
  expect(nodeConfig().knowledge_base_id).toBe(uuid(1));
});
it("provides read-only Knowledge inspection with disabled selection and inputs", async () => {
  const ReadOnly = (props: NodeConfigurationEditorProps) => (
    <NodeConfigurationEditor {...props} editable={false} />
  );
  render(
    <WorkflowCanvasEditor
      workflow={workflow}
      userId={A.id}
      CanvasComponent={FakeCanvas}
      NodeEditorComponent={ReadOnly}
    />,
    { wrapper },
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "move knowledge" })).toBeEnabled());
  await select();
  await screen.findByRole("option", { name: "Base 1" });
  expect(screen.getByLabelText("Knowledge base")).toBeDisabled();
  expect(screen.getByLabelText("Literal query text")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled();
  expect(calls("PATCH")).toHaveLength(0);
});
it("invalidates selection during metadata refetch until new authority returns", async () => {
  await ready();
  await editQuery();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeEnabled(),
  );
  const pending = deferred<Response>();
  overrides.set(`GET ${root}/${uuid(1)}`, () => pending.promise);
  await act(async () => {
    void client.invalidateQueries({ queryKey: qk.knowledge.base(A.id, W, uuid(1)), exact: true });
  });
  fireEvent.click(screen.getByRole("button", { name: "Apply configuration" }));
  expect(nodeConfig().query).toBe("Original query");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply configuration" })).toBeDisabled(),
  );
  await act(async () => pending.resolve(Response.json(base())));
  await apply();
  expect(nodeConfig().query).toBe("New query");
});
it("clears a missing historical Agent binding explicitly without replacing it", async () => {
  workflow.definition.nodes[2]!.config.knowledge_base_id = uuid(99);
  await ready("agent-1");
  await screen.findByText("The current knowledge base or its access is unavailable.");
  fireEvent.change(screen.getByLabelText("Bind knowledge base (optional)"), {
    target: { value: "" },
  });
  await apply();
  expect(nodeConfig("agent-1")).toEqual({
    runner: "langgraph",
    instruction: "Original instruction",
    model: "original-model",
  });
});
