import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { useAuthStore } from "@/stores/auth-store";
import { bindKnowledgeLifecycle, clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import type { User, KnowledgeSearchResponse, KnowledgeAskResponse } from "@/types";
import { KnowledgeManagement } from "./knowledge-management";
import { PLAYGROUND_CODES, PLAYGROUND_TEXT_LIMIT } from "./knowledge-playground-utils";
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
    role: "admin",
    is_active: true,
    created_at: "2026-11-23",
  },
  B: User = { ...A, id: "b" };
const basePath = "/api/workspaces/w1/knowledge-bases/kb1",
  searchPath = `${basePath}/search`,
  askPath = `${basePath}/ask`;
const result = (overrides: Partial<KnowledgeSearchResponse> = {}): KnowledgeSearchResponse => ({
  query: "actual query",
  embedding_model: "model-real",
  total: 1,
  results: [
    {
      knowledge_base_id: "kb1",
      filename: "真实资料.txt",
      document_id: "document-real",
      chunk_id: "chunk-real",
      chunk_index: 7,
      content: "real retrieved text",
      similarity_score: 0.75,
      page_start: 2,
      page_end: 3,
      start_offset: 100,
      end_offset: 200,
    },
  ],
  ...overrides,
});
const answer = (overrides: Partial<KnowledgeAskResponse> = {}): KnowledgeAskResponse => ({
  status: "answered",
  answer: "Grounded answer",
  sources: [
    {
      filename: "Source.txt",
      document_id: "source-document",
      chunk_id: "source-chunk",
      page_start: 4,
      page_end: 5,
      similarity_score: 0.8,
    },
  ],
  ...overrides,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
let client: QueryClient,
  unbind: () => void,
  role: string,
  searchResult: KnowledgeSearchResponse,
  askResult: KnowledgeAskResponse,
  overrides: Map<string, () => Response | Promise<Response>>;
const fetchMock = vi.fn();
function response(url: string, options: RequestInit = {}) {
  const path = new URL(url, "https://app.test").pathname,
    method = options.method ?? "GET";
  const custom = overrides.get(`${method} ${path}`);
  if (custom) return custom();
  const parts = path.split("/"),
    w = parts[3]!,
    b = parts[5]!;
  if (path === "/api/workspaces")
    return Response.json({
      items: ["w1", "w2"].map((id) => ({
        id,
        name: id,
        created_by_user_id: "a",
        created_at: "2026-11-23",
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
              created_at: "2026-11-23",
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
      created_at: "2026-11-23",
      updated_at: null,
    });
  if (parts[6] === "documents") return Response.json({ items: [], total: 0 });
  if (parts[6] === "search")
    return Response.json(
      w === "w1" && b === "kb1" ? searchResult : result({ results: [], total: 0 }),
    );
  if (parts[6] === "ask") return Response.json(askResult);
  throw new Error(`Unexpected HTTP boundary: ${path}`);
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
function mount(base = "kb1", user = "a") {
  const view = render(<KnowledgeManagement userId={user} knowledgeBaseId={base} />, { wrapper });
  return {
    ...view,
    change: (b = base, u = user) =>
      view.rerender(<KnowledgeManagement userId={u} knowledgeBaseId={b} />),
  };
}
const calls = (mode = "search") =>
  fetchMock.mock.calls.filter(([u, o]) => String(u).endsWith(`/${mode}`) && o.method === "POST");
const queryInput = () => screen.getByLabelText("Query");
async function ready() {
  const view = mount();
  await screen.findByLabelText("Query");
  return view;
}
function fill(value = "first query") {
  fireEvent.change(queryInput(), { target: { value } });
}
async function search(value = "first query") {
  fill(value);
  await userEvent.click(screen.getByRole("button", { name: "Search knowledge" }));
}
async function ask(value = "A question?") {
  await userEvent.click(screen.getByRole("tab", { name: "Ask knowledge" }));
  fireEvent.change(screen.getByLabelText("Question"), { target: { value } });
  await userEvent.click(screen.getByRole("button", { name: "Ask knowledge" }));
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
  role = "owner";
  searchResult = result();
  askResult = answer();
  overrides = new Map();
  route.search = "workspace_id=w1";
  route.push.mockReset();
  route.replace.mockReset();
  fetchMock.mockReset().mockImplementation(response);
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  unbind();
  client.clear();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});
it("never searches automatically and submits real scoped default parameters", async () => {
  await ready();
  fill("  trim me  ");
  expect(calls()).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Search knowledge" }));
  await screen.findByText("real retrieved text");
  expect(calls()).toHaveLength(1);
  expect(calls()[0]![0]).toBe(searchPath);
  expect(JSON.parse(calls()[0]![1].body)).toEqual({ query: "trim me", top_k: 5, min_score: null });
  expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/members"))).toHaveLength(2);
});
for (const top of ["1", "5", "20"])
  it(`accepts top_k ${top}`, async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Top K"), { target: { value: top } });
    await search();
    await screen.findByText("real retrieved text");
    expect(JSON.parse(calls()[0]![1].body).top_k).toBe(Number(top));
  });
for (const top of [
  "",
  "0",
  "21",
  "1.5",
  "1e1",
  "NaN",
  "Infinity",
  "-Infinity",
  "-1",
  "abc",
  "0x10",
])
  it(`rejects top_k ${top}`, async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Top K"), { target: { value: top } });
    await search();
    await screen.findByRole("alert");
    expect(calls()).toHaveLength(0);
  });
for (const min of ["", "-1", "0", "1", "0.5"])
  it(`accepts minimum similarity ${min}`, async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Minimum similarity (optional)"), {
      target: { value: min },
    });
    await search();
    await screen.findByText("real retrieved text");
    expect(JSON.parse(calls()[0]![1].body).min_score).toBe(min === "" ? null : Number(min));
  });
