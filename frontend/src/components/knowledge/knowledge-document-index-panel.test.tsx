import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { useAuthStore } from "@/stores/auth-store";
import { bindKnowledgeLifecycle, clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { useKnowledgeIndexStatus } from "@/hooks/use-knowledge";
import { qk } from "@/lib/query-keys";
import type { User, KnowledgeIndexStatusRead, KnowledgeIndexJobRead } from "@/types";
import { KnowledgeManagement } from "./knowledge-management";
import { INDEX_CODES } from "./knowledge-index-utils";
const route = vi.hoisted(() => ({ search: "workspace_id=w1", push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/knowledge/kb1",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ push: route.push, replace: route.replace }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
const A: User = {
  id: "a",
  email: "a@test",
  is_active: true,
  role: "admin",
  created_at: "2026-11-21",
};
const B: User = { ...A, id: "b" };
const basePath = "/api/workspaces/w1/knowledge-bases/kb1",
  docPath = `${basePath}/documents/d1`,
  indexPath = `${docPath}/index`;
const status = (overrides: Partial<KnowledgeIndexStatusRead> = {}): KnowledgeIndexStatusRead => ({
  document_id: "d1",
  job_id: null,
  status: "not_indexed",
  active_generation_id: null,
  chunk_count: 0,
  embedding_model: null,
  index_version: null,
  error_code: null,
  ...overrides,
});
const job = (overrides: Partial<KnowledgeIndexJobRead> = {}): KnowledgeIndexJobRead => ({
  id: "job-new",
  document_id: "d1",
  status: "pending",
  embedding_model: "model",
  embedding_dimensions: 1536,
  index_generation_id: "generation-new",
  chunking_config_version: "v1",
  attempt_count: 0,
  error_code: null,
  created_at: "2026-11-21",
  ...overrides,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
let client: QueryClient,
  unbind: () => void,
  state: KnowledgeIndexStatusRead,
  postResult: KnowledgeIndexJobRead,
  role: string,
  parse: "ready" | "failed",
  overrides: Map<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn();
function response(url: string, options: RequestInit = {}) {
  const path = new URL(url, "https://app.test").pathname,
    method = options.method ?? "GET";
  const custom = overrides.get(`${method} ${path}`);
  if (custom) return custom();
  const parts = path.split("/"),
    w = parts[3]!,
    b = parts[5]!,
    d = parts[7]!;
  if (path === "/api/workspaces")
    return Response.json({
      items: ["w1", "w2"].map((id) => ({
        id,
        name: id,
        created_by_user_id: "a",
        created_at: "2026-11-21",
        updated_at: null,
      })),
    });
  if (parts[4] === "members")
    return Response.json(
      role === "missing"
        ? []
        : [
            {
              workspace_id: w,
              user_id: useAuthStore.getState().user?.id,
              role,
              created_at: "2026-11-21",
              updated_at: null,
            },
          ],
    );
  if (parts.length === 4) return Response.json({ id: w });
  if (parts.length === 6)
    return Response.json({
      id: b,
      workspace_id: w,
      name: b,
      description: "base",
      created_by_user_id: "a",
      created_at: "2026-11-21",
      updated_at: null,
    });
  const document = {
    id: d || "d1",
    workspace_id: w,
    knowledge_base_id: b,
    created_by_user_id: "a",
    filename: `${d || "d1"}-${w}-${b}.txt`,
    mime_type: "text/plain",
    size_bytes: 10,
    sha256: "abc",
    parse_status: parse,
    parse_error_code: null,
    page_count: null,
    parse_metadata: {},
    created_at: "2026-11-21",
    updated_at: null,
  };
  if (parts.length === 7)
    return Response.json({
      items: [document, { ...document, id: "d2", filename: `d2-${w}-${b}.txt` }],
      total: 2,
    });
  if (parts[8] === "index")
    return method === "POST"
      ? Response.json(postResult, { status: 202 })
      : Response.json(w === "w1" && b === "kb1" && d === "d1" ? state : status({ document_id: d }));
  return Response.json(document);
}
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <NextIntlClientProvider
      locale="en"
      messages={{ knowledgeManagement: messages.knowledgeManagement, common: messages.common }}
    >
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </NextIntlClientProvider>
  );
}
function mount(b = "kb1", u = "a") {
  const view = render(<KnowledgeManagement userId={u} knowledgeBaseId={b} />, { wrapper });
  return {
    ...view,
    change: (base = b, user = u) =>
      view.rerender(<KnowledgeManagement userId={user} knowledgeBaseId={base} />),
  };
}
const calls = (method = "GET") =>
  fetchMock.mock.calls.filter(([u, o]) => String(u).endsWith("/index") && o.method === method);
const panel = () => screen.getByRole("region", { name: "Index status" });
async function open() {
  const view = mount();
  await userEvent.click(await screen.findByRole("button", { name: "d1-w1-kb1.txt" }));
  await screen.findByRole("region", { name: "Index status" });
  await waitFor(() =>
    expect(
      within(panel()).queryByText("Latest job:") ?? within(panel()).queryByRole("alert"),
    ).toBeInTheDocument(),
  );
  await waitFor(() => expect(calls()).toHaveLength(1));
  return view;
}
async function tick(ms = 100) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
async function openClock() {
  vi.useFakeTimers();
  const view = mount();
  for (let i = 0; i < 10 && !screen.queryByRole("button", { name: "d1-w1-kb1.txt" }); i++)
    await tick();
  fireEvent.click(screen.getByRole("button", { name: "d1-w1-kb1.txt" }));
  for (let i = 0; i < 10 && !screen.queryByRole("region", { name: "Index status" }); i++)
    await tick();
  await tick();
  return view;
}
beforeAll(() =>
  Object.defineProperties(HTMLElement.prototype, {
    hasPointerCapture: { configurable: true, value: () => false },
    setPointerCapture: { configurable: true, value: () => {} },
    releasePointerCapture: { configurable: true, value: () => {} },
    scrollIntoView: { configurable: true, value: () => {} },
  }),
);
beforeEach(() => {
  useAuthStore.getState().setUser(A);
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  unbind = bindKnowledgeLifecycle(client);
  state = status();
  postResult = job();
  role = "owner";
  parse = "ready";
  overrides = new Map();
  route.search = "workspace_id=w1";
  route.push.mockReset();
  route.replace.mockReset();
  fetchMock.mockReset().mockImplementation(response);
  vi.stubGlobal("fetch", fetchMock);
  focusManager.setFocused(true);
});
afterEach(() => {
  cleanup();
  unbind();
  client.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  focusManager.setFocused(undefined);
  useAuthStore.getState().logout();
});
for (const value of ["not_indexed", "pending", "running", "succeeded", "failed", "unknown"])
  it(`displays authoritative ${value} status`, async () => {
    state = status({
      status: value as "failed",
      job_id: value === "not_indexed" ? null : "latest-job",
    });
    await open();
    expect(
      within(panel()).getByText(
        messages.knowledgeManagement.documents.index.states[value as "failed"],
      ),
    ).toBeInTheDocument();
    expect(panel().textContent).not.toContain("%");
    expect(calls("POST")).toHaveLength(0);
  });
it("separates latest failed job from active successful generation", async () => {
  state = status({
    status: "failed",
    job_id: "failed-job",
    active_generation_id: "old-generation",
    chunk_count: 42,
    embedding_model: "old-model",
    index_version: "old-version",
    error_code: "EMBEDDING_TIMEOUT",
  });
  await open();
  for (const text of [
    "failed-job",
    "old-generation",
    "old-model",
    "old-version",
    "42",
    "The latest build failed. The previous successful index remains active.",
  ])
    expect(within(panel()).getByText(text)).toBeInTheDocument();
});
it("rejects status for another document and never writes", async () => {
  state = status({ document_id: "other", status: "running" });
  await open();
  expect(within(panel()).getByRole("alert")).toHaveTextContent(
    messages.knowledgeManagement.scopeError,
  );
  expect(within(panel()).queryByRole("button", { name: "Build index" })).not.toBeInTheDocument();
});
for (const level of ["owner", "admin", "member"])
  it(`enforces ${level} role`, async () => {
    role = level;
    await open();
    expect(Boolean(within(panel()).queryByRole("button", { name: "Build index" }))).toBe(
      level !== "member",
    );
    if (level !== "member") {
      await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
      await within(panel()).findByText(/Index request accepted/);
      expect(calls("POST")).toHaveLength(1);
      expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/members"))).toHaveLength(2);
    }
  });
it("disables writes for failed parse while preserving download", async () => {
  parse = "failed";
  await open();
  expect(
    within(panel()).getByText(messages.knowledgeManagement.documents.index.notReady),
  ).toBeInTheDocument();
  expect(within(panel()).queryByRole("button", { name: "Build index" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download original" })).toBeInTheDocument();
});
it("requires rebuild confirmation and permits cancellation", async () => {
  state = status({ status: "succeeded", job_id: "old", active_generation_id: "active" });
  await open();
  await userEvent.click(within(panel()).getByRole("button", { name: "Rebuild index" }));
  expect(calls("POST")).toHaveLength(0);
  await userEvent.click(within(panel()).getByRole("button", { name: "Cancel" }));
  expect(calls("POST")).toHaveLength(0);
  await userEvent.click(within(panel()).getByRole("button", { name: "Rebuild index" }));
  await userEvent.click(within(panel()).getByRole("button", { name: "Confirm rebuild" }));
  await within(panel()).findByText(/Index request accepted/);
  expect(calls("POST")).toHaveLength(1);
});
it("retries failed jobs only by explicit action", async () => {
  state = status({ status: "failed", job_id: "old", error_code: "EMBEDDING_TIMEOUT" });
  await open();
  expect(calls("POST")).toHaveLength(0);
  await userEvent.click(within(panel()).getByRole("button", { name: "Retry index" }));
  await within(panel()).findByText(/Index request accepted/);
  expect(calls("POST")).toHaveLength(1);
});
it("locks double submits and treats 202 as acceptance, not success", async () => {
  const pending = deferred<Response>();
  overrides.set(`POST ${indexPath}`, () => pending.promise);
  await open();
  const button = within(panel()).getByRole("button", { name: "Build index" });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(calls("POST")).toHaveLength(1));
  await act(async () =>
    pending.resolve(
      Response.json(job({ id: "existing-active-job", status: "running" }), { status: 202 }),
    ),
  );
  await within(panel()).findByText(/existing-active-job/);
  expect(within(panel()).getByText("State returned with acceptance: Running")).toBeInTheDocument();
  expect(within(panel()).queryByText("Succeeded")).not.toBeInTheDocument();
});
for (const code of [409, 422, 500])
  it(`preserves current index after POST ${code}`, async () => {
    overrides.set(`POST ${indexPath}`, () =>
      Response.json({ detail: "private/token/trace" }, { status: code }),
    );
    await open();
    await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
    await within(panel()).findByRole("alert");
    expect(within(panel()).getByText("Not indexed")).toBeInTheDocument();
    expect(panel().textContent).not.toContain("private/token");
    expect(calls("POST")).toHaveLength(1);
  });
it("refuses write after fresh membership downgrade", async () => {
  await open();
  role = "member";
  await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
  await waitFor(() =>
    expect(within(panel()).queryByRole("button", { name: "Build index" })).not.toBeInTheDocument(),
  );
  expect(calls("POST")).toHaveLength(0);
});
it("does not post while permission preflight is pending", async () => {
  await open();
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
  await screen.findByText("Checking write permission and submitting index request…");
  expect(calls("POST")).toHaveLength(0);
  await act(async () =>
    pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "member" }])),
  );
  expect(calls("POST")).toHaveLength(0);
});
it("does not query index before valid base and document", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${basePath}`, () => pending.promise);
  mount();
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u]) => String(u) === basePath)).toBe(true),
  );
  expect(calls()).toHaveLength(0);
  await act(async () => pending.resolve(Response.json({ id: "wrong", workspace_id: "w1" })));
  expect(calls()).toHaveLength(0);
});
it("waits for document metadata before querying index", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${docPath}`, () => pending.promise);
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "d1-w1-kb1.txt" }));
  expect(calls()).toHaveLength(0);
  await act(async () =>
    pending.resolve(Response.json({ id: "wrong", workspace_id: "w1", knowledge_base_id: "kb1" })),
  );
  expect(calls()).toHaveLength(0);
});
for (const code of INDEX_CODES)
  it(`maps actual ${code} to safe text`, async () => {
    state = status({ status: "failed", error_code: code });
    await open();
    expect(
      within(panel()).getByText(messages.knowledgeManagement.documents.index.errors[code]),
    ).toBeInTheDocument();
  });