for (const min of ["NaN", "Infinity", "-Infinity", "1.01", "-1.01", "abc", "0x0"])
  it(`rejects minimum similarity ${min}`, async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Minimum similarity (optional)"), {
      target: { value: min },
    });
    await search();
    await screen.findByRole("alert");
    expect(calls()).toHaveLength(0);
  });
for (const mode of ["search", "ask"])
  for (const value of ["", "   ", "\u0085\u001c", "😀".repeat(2001)])
    it(`rejects ${mode} input ${value.length}`, async () => {
      await ready();
      if (mode === "search") await search(value);
      else await ask(value);
      await screen.findByRole("alert");
      expect(calls(mode)).toHaveLength(0);
    });
for (const mode of ["search", "ask"])
  it(`accepts 2000 Unicode code points for ${mode}`, async () => {
    await ready();
    const value = "😀".repeat(2000);
    if (mode === "search") await search(`\u0085${value}\u001c`);
    else await ask(`\u0085${value}\u001c`);
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    expect(JSON.parse(calls(mode)[0]![1].body)[mode === "search" ? "query" : "question"]).toBe(
      value,
    );
  });
it("preserves Python-significant FEFF in a query", async () => {
  await ready();
  await search("\ufeff");
  await waitFor(() => expect(calls()).toHaveLength(1));
  expect(JSON.parse(calls()[0]![1].body).query).toBe("\ufeff");
});
it("renders actual query/model and ordered result metadata without turning similarity into confidence", async () => {
  const item = result().results[0]!;
  searchResult = result({
    total: 2,
    results: [
      item,
      { ...item, chunk_id: "second-chunk", filename: "second.txt", similarity_score: 0.99 },
    ],
  });
  await ready();
  await search();
  const results = await screen.findByRole("region", { name: "Search results" });
  for (const value of [
    "Actual query: actual query",
    "Embedding model: model-real",
    "2 results shown",
  ])
    expect(within(results).getByText(value)).toBeInTheDocument();
  const first = results.querySelector("article")!;
  for (const value of ["document-real", "chunk-real", "7", "100", "200", "0.75", "2", "3"])
    expect(within(first).getByText(value)).toBeInTheDocument();
  expect([...results.querySelectorAll("article")].map((node) => node.textContent)).toEqual([
    expect.stringContaining("chunk-real"),
    expect.stringContaining("second-chunk"),
  ]);
  expect(results.textContent).not.toContain("75%");
});
it("shows normal empty results without claiming indexes are absent or starting a job", async () => {
  searchResult = result({ results: [], total: 0 });
  await ready();
  await search();
  await screen.findByText("No matching results");
  expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/index"))).toBe(false);
});
it("hides foreign knowledge base results without reordering safe rows", async () => {
  searchResult = result({
    results: [
      { ...result().results[0]!, knowledge_base_id: "foreign", filename: "foreign-private.txt" },
      result().results[0]!,
    ],
    total: 2,
  });
  await ready();
  await search();
  await screen.findByText("real retrieved text");
  expect(screen.queryByText("foreign-private.txt")).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "Search results" })).getByRole("alert"),
  ).toHaveTextContent(messages.knowledgeManagement.scopeError);
});
it("renders search HTML and Markdown as inert text", async () => {
  searchResult.results[0]!.filename = "<img src=x onerror=alert(1)>";
  searchResult.results[0]!.content = "<script>alert(1)</script> ![x](https://evil.test/img)";
  await ready();
  await search();
  await screen.findByText(searchResult.results[0]!.content);
  const region = screen.getByRole("region", { name: "Search results" });
  expect(region.querySelector("img,script,iframe,a")).toBeNull();
});
it("bounds long retrieved text and identifies display truncation", async () => {
  searchResult.results[0]!.content = "😀".repeat(PLAYGROUND_TEXT_LIMIT + 1);
  await ready();
  await search();
  await screen.findByText(/Partial display/);
  expect(Array.from(document.querySelector("pre")!.textContent!)).toHaveLength(
    PLAYGROUND_TEXT_LIMIT,
  );
});
it("renders a standalone answer with only actual backend sources", async () => {
  await ready();
  await ask("  Question?  ");
  const region = await screen.findByRole("region", { name: "Answer" });
  expect(JSON.parse(calls("ask")[0]![1].body)).toEqual({ question: "Question?" });
  for (const value of [
    "Grounded answer",
    "Source.txt",
    "source-document",
    "source-chunk",
    "4",
    "5",
    "0.8",
  ])
    expect(within(region).getByText(value)).toBeInTheDocument();
  expect(region.querySelector("a")).toBeNull();
});
it("localizes no_evidence as a successful non-error response", async () => {
  askResult = answer({ status: "no_evidence", answer: "raw server English", sources: [] });
  await ready();
  await ask();
  await screen.findByText(messages.knowledgeManagement.playground.noEvidence);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText("raw server English")).not.toBeInTheDocument();
});
it("never infers citations from answer text when no sources exist", async () => {
  askResult = answer({
    answer: "According to [1](javascript:evil), see invented.pdf",
    sources: [],
  });
  await ready();
  await ask();
  const region = await screen.findByRole("region", { name: "Answer" });
  expect(
    within(region).getByText(messages.knowledgeManagement.playground.noSources),
  ).toBeInTheDocument();
  expect(region.querySelector("a")).toBeNull();
  expect(region.querySelectorAll("article")).toHaveLength(0);
});
it("renders malicious answer/source text inertly and bounds long answers", async () => {
  askResult = answer({
    answer: "<script>alert(1)</script>" + "x".repeat(PLAYGROUND_TEXT_LIMIT),
    sources: [{ ...answer().sources[0]!, filename: "<img src=https://evil.test/i>" }],
  });
  await ready();
  await ask();
  const region = await screen.findByRole("region", { name: "Answer" });
  expect(region.querySelector("script,img,iframe,a")).toBeNull();
  expect(region.querySelector("pre")!.textContent).toHaveLength(PLAYGROUND_TEXT_LIMIT);
  expect(within(region).getByText(/Partial display/)).toBeInTheDocument();
});
for (const level of ["owner", "admin", "member"])
  for (const mode of ["search", "ask"])
    it(`permits ${level} to ${mode} using fresh read authorization`, async () => {
      role = level;
      await ready();
      if (mode === "search") await search();
      else await ask();
      await waitFor(() => expect(calls(mode)).toHaveLength(1));
      expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/members"))).toHaveLength(2);
    });