it("hides unknown error codes", async () => {
  state = status({ status: "failed", error_code: "secret-token-path-stack" });
  await open();
  expect(panel().textContent).not.toContain("secret-token-path-stack");
  expect(
    within(panel()).getByText(messages.knowledgeManagement.documents.index.errors.unknown),
  ).toBeInTheDocument();
});
it("keeps English and Polish index translation keys in parity", () => {
  const keys = (v: object): string[] =>
    Object.entries(v)
      .flatMap(([k, v]) => (typeof v === "object" ? keys(v).map((child) => `${k}.${child}`) : [k]))
      .sort();
  expect(keys(messages.knowledgeManagement.documents.index)).toEqual(
    keys(polish.knowledgeManagement.documents.index),
  );
});
for (const value of ["pending", "running"])
  it(`polls ${value}, stops at terminal success`, async () => {
    state = status({ status: value as "pending", job_id: "job" });
    await openClock();
    const initial = calls().length;
    await tick(3000);
    expect(calls()).toHaveLength(initial + 1);
    state = status({ status: "succeeded", job_id: "job", active_generation_id: "generation" });
    await tick(3000);
    const finished = calls().length;
    await tick(30_000);
    expect(calls()).toHaveLength(finished);
  });
for (const value of ["not_indexed", "failed", "succeeded", "unknown"])
  it(`does not poll ${value}`, async () => {
    state = status({ status: value as "failed" });
    await openClock();
    const initial = calls().length;
    await tick(30_000);
    expect(calls()).toHaveLength(initial);
  });