for (const code of PLAYGROUND_CODES)
  it(`maps safe error ${code}`, async () => {
    overrides.set(`POST ${askPath}`, () =>
      Response.json(
        { error: { code }, detail: "private/token/stack/provider-url" },
        { status: 503 },
      ),
    );
    await ready();
    await ask();
    await screen.findByText(messages.knowledgeManagement.playground.errors[code]);
    expect(screen.queryByText("private/token/stack/provider-url")).not.toBeInTheDocument();
    expect(calls("ask")).toHaveLength(1);
  });
for (const http of [409, 422, 500])
  it(`shows safe HTTP ${http} and supports explicit retry`, async () => {
    overrides.set(`POST ${searchPath}`, () =>
      Response.json({ detail: "private/secret" }, { status: http }),
    );
    await ready();
    await search();
    await screen.findByText("Unable to complete this request");
    expect(screen.queryByText("private/secret")).not.toBeInTheDocument();
    overrides.delete(`POST ${searchPath}`);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("real retrieved text");
    expect(calls()).toHaveLength(2);
  });
it("handles network errors safely without automatic retry", async () => {
  overrides.set(`POST ${searchPath}`, () => Promise.reject(new TypeError("private internal URL")));
  await ready();
  await search();
  await screen.findByText("Unable to complete this request");
  expect(screen.queryByText("private internal URL")).not.toBeInTheDocument();
  expect(calls()).toHaveLength(1);
});
for (const mode of ["search", "ask"])
  it(`coalesces fast duplicate ${mode} submissions`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
    await ready();
    if (mode === "ask") await userEvent.click(screen.getByRole("tab", { name: "Ask knowledge" }));
    fireEvent.change(screen.getByLabelText(mode === "search" ? "Query" : "Question"), {
      target: { value: "same input" },
    });
    const button = screen.getByRole("button", {
      name: mode === "search" ? "Search knowledge" : "Ask knowledge",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    await act(async () => pending.resolve(Response.json(mode === "search" ? result() : answer())));
    expect(calls(mode)).toHaveLength(1);
  });
for (const mode of ["search", "ask"])
  it(`uses latest-wins for ${mode}`, async () => {
    const first = deferred<Response>();
    let n = 0;
    overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () =>
      ++n === 1
        ? first.promise
        : Response.json(
            mode === "search"
              ? result({
                  query: "new",
                  results: [{ ...result().results[0]!, content: "new latest search" }],
                })
              : answer({ answer: "new latest answer" }),
          ),
    );
    await ready();
    if (mode === "ask") await userEvent.click(screen.getByRole("tab", { name: "Ask knowledge" }));
    const field = screen.getByLabelText(mode === "search" ? "Query" : "Question"),
      button = screen.getByRole("button", {
        name: mode === "search" ? "Search knowledge" : "Ask knowledge",
      });
    fireEvent.change(field, { target: { value: "old input" } });
    fireEvent.click(button);
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    fireEvent.change(field, { target: { value: "new input" } });
    fireEvent.click(button);
    await screen.findByText(mode === "search" ? "new latest search" : "new latest answer");
    expect(calls(mode)[0]![1].signal.aborted).toBe(true);
    await act(async () =>
      first.resolve(
        Response.json(
          mode === "search"
            ? result({ results: [{ ...result().results[0]!, content: "stale private search" }] })
            : answer({ answer: "stale private answer" }),
        ),
      ),
    );
    expect(screen.queryByText(/stale private/)).not.toBeInTheDocument();
  });