it("default index hook remains non-polling", async () => {
  vi.useFakeTimers();
  state = status({ status: "pending" });
  renderHook(() => useKnowledgeIndexStatus("a", "w1", "kb1", "d1"), { wrapper });
  await tick();
  expect(calls()).toHaveLength(1);
  await tick(30_000);
  expect(calls()).toHaveLength(1);
});
it("stops polling on network failure and resumes only after manual refresh", async () => {
  state = status({ status: "running", job_id: "job" });
  await openClock();
  overrides.set(`GET ${indexPath}`, () => Promise.reject(new TypeError("private network URL")));
  await tick(3000);
  const failed = calls().length;
  await tick(30_000);
  expect(calls()).toHaveLength(failed);
  expect(within(panel()).getByRole("alert").textContent).not.toContain("private network URL");
  overrides.delete(`GET ${indexPath}`);
  fireEvent.click(within(panel()).getByRole("button", { name: "Refresh index status" }));
  await tick();
  expect(calls()).toHaveLength(failed + 1);
  await tick(3000);
  expect(calls()).toHaveLength(failed + 2);
});
it("does not poll in background tabs", async () => {
  state = status({ status: "running" });
  await openClock();
  focusManager.setFocused(false);
  const before = calls().length;
  await tick(30_000);
  expect(calls()).toHaveLength(before);
  focusManager.setFocused(true);
  await tick(3000);
  expect(calls().length).toBeGreaterThan(before);
});
it("bounds stale status confirmation after 202 and never presents old success as new completion", async () => {
  state = status({ status: "succeeded", job_id: "old", active_generation_id: "old-generation" });
  await openClock();
  fireEvent.click(within(panel()).getByRole("button", { name: "Rebuild index" }));
  fireEvent.click(within(panel()).getByRole("button", { name: "Confirm rebuild" }));
  await tick();
  expect(calls("POST")).toHaveLength(1);
  expect(within(panel()).getByText(/Waiting for status to confirm/)).toBeInTheDocument();
  await tick(33_000);
  const stopped = calls().length;
  await tick(30_000);
  expect(calls()).toHaveLength(stopped);
  expect(within(panel()).queryByRole("button", { name: "Rebuild index" })).not.toBeInTheDocument();
  expect(within(panel()).getByText(/Automatic confirmation has stopped/)).toBeInTheDocument();
});
it("tracks accepted job identity through pending and success", async () => {
  await openClock();
  fireEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
  await tick();
  state = status({ status: "pending", job_id: "job-new" });
  await tick(3000);
  expect(within(panel()).queryByText(/Waiting for status/)).not.toBeInTheDocument();
  state = status({
    status: "succeeded",
    job_id: "job-new",
    active_generation_id: "new-generation",
  });
  await tick(3000);
  expect(within(panel()).getByText("new-generation")).toBeInTheDocument();
  const finished = calls().length;
  await tick(30_000);
  expect(calls()).toHaveLength(finished);
});
for (const reason of [
  "close",
  "workspace",
  "base",
  "document",
  "logout",
  "account",
  "same-user",
  "delete",
  "base-delete",
  "workspace-loss",
])
  it(`stops old polling on ${reason}`, async () => {
    state = status({ status: "running", job_id: "old" });
    const view = await openClock();
    const oldCalls = () => calls().filter(([u]) => String(u) === indexPath).length;
    if (reason === "close") fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    else if (reason === "workspace" || reason === "base") {
      if (reason === "workspace") route.search = "workspace_id=w2";
      view.change("kb2");
    } else if (reason === "document") {
      fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
      fireEvent.click(screen.getByRole("button", { name: "d2-w1-kb1.txt" }));
    } else
      await act(async () => {
        if (reason === "delete")
          clearKnowledgeScope(client, qk.knowledge.document("a", "w1", "kb1", "d1"));
        else if (reason === "base-delete")
          clearKnowledgeScope(client, qk.knowledge.base("a", "w1", "kb1"));
        else if (reason === "workspace-loss")
          clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1"));
        else {
          useAuthStore.getState().logout();
          if (reason !== "logout") {
            useAuthStore.getState().setUser(reason === "account" ? B : A);
            view.change("kb1", reason === "account" ? "b" : "a");
          }
        }
      });
    await tick();
    const stopped = oldCalls();
    await tick(30_000);
    expect(oldCalls()).toBe(stopped);
  });