for (const mode of ["search", "ask"])
  it(`cancels pending ${mode} without a business error`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
    await ready();
    if (mode === "search") await search();
    else await ask();
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(calls(mode)[0]![1].signal.aborted).toBe(true);
    await act(async () => pending.resolve(Response.json(mode === "search" ? result() : answer())));
    expect(
      screen.queryByRole("region", { name: mode === "search" ? "Search results" : "Answer" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Unable to complete this request")).not.toBeInTheDocument();
  });
for (const mode of ["search", "ask"])
  it(`cancels old ${mode} when switching modes and preserves separate drafts`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
    await ready();
    if (mode === "search") await search("search draft");
    else await ask("ask draft");
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    await userEvent.click(
      screen.getByRole("tab", { name: mode === "search" ? "Ask knowledge" : "Search knowledge" }),
    );
    await act(async () => pending.resolve(Response.json(mode === "search" ? result() : answer())));
    expect(
      screen.queryByRole("region", { name: mode === "search" ? "Search results" : "Answer" }),
    ).not.toBeInTheDocument();
    expect(calls(mode)[0]![1].signal.aborted).toBe(true);
    await userEvent.click(
      screen.getByRole("tab", { name: mode === "search" ? "Search knowledge" : "Ask knowledge" }),
    );
    expect(screen.getByLabelText(mode === "search" ? "Query" : "Question")).toHaveValue(
      mode === "search" ? "search draft" : "ask draft",
    );
    expect(
      screen.queryByRole("region", { name: mode === "search" ? "Search results" : "Answer" }),
    ).not.toBeInTheDocument();
  });
for (const mode of ["search", "ask"])
  for (const reason of [
    "workspace",
    "base",
    "logout",
    "account",
    "same-user",
    "base-delete",
    "workspace-loss",
  ])
    it(`isolates delayed ${mode} after ${reason}`, async () => {
      const pending = deferred<Response>();
      overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
      const view = await ready();
      if (mode === "search") await search();
      else await ask();
      await waitFor(() => expect(calls(mode)).toHaveLength(1));
      if (reason === "workspace" || reason === "base") {
        if (reason === "workspace") route.search = "workspace_id=w2";
        view.change("kb2");
        await screen.findByLabelText("Query");
        expect(queryInput()).toHaveValue("");
      } else
        await act(async () => {
          if (reason === "base-delete")
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
      await act(async () =>
        pending.resolve(
          Response.json(
            mode === "search"
              ? result({ results: [{ ...result().results[0]!, content: "late private search" }] })
              : answer({ answer: "late private answer" }),
          ),
        ),
      );
      expect(screen.queryByText(/late private/)).not.toBeInTheDocument();
      expect(calls(mode)[0]![1].signal.aborted).toBe(true);
      expect(route.push).not.toHaveBeenCalled();
    });
for (const mode of ["search", "ask"])
  for (const http of [403, 404])
    it(`suppresses old ${mode} ${http} error after a new scope opens`, async () => {
      const pending = deferred<Response>();
      overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
      const view = await ready();
      if (mode === "search") await search();
      else await ask();
      await waitFor(() => expect(calls(mode)).toHaveLength(1));
      view.change("kb2");
      await screen.findByLabelText("Query");
      fill("new draft");
      await act(async () =>
        pending.resolve(Response.json({ detail: "stale sensitive error" }, { status: http })),
      );
      expect(queryInput()).toHaveValue("new draft");
      expect(screen.queryByText("Unable to complete this request")).not.toBeInTheDocument();
      expect(route.push).not.toHaveBeenCalled();
    });
it("keeps requests blocked while membership is pending", async () => {
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  mount();
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("members"))).toBe(true),
  );
  expect(screen.queryByLabelText("Query")).not.toBeInTheDocument();
  expect(calls()).toHaveLength(0);
  expect(calls("ask")).toHaveLength(0);
});
it("does not mount playground when membership fails", async () => {
  overrides.set("GET /api/workspaces/w1/members", () =>
    Response.json({ detail: "secret" }, { status: 500 }),
  );
  mount();
  await screen.findByText(messages.knowledgeManagement.errors.membership);
  expect(screen.queryByLabelText("Query")).not.toBeInTheDocument();
});
it("does not mount playground before base verification or for a mismatched base", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${basePath}`, () => pending.promise);
  mount();
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u]) => String(u) === basePath)).toBe(true),
  );
  expect(screen.queryByLabelText("Query")).not.toBeInTheDocument();
  await act(async () => pending.resolve(Response.json({ id: "wrong", workspace_id: "w1" })));
  await screen.findByText(messages.knowledgeManagement.scopeError);
  expect(screen.queryByLabelText("Query")).not.toBeInTheDocument();
});
it("rechecks read membership before issuing a POST and fails closed if revoked", async () => {
  await ready();
  role = "missing";
  await search();
  await waitFor(() => expect(screen.queryByLabelText("Query")).not.toBeInTheDocument());
  expect(calls()).toHaveLength(0);
});
for (const http of [403, 404])
  it(`handles current ${http} without removing another workspace`, async () => {
    await ready();
    const foreign = qk.knowledge.base("a", "w2", "kb2");
    client.setQueryData(foreign, { keep: true });
    overrides.set(`POST ${searchPath}`, () =>
      Response.json({ detail: "private scope" }, { status: http }),
    );
    await search();
    await waitFor(() => expect(calls()).toHaveLength(1));
    await waitFor(() =>
      expect(
        screen.queryByText("Verifying access and processing your request…"),
      ).not.toBeInTheDocument(),
    );
    expect(client.getQueryData(foreign)).toEqual({ keep: true });
    expect(screen.queryByText("private scope")).not.toBeInTheDocument();
    if (http === 403)
      expect(
        fetchMock.mock.calls.filter(([u]) => String(u).endsWith("members")).length,
      ).toBeGreaterThan(2);
  });
it("coalesces a shared read preflight while latest query replaces an earlier intent", async () => {
  await ready();
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  fill("old");
  fireEvent.click(screen.getByRole("button", { name: "Search knowledge" }));
  fill("new");
  fireEvent.click(screen.getByRole("button", { name: "Search knowledge" }));
  expect(calls()).toHaveLength(0);
  await act(async () =>
    pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "member" }])),
  );
  await waitFor(() => expect(calls()).toHaveLength(1));
  expect(JSON.parse(calls()[0]![1].body).query).toBe("new");
});
it("works under StrictMode without automatic Search or Ask", async () => {
  render(
    <StrictMode>
      <KnowledgeManagement userId="a" knowledgeBaseId="kb1" />
    </StrictMode>,
    { wrapper },
  );
  await screen.findByLabelText("Query");
  expect(calls()).toHaveLength(0);
  expect(calls("ask")).toHaveLength(0);
  await search();
  await screen.findByText("real retrieved text");
});
it("keeps en/pl playground translation keys in parity", () => {
  const keys = (v: object): string[] =>
    Object.entries(v)
      .flatMap(([k, v]) => (typeof v === "object" ? keys(v).map((x) => `${k}.${x}`) : [k]))
      .sort();
  expect(keys(messages.knowledgeManagement.playground)).toEqual(
    keys(polish.knowledgeManagement.playground),
  );
});

it("uses the existing authenticated refresh retry on a current 401", async () => {
  let n = 0;
  overrides.set(`POST ${searchPath}`, () =>
    ++n === 1 ? Response.json({ detail: "private" }, { status: 401 }) : Response.json(result()),
  );
  overrides.set("POST /api/auth/refresh", () => Response.json({ access_token: "refreshed-token" }));
  await ready();
  await search();
  await screen.findByText("real retrieved text");
  expect(calls()).toHaveLength(2);
  expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(1);
  expect(useAuthStore.getState().user?.id).toBe("a");
});
it("shows a safe 401 when the existing authentication refresh fails", async () => {
  overrides.set(`POST ${searchPath}`, () => Response.json({ detail: "private" }, { status: 401 }));
  overrides.set("POST /api/auth/refresh", () => Response.json({}, { status: 401 }));
  await ready();
  await search();
  await screen.findByText(messages.knowledgeManagement.errors.unauthorized);
  expect(calls()).toHaveLength(1);
  expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(1);
});
for (const mode of ["search", "ask"])
  it(`does not let stale ${mode} 401 refresh the new identity`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${mode === "search" ? searchPath : askPath}`, () => pending.promise);
    const view = await ready();
    if (mode === "search") await search();
    else await ask();
    await waitFor(() => expect(calls(mode)).toHaveLength(1));
    await act(async () => {
      useAuthStore.getState().logout();
      useAuthStore.getState().setUser(B);
      view.change("kb1", "b");
    });
    await screen.findByLabelText("Query");
    await act(async () =>
      pending.resolve(Response.json({ detail: "old unauthorized" }, { status: 401 })),
    );
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/refresh"))).toBe(false);
    expect(calls(mode)).toHaveLength(1);
    expect(useAuthStore.getState().user?.id).toBe("b");
  });