for (const result of ["failed", "not_indexed"])
  it(`stops polling after transition to ${result}`, async () => {
    state = status({ status: "running", job_id: "job" });
    await openClock();
    state = status({ status: result as "failed", job_id: "job" });
    await tick(3000);
    const stopped = calls().length;
    await tick(30_000);
    expect(calls()).toHaveLength(stopped);
  });
it("does not poll a mismatched document response", async () => {
  state = status({ status: "running", document_id: "wrong" });
  await openClock();
  const count = calls().length;
  await tick(30_000);
  expect(calls()).toHaveLength(count);
  expect(within(panel()).getByRole("alert")).toHaveTextContent(
    messages.knowledgeManagement.scopeError,
  );
});
for (const http of [403, 404])
  it(`handles status ${http} without clearing another workspace`, async () => {
    client.setQueryData(qk.knowledge.document("a", "w2", "kb2", "other"), { keep: true });
    overrides.set(`GET ${indexPath}`, () => {
      if (http === 403) role = "member";
      return Response.json({ detail: "private trace" }, { status: http });
    });
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "d1-w1-kb1.txt" }));
    await waitFor(() => expect(calls().length).toBeGreaterThan(0));
    if (http === 404)
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    else
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Build index" })).not.toBeInTheDocument(),
      );
    expect(client.getQueryData(qk.knowledge.document("a", "w2", "kb2", "other"))).toEqual({
      keep: true,
    });
    if (http === 403)
      expect(
        fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/members")).length,
      ).toBeGreaterThan(1);
  });