it("does not expose an unknown backend error code", async () => {
  overrides.set(`POST ${searchPath}`, () =>
    Response.json(
      { error: { code: "PRIVATE_TOKEN_IN_ERROR" }, detail: "secret provider URL" },
      { status: 500 },
    ),
  );
  await ready();
  await search();
  await screen.findByText("Unable to complete this request");
  expect(screen.queryByText("PRIVATE_TOKEN_IN_ERROR")).not.toBeInTheDocument();
  expect(screen.queryByText("secret provider URL")).not.toBeInTheDocument();
});
it("cancels during permission preflight without later issuing a Search", async () => {
  await ready();
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  await search();
  await screen.findByText("Verifying access and processing your request…");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await act(async () =>
    pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "member" }])),
  );
  expect(calls()).toHaveLength(0);
  expect(screen.queryByText("Unable to complete this request")).not.toBeInTheDocument();
});
it("does not revive a cleared base after delayed permission success", async () => {
  await ready();
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  await search();
  await screen.findByText("Verifying access and processing your request…");
  await act(async () => clearKnowledgeScope(client, qk.knowledge.base("a", "w1", "kb1")));
  await act(async () =>
    pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "owner" }])),
  );
  expect(calls()).toHaveLength(0);
  expect(screen.queryByLabelText("Query")).not.toBeInTheDocument();
});
it("localizes unknown Ask response states without creating an answer", async () => {
  askResult = { ...answer(), status: "unexpected" as "answered" };
  await ready();
  await ask();
  await screen.findByText(messages.knowledgeManagement.playground.invalidResponse);
  expect(screen.queryByRole("region", { name: "Answer" })).not.toBeInTheDocument();
});