for (const http of [403, 404])
  it(`handles POST ${http} without automatic retry or leaking detail`, async () => {
    await open();
    overrides.set(`POST ${indexPath}`, () => {
      if (http === 403) role = "member";
      return Response.json({ detail: "private/token/trace" }, { status: http });
    });
    await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
    if (http === 404)
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    else
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Build index" })).not.toBeInTheDocument(),
      );
    expect(calls("POST")).toHaveLength(1);
    expect(screen.queryByText("private/token/trace")).not.toBeInTheDocument();
  });
for (const reason of [
  "base",
  "workspace",
  "document",
  "logout",
  "account",
  "same-user",
  "delete",
  "base-delete",
  "workspace-loss",
])
  it(`isolates delayed POST 202 after ${reason}`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${indexPath}`, () => pending.promise);
    const view = await open();
    await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    if (reason === "base" || reason === "workspace") {
      if (reason === "workspace") route.search = "workspace_id=w2";
      view.change("kb2");
      await userEvent.click(
        await screen.findByRole("button", {
          name: `d1-${reason === "workspace" ? "w2" : "w1"}-kb2.txt`,
        }),
      );
      await screen.findByRole("region", { name: "Index status" });
    } else if (reason === "document") {
      await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
      await userEvent.click(screen.getByRole("button", { name: "d2-w1-kb1.txt" }));
      await screen.findByRole("region", { name: "Index status" });
    } else
      await act(async () => {
        if (reason === "delete")
          clearKnowledgeScope(client, qk.knowledge.document("a", "w1", "kb1", "d1"));
        else if (reason === "base-delete")
          clearKnowledgeScope(client, qk.knowledge.base("a", "w1", "kb1"));
        else if (reason === "workspace-loss")
          clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1"));
        else {
          useAuthStore.getState().logout();
          if (reason !== "logout") {
            useAuthStore.getState().setUser(reason === "account" ? B : A);
            view.change("kb1", reason === "account" ? "b" : "a");
          }
        }
      });
    const oldGetCount = calls().filter(([u]) => String(u) === indexPath).length;
    await act(async () =>
      pending.resolve(Response.json(job({ id: "late-private-old-job" }), { status: 202 })),
    );
    expect(screen.queryByText(/late-private-old-job/)).not.toBeInTheDocument();
    expect(calls().filter(([u]) => String(u) === indexPath)).toHaveLength(oldGetCount);
    expect(route.push).not.toHaveBeenCalled();
  });
for (const reason of ["document", "workspace", "logout", "account", "same-user", "delete"])
  it(`isolates delayed GET status after ${reason}`, async () => {
    const pending = deferred<Response>();
    overrides.set(`GET ${indexPath}`, () => pending.promise);
    const view = mount();
    await userEvent.click(await screen.findByRole("button", { name: "d1-w1-kb1.txt" }));
    await waitFor(() => expect(calls()).toHaveLength(1));
    const request = calls()[0]![1];
    if (reason === "document") {
      await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
      await userEvent.click(screen.getByRole("button", { name: "d2-w1-kb1.txt" }));
    } else if (reason === "workspace") {
      route.search = "workspace_id=w2";
      view.change("kb2");
    } else
      await act(async () => {
        if (reason === "delete")
          clearKnowledgeScope(client, qk.knowledge.document("a", "w1", "kb1", "d1"));
        else {
          useAuthStore.getState().logout();
          if (reason !== "logout") {
            useAuthStore.getState().setUser(reason === "account" ? B : A);
            view.change("kb1", reason === "account" ? "b" : "a");
          }
        }
      });
    await waitFor(() => expect(request.signal.aborted).toBe(true));
    await act(async () =>
      pending.resolve(Response.json(status({ status: "running", job_id: "late-old-get" }))),
    );
    expect(screen.queryByText("late-old-get")).not.toBeInTheDocument();
    expect(calls("POST")).toHaveLength(0);
  });
it("does not post after scope cleanup during delayed permission check", async () => {
  const view = await open();
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
  await screen.findByText("Checking write permission and submitting index request…");
  await act(async () => clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1")));
  await act(async () =>
    pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "owner" }])),
  );
  expect(calls("POST")).toHaveLength(0);
  view.unmount();
});
it("clears index cache precisely when its document is deleted", async () => {
  await open();
  const foreign = qk.knowledge.index("a", "w2", "kb2", "d1");
  client.setQueryData(foreign, status());
  await act(async () => clearKnowledgeScope(client, qk.knowledge.document("a", "w1", "kb1", "d1")));
  expect(client.getQueryData(qk.knowledge.index("a", "w1", "kb1", "d1"))).toBeUndefined();
  expect(client.getQueryData(foreign)).toBeDefined();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("an old polling error cannot dismiss a new document", async () => {
  state = status({ status: "running" });
  await openClock();
  const pending = deferred<Response>();
  overrides.set(`GET ${indexPath}`, () => pending.promise);
  await tick(3000);
  fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
  fireEvent.click(screen.getByRole("button", { name: "d2-w1-kb1.txt" }));
  await tick();
  await act(async () =>
    pending.resolve(Response.json({ detail: "old forbidden" }, { status: 403 })),
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(panel().textContent).not.toContain("old forbidden");
  expect(within(panel()).getByText("d2")).toBeInTheDocument();
});

for (const mismatch of [{ document_id: "other" }, { id: "" }, { status: "unknown" }])
  it(`rejects invalid 202 job ${JSON.stringify(mismatch)}`, async () => {
    overrides.set(`POST ${indexPath}`, () =>
      Response.json({ ...job(), ...mismatch }, { status: 202 }),
    );
    await open();
    await userEvent.click(within(panel()).getByRole("button", { name: "Build index" }));
    await waitFor(() =>
      expect(within(panel()).getByRole("alert")).toHaveTextContent(
        messages.knowledgeManagement.scopeError,
      ),
    );
    expect(within(panel()).queryByText(/Index request accepted/)).not.toBeInTheDocument();
    expect(calls("POST")).toHaveLength(1);
  });

it("works through StrictMode effect replay without disabling its resource lease", async () => {
  render(
    <StrictMode>
      <KnowledgeManagement userId="a" knowledgeBaseId="kb1" />
    </StrictMode>,
    { wrapper },
  );
  await userEvent.click(await screen.findByRole("button", { name: "d1-w1-kb1.txt" }));
  await userEvent.click(await screen.findByRole("button", { name: "Build index" }));
  await screen.findByText(/Index request accepted/);
  expect(calls("POST")).toHaveLength(1);
});
it("checks the synchronous resource lease before issuing another polling request", async () => {
  vi.useFakeTimers();
  state = status({ status: "pending" });
  let current = true;
  const view = renderHook(
    () =>
      useKnowledgeIndexStatus("a", "w1", "kb1", "d1", {
        pollActive: true,
        isCurrent: () => current,
      }),
    { wrapper },
  );
  await tick();
  expect(calls()).toHaveLength(1);
  current = false;
  await act(async () => {
    await view.result.current.refetch();
  });
  await tick(30_000);
  expect(calls()).toHaveLength(1);
});
