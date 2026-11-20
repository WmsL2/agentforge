import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { useAuthStore } from "@/stores/auth-store";
import { bindKnowledgeLifecycle } from "@/lib/knowledge/knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import type { KnowledgeBaseRead, User, WorkspaceRead, WorkspaceRole } from "@/types";
import KnowledgeListPage from "@/app/[locale]/(dashboard)/knowledge/page";
import KnowledgeDetailPage from "@/app/[locale]/(dashboard)/knowledge/[knowledgeBaseId]/page";
import { KnowledgeManagement } from "./knowledge-management";
const route = vi.hoisted(() => ({
  pathname: "/knowledge",
  search: "workspace_id=w1",
  push: vi.fn(),
  replace: vi.fn(),
  toast: vi.fn(),
}));
vi.mock("@/hooks", async () => {
  const { useAuthStore } = await import("@/stores/auth-store");
  return { useAuth: () => useAuthStore() };
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ knowledgeBaseId: "kb1" }),
  usePathname: () => route.pathname,
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ push: route.push, replace: route.replace }),
}));
vi.mock("sonner", () => ({ toast: { error: route.toast } }));
const A: User = {
  id: "a",
  email: "a@test",
  is_active: true,
  role: "admin",
  created_at: "2026-11-20",
};
const B: User = { ...A, id: "b", email: "b@test" };
const W: WorkspaceRead[] = [
  {
    id: "w1",
    name: "Workspace One",
    created_by_user_id: "a",
    created_at: "2026-11-20",
    updated_at: null,
  },
  {
    id: "w2",
    name: "Workspace Two",
    created_by_user_id: "a",
    created_at: "2026-11-20",
    updated_at: null,
  },
];
const base = (id = "kb1", w = "w1", name = "Real knowledge"): KnowledgeBaseRead => ({
  id,
  workspace_id: w,
  name,
  description: "Actual description",
  created_by_user_id: "a",
  created_at: "2026-11-20T12:00:00Z",
  updated_at: null,
});
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
let client: QueryClient,
  unbind: () => void,
  workspaces: WorkspaceRead[],
  roles: Record<string, WorkspaceRole | "missing">,
  database: Record<string, KnowledgeBaseRead[]>;
const fetchMock = vi.fn();
let overrides: Map<string, () => Promise<Response> | Response>;
function response(url: string, options: RequestInit = {}) {
  const parsed = new URL(url, "https://app.test"),
    path = parsed.pathname,
    method = options.method ?? "GET";
  const custom = overrides.get(`${method} ${path}`);
  if (custom) return custom();
  if (path === "/api/workspaces") return Response.json({ items: workspaces });
  const parts = path.split("/");
  const w = parts[3]!;
  if (parts[4] === "members")
    return Response.json(
      roles[w] === "missing"
        ? []
        : [
            {
              workspace_id: w,
              user_id: useAuthStore.getState().user!.id,
              role: roles[w],
              created_at: "2026-11-20",
              updated_at: null,
            },
          ],
    );
  if (parts.length === 4)
    return workspaces.some((item) => item.id === w)
      ? Response.json(W.find((item) => item.id === w))
      : Response.json({ detail: "absent" }, { status: 404 });
  if (parts[4] !== "knowledge-bases") throw new Error(`Unexpected test URL ${url}`);
  const items = database[w] ?? [],
    id = parts[5];
  if (method === "GET" && !id) {
    const skip = Number(parsed.searchParams.get("skip") ?? 0),
      limit = Number(parsed.searchParams.get("limit") ?? 50);
    return Response.json({ items: items.slice(skip, skip + limit), total: items.length });
  }
  const payload = options.body ? JSON.parse(String(options.body)) : {};
  if (method === "POST") {
    const created = { ...base("new", w), ...payload };
    database[w] = [...items, created];
    return Response.json(created, { status: 201 });
  }
  const found = items.find((item) => item.id === id);
  if (!found) return Response.json({ detail: "absent" }, { status: 404 });
  if (method === "PATCH") {
    const updated = { ...found, ...payload };
    database[w] = items.map((item) => (item.id === id ? updated : item));
    return Response.json(updated);
  }
  if (method === "DELETE") {
    database[w] = items.filter((item) => item.id !== id);
    return new Response(null, { status: 204 });
  }
  return Response.json(found);
}
function mount(detail?: string, locale = "en", userId = "a") {
  const element = (id = userId) => (
    <NextIntlClientProvider
      locale={locale}
      messages={{
        knowledgeManagement: (locale === "pl" ? polish : messages).knowledgeManagement,
        common: messages.common,
      }}
    >
      <QueryClientProvider client={client}>
        <KnowledgeManagement userId={id} knowledgeBaseId={detail} />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
  const view = render(element());
  return { ...view, refresh: (id = userId) => view.rerender(element(id)) };
}
const kbCalls = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("knowledge-bases"));
const writes = () => kbCalls().filter(([, opts]) => opts.method !== "GET");
async function ready() {
  await screen.findByRole("link", { name: "Real knowledge" });
}
async function createDialog() {
  await ready();
  await userEvent.click(screen.getByRole("button", { name: "Create knowledge base" }));
  return screen.getByRole("dialog");
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
  workspaces = [...W];
  roles = { w1: "owner", w2: "owner" };
  database = { w1: [base()], w2: [base("kb2", "w2", "Other workspace secret")] };
  overrides = new Map();
  route.pathname = "/knowledge";
  route.search = "workspace_id=w1";
  route.push.mockReset();
  route.replace.mockReset();
  route.toast.mockReset();
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
it("loads real scoped data with server pagination and navigates to scoped detail", async () => {
  mount();
  await ready();
  expect(screen.getByText("Actual description")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Real knowledge" })).toHaveAttribute(
    "href",
    "/knowledge/kb1?workspace_id=w1",
  );
  expect(kbCalls()[0]![0]).toBe("/api/workspaces/w1/knowledge-bases?skip=0&limit=10");
  expect(screen.getByText("1 knowledge bases")).toBeInTheDocument();
});
it.each(["", "workspace_id=not-authorized"])(
  "recovers list selection from %s without requesting untrusted scope",
  async (search) => {
    route.search = search;
    mount();
    await ready();
    expect(route.replace).toHaveBeenCalledWith("/knowledge?workspace_id=w1");
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("not-authorized/"))).toBe(
      true,
    );
  },
);
it("shows no-workspace state and a localized Workflows entry", async () => {
  workspaces = [];
  route.pathname = "/pl/knowledge";
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Open Workflows" }));
  expect(route.push).toHaveBeenCalledWith("/pl/workflows");
  expect(kbCalls()).toHaveLength(0);
});
it("handles workspace failure and retries safely", async () => {
  overrides.set("GET /api/workspaces", () =>
    Response.json({ detail: "secret token internal://url" }, { status: 503 }),
  );
  mount();
  await screen.findByText("Unable to load workspaces");
  expect(screen.queryByText(/internal:/)).not.toBeInTheDocument();
  overrides.delete("GET /api/workspaces");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await ready();
});
it.each(["owner", "admin"] as const)("allows %s CRUD", async (role) => {
  roles.w1 = role;
  mount();
  await ready();
  expect(screen.getByRole("button", { name: "Create knowledge base" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Edit Real knowledge" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Delete Real knowledge" })).toBeEnabled();
});
it("App Admin and workspace creator do not override Member read-only role", async () => {
  roles.w1 = "member";
  mount();
  await ready();
  expect(screen.getByText("Read-only workspace access")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Create|Edit|Delete/ })).not.toBeInTheDocument();
});
it("does not grant writes from stale cached Admin while membership revalidation is pending", async () => {
  client.setQueryData(qk.workspaces.members("a", "w1"), [
    { workspace_id: "w1", user_id: "a", role: "admin" },
  ]);
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  roles.w1 = "member";
  mount();
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/workspaces/w1/members")).toBe(true),
  );
  expect(kbCalls()).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
  pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "member" }]));
  await ready();
  expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
});
it("fails closed on membership error and retry", async () => {
  overrides.set("GET /api/workspaces/w1/members", () =>
    Response.json({ detail: "secret" }, { status: 500 }),
  );
  mount();
  await screen.findByText("Unable to verify workspace membership");
  expect(kbCalls()).toHaveLength(0);
  overrides.delete("GET /api/workspaces/w1/members");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await ready();
});
it.each(["missing", 403, 404])(
  "clears confirmed lost workspace and hides cached knowledge: %s",
  async (reason) => {
    workspaces = [W[0]!];
    client.setQueryData(qk.knowledge.content("a", "w1", "kb1", "d"), "secret");
    if (reason === "missing") roles.w1 = "missing";
    else
      overrides.set("GET /api/workspaces/w1/members", () =>
        Response.json({ detail: "denied" }, { status: Number(reason) }),
      );
    mount();
    await screen.findByText("Workspace access is no longer available.");
    await waitFor(() =>
      expect(client.getQueryData(qk.knowledge.content("a", "w1", "kb1", "d"))).toBeUndefined(),
    );
    expect(kbCalls()).toHaveLength(0);
    expect(screen.queryByText("Real knowledge")).not.toBeInTheDocument();
  },
);
it("creates trimmed name from real success and updates list", async () => {
  mount();
  const dialog = await createDialog();
  await userEvent.type(within(dialog).getByLabelText("Name"), "  New base  ");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await screen.findByRole("link", { name: "New base" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(JSON.parse(writes()[0]![1].body)).toEqual({ name: "New base", description: null });
});
it("retains create values on failure and never exposes backend details", async () => {
  overrides.set("POST /api/workspaces/w1/knowledge-bases", () =>
    Response.json({ error: { message: "token private://stack" } }, { status: 422 }),
  );
  mount();
  const dialog = await createDialog();
  await userEvent.type(within(dialog).getByLabelText("Name"), "Keep me");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Name")).toHaveValue("Keep me");
  expect(screen.queryByText(/private:/)).not.toBeInTheDocument();
  expect(database.w1).toHaveLength(1);
});
it.each(["   ", "x".repeat(256)])("validates name before submitting: %s", async (value) => {
  mount();
  const dialog = await createDialog();
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value } });
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  expect(writes()).toHaveLength(0);
});
it("prevents duplicate submissions while request is pending", async () => {
  const pending = deferred<Response>();
  overrides.set("POST /api/workspaces/w1/knowledge-bases", () => pending.promise);
  mount();
  const dialog = await createDialog();
  await userEvent.type(within(dialog).getByLabelText("Name"), "Once");
  const save = within(dialog).getByRole("button", { name: "Save" });
  fireEvent.click(save);
  fireEvent.click(save);
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(save).toBeDisabled();
  pending.resolve(Response.json(base("new", "w1", "Once"), { status: 201 }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("edits real initial values and sends explicit null to clear description", async () => {
  mount();
  await ready();
  await userEvent.click(screen.getByRole("button", { name: "Edit Real knowledge" }));
  expect(screen.getByLabelText("Name")).toHaveValue("Real knowledge");
  await userEvent.clear(screen.getByLabelText("Description"));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(JSON.parse(writes()[0]![1].body)).toEqual({ name: "Real knowledge", description: null });
  await screen.findByText("No description");
});
it("keeps edit input on conflict", async () => {
  overrides.set("PATCH /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json({ detail: "conflict" }, { status: 409 }),
  );
  mount();
  await ready();
  await userEvent.click(screen.getByRole("button", { name: "Edit Real knowledge" }));
  await userEvent.clear(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Changed");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Name")).toHaveValue("Changed");
});
it("delete requires confirmation, cancel does not send, success clears child cache", async () => {
  mount();
  await ready();
  const key = qk.knowledge.content("a", "w1", "kb1", "d");
  client.setQueryData(key, "private");
  await userEvent.click(screen.getByRole("button", { name: "Delete Real knowledge" }));
  expect(writes()).toHaveLength(0);
  expect(screen.getByText(/also affects its documents and indexes/)).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(writes()).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Delete Real knowledge" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  await screen.findByText("No knowledge bases yet");
  expect(client.getQueryData(key)).toBeUndefined();
});
it("preserves delete confirmation on service failure", async () => {
  overrides.set("DELETE /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json({ detail: "private" }, { status: 503 }),
  );
  mount();
  await ready();
  await userEvent.click(screen.getByRole("button", { name: "Delete Real knowledge" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(database.w1).toHaveLength(1);
});
it("paginates and returns to a valid page after deleting its last row", async () => {
  database.w1 = Array.from({ length: 11 }, (_, i) => base(`kb${i}`, "w1", `Base ${i}`));
  mount();
  await screen.findByRole("link", { name: "Base 0" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("link", { name: "Base 10" });
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Delete Base 10" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  await screen.findByRole("link", { name: "Base 0" });
  expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
});
it("closes write dialog on permission revalidation/downgrade", async () => {
  mount();
  await createDialog();
  roles.w1 = "member";
  await act(() => client.refetchQueries({ queryKey: qk.workspaces.members("a", "w1") }));
  await ready();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
  expect(writes()).toHaveLength(0);
});
it("403 revalidates membership, closes write dialog and shows safe error", async () => {
  overrides.set("POST /api/workspaces/w1/knowledge-bases", () => {
    roles.w1 = "member";
    return Response.json(
      { error: { code: "WORKSPACE_PERMISSION_DENIED", message: "secret" } },
      { status: 403 },
    );
  });
  mount();
  const dialog = await createDialog();
  await userEvent.type(within(dialog).getByLabelText("Name"), "Denied");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(route.toast).toHaveBeenCalledWith("You do not have permission to perform this action."),
  );
  await ready();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
});
it("switches workspace with selector, resets pagination and hides prior content", async () => {
  mount();
  await ready();
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: "Workspace Two" }));
  expect(route.push).toHaveBeenCalledWith("/knowledge?workspace_id=w2");
});
it.each(["success", "failure"])(
  "old create %s cannot close a new workspace's dialog or emit toast",
  async (outcome) => {
    const pending = deferred<Response>();
    overrides.set("POST /api/workspaces/w1/knowledge-bases", () => pending.promise);
    const view = mount();
    const dialog = await createDialog();
    await userEvent.type(within(dialog).getByLabelText("Name"), "Old");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    route.search = "workspace_id=w2";
    view.refresh();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Real knowledge")).not.toBeInTheDocument();
    await screen.findByRole("link", { name: "Other workspace secret" });
    await userEvent.click(screen.getByRole("button", { name: "Create knowledge base" }));
    await userEvent.type(screen.getByLabelText("Name"), "New input");
    await act(async () => {
      pending.resolve(
        Response.json(outcome === "success" ? base("late") : { detail: "private" }, {
          status: outcome === "success" ? 201 : 500,
        }),
      );
      await pending.promise;
    });
    expect(screen.getByLabelText("Name")).toHaveValue("New input");
    expect(route.toast).not.toHaveBeenCalled();
    expect(route.push).not.toHaveBeenCalled();
  },
);
it.each(["logout", "switch", "same-user"])(
  "isolates completed dialog and cached role after %s",
  async (mode) => {
    const view = mount();
    await createDialog();
    await userEvent.type(screen.getByLabelText("Name"), "Old private input");
    act(() => useAuthStore.getState().logout());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Real knowledge")).not.toBeInTheDocument();
    if (mode !== "logout") {
      roles.w1 = "member";
      act(() => useAuthStore.getState().setUser(mode === "switch" ? B : A));
      view.refresh(mode === "switch" ? "b" : "a");
      await ready();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Create knowledge base" }),
      ).not.toBeInTheDocument();
    }
  },
);
it("does not render when supplied user differs from current identity", () => {
  mount(undefined, "en", "b");
  expect(fetchMock).not.toHaveBeenCalled();
});
it("renders localized list and preserves locale in detail links", async () => {
  route.pathname = "/pl/knowledge";
  mount(undefined, "pl");
  await ready();
  expect(screen.getByText("Bazy wiedzy")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Real knowledge" })).toHaveAttribute(
    "href",
    "/pl/knowledge/kb1?workspace_id=w1",
  );
});
it("detail shows actual metadata and localized back navigation", async () => {
  route.pathname = "/pl/knowledge/kb1";
  mount("kb1");
  await screen.findByRole("heading", { name: "Real knowledge" });
  expect(screen.getByText("kb1")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to knowledge bases" })).toHaveAttribute(
    "href",
    "/pl/knowledge?workspace_id=w1",
  );
  expect(kbCalls()[0]![0]).toBe("/api/workspaces/w1/knowledge-bases/kb1");
});
it.each(["", "workspace_id=unauthorized"])(
  "detail rejects missing/invalid workspace: %s",
  async (search) => {
    route.search = search;
    mount("kb1");
    await screen.findByText("Choose an accessible workspace from the knowledge base list.");
    expect(kbCalls()).toHaveLength(0);
  },
);
it("detail rejects mismatching returned resource scope", async () => {
  overrides.set("GET /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json(base("kb1", "w2", "Hidden wrong workspace")),
  );
  mount("kb1");
  await screen.findByText("Choose an accessible workspace from the knowledge base list.");
  expect(screen.queryByText("Hidden wrong workspace")).not.toBeInTheDocument();
});
it("single KB 404 preserves other workspace cache and supports retry", async () => {
  const key = qk.knowledge.content("a", "w2", "kb2", "d");
  client.setQueryData(key, "keep");
  overrides.set("GET /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json({ detail: "missing" }, { status: 404 }),
  );
  mount("kb1");
  await screen.findByText("This resource does not exist or is not accessible.");
  expect(client.getQueryData(key)).toBe("keep");
  overrides.delete("GET /api/workspaces/w1/knowledge-bases/kb1");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("heading", { name: "Real knowledge" });
});
it("detail edits then deletes and returns only to its scoped list", async () => {
  route.pathname = "/knowledge/kb1";
  mount("kb1");
  await screen.findByRole("heading", { name: "Real knowledge" });
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  await userEvent.clear(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Renamed");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
  await screen.findByRole("heading", { name: "Renamed" });
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(route.push).toHaveBeenCalledWith("/knowledge?workspace_id=w1"));
});
it("Member detail has no edit/delete controls", async () => {
  roles.w1 = "member";
  mount("kb1");
  await screen.findByRole("heading", { name: "Real knowledge" });
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
});

it.each(["membership", "knowledge"])(
  "late %s read cannot populate a new workspace",
  async (kind) => {
    const pending = deferred<Response>();
    const path =
      kind === "membership" ? "/api/workspaces/w1/members" : "/api/workspaces/w1/knowledge-bases";
    overrides.set(`GET ${path}`, () => pending.promise);
    roles.w2 = "member";
    const view = mount();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).split("?")[0] === path)).toBe(true),
    );
    const oldSignal = fetchMock.mock.calls.find(([url]) => String(url).split("?")[0] === path)![1]
      .signal as AbortSignal;
    route.search = "workspace_id=w2";
    view.refresh();
    expect(screen.queryByText("Real knowledge")).not.toBeInTheDocument();
    await screen.findByRole("link", { name: "Other workspace secret" });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => {
      pending.resolve(
        Response.json(
          kind === "membership"
            ? [{ workspace_id: "w1", user_id: "a", role: "admin" }]
            : { items: [base("late", "w1", "Late secret")], total: 1 },
        ),
      );
      await pending.promise;
    });
    expect(screen.queryByText("Late secret")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
  },
);
it.each(["switch", "same-user"])(
  "late membership cannot restore old Admin after %s",
  async (mode) => {
    const pending = deferred<Response>();
    overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
    const view = mount();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === "/api/workspaces/w1/members")).toBe(true),
    );
    act(() => useAuthStore.getState().logout());
    overrides.delete("GET /api/workspaces/w1/members");
    roles.w1 = "member";
    act(() => useAuthStore.getState().setUser(mode === "switch" ? B : A));
    view.refresh(mode === "switch" ? "b" : "a");
    await ready();
    await act(async () => {
      pending.resolve(Response.json([{ workspace_id: "w1", user_id: "a", role: "admin" }]));
      await pending.promise;
    });
    expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
    expect(screen.getByText("Read-only workspace access")).toBeInTheDocument();
  },
);
it("successful workspace-list revalidation clears only confirmed removed scope", async () => {
  const old = qk.knowledge.content("a", "w1", "kb1", "d"),
    other = qk.knowledge.content("a", "w2", "kb2", "d");
  client.setQueryData(old, "old secret");
  client.setQueryData(other, "keep");
  mount();
  await ready();
  workspaces = [W[1]!];
  await act(() => client.refetchQueries({ queryKey: qk.workspaces.list("a") }));
  await screen.findByRole("link", { name: "Other workspace secret" });
  expect(client.getQueryData(old)).toBeUndefined();
  expect(client.getQueryData(other)).toBe("keep");
  expect(screen.queryByRole("link", { name: "Real knowledge" })).not.toBeInTheDocument();
  expect(route.replace).toHaveBeenCalledWith("/knowledge?workspace_id=w2");
});
it("late detail deletion cannot navigate a newly selected workspace", async () => {
  const pending = deferred<Response>();
  overrides.set("DELETE /api/workspaces/w1/knowledge-bases/kb1", () => pending.promise);
  const view = mount("kb1");
  await screen.findByRole("heading", { name: "Real knowledge" });
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  route.search = "workspace_id=w2";
  view.refresh();
  await screen.findByText("This resource does not exist or is not accessible.");
  await act(async () => {
    pending.resolve(new Response(null, { status: 204 }));
    await pending.promise;
  });
  expect(route.push).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("renders untrusted names/descriptions as text", async () => {
  database.w1 = [
    { ...base(), name: "<img src=x onerror=alert(1)>", description: "<script>private()</script>" },
  ];
  mount();
  await screen.findByRole("link", { name: "<img src=x onerror=alert(1)>" });
  expect(screen.getByText("<script>private()</script>")).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(document.querySelector('img[src="x"]')).toBeNull();
});
it.each([401, 403, 409, 422, 500])(
  "shows safe read error %s and retries after access verification",
  async (status) => {
    overrides.set("GET /api/workspaces/w1/knowledge-bases", () =>
      Response.json({ detail: "secret private://stack" }, { status }),
    );
    if (status === 401)
      overrides.set("POST /api/auth/refresh", () =>
        Response.json({ detail: "expired" }, { status: 401 }),
      );
    mount();
    await screen.findByText("Unable to load knowledge bases");
    expect(screen.queryByRole("button", { name: "Create knowledge base" })).not.toBeInTheDocument();
    expect(screen.queryByText(/private:/)).not.toBeInTheDocument();
    overrides.delete("GET /api/workspaces/w1/knowledge-bases");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await ready();
  },
);

it("resets page to zero when moving to another authorized workspace", async () => {
  database.w1 = Array.from({ length: 11 }, (_, i) => base(`kb${i}`, "w1", `Page base ${i}`));
  const view = mount();
  await screen.findByRole("link", { name: "Page base 0" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("link", { name: "Page base 10" });
  route.search = "workspace_id=w2";
  view.refresh();
  expect(screen.queryByRole("link", { name: "Page base 10" })).not.toBeInTheDocument();
  await screen.findByRole("link", { name: "Other workspace secret" });
  expect(kbCalls().filter(([url]) => String(url).includes("/w2/"))[0]![0]).toBe(
    "/api/workspaces/w2/knowledge-bases?skip=0&limit=10",
  );
  expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
});
it.each(["logout", "switch", "same-user"])(
  "late mutation failure does not change UI after %s",
  async (mode) => {
    const pending = deferred<Response>();
    overrides.set("POST /api/workspaces/w1/knowledge-bases", () => pending.promise);
    const view = mount();
    const dialog = await createDialog();
    await userEvent.type(within(dialog).getByLabelText("Name"), "Old pending");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    act(() => useAuthStore.getState().logout());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    if (mode !== "logout") {
      act(() => useAuthStore.getState().setUser(mode === "switch" ? B : A));
      view.refresh(mode === "switch" ? "b" : "a");
      await ready();
      await userEvent.click(screen.getByRole("button", { name: "Create knowledge base" }));
      await userEvent.type(screen.getByLabelText("Name"), "Current private input");
    }
    await act(async () => {
      pending.resolve(Response.json({ detail: "old secret" }, { status: 500 }));
      await pending.promise;
    });
    expect(route.toast).not.toHaveBeenCalled();
    expect(route.push).not.toHaveBeenCalled();
    if (mode !== "logout")
      expect(screen.getByLabelText("Name")).toHaveValue("Current private input");
    else expect(screen.queryByText("Real knowledge")).not.toBeInTheDocument();
  },
);

it("does not fabricate a zero total while the first list response is pending", async () => {
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/knowledge-bases", () => pending.promise);
  mount();
  await waitFor(() => expect(kbCalls()).toHaveLength(1));
  expect(screen.queryByText("0 knowledge bases")).not.toBeInTheDocument();
  pending.resolve(Response.json({ items: [base()], total: 1 }));
  await ready();
  expect(screen.getByText("1 knowledge bases")).toBeInTheDocument();
});
it("initial authorized list removes inaccessible cached scopes without clearing another user", async () => {
  const old = qk.knowledge.content("a", "w1", "kb1", "d"),
    other = qk.knowledge.content("b", "w1", "kb1", "d");
  client.setQueryData(old, "old private");
  client.setQueryData(other, "other user");
  workspaces = [];
  mount();
  await screen.findByText("No accessible workspaces");
  expect(client.getQueryData(old)).toBeUndefined();
  expect(client.getQueryData(other)).toBe("other user");
});

it.each([KnowledgeListPage, KnowledgeDetailPage])(
  "page $name waits for authenticated identity verification",
  async (Page) => {
    route.pathname = Page === KnowledgeDetailPage ? "/knowledge/kb1" : "/knowledge";
    act(() => useAuthStore.getState().logout());
    render(
      <NextIntlClientProvider
        locale="en"
        messages={{ knowledgeManagement: messages.knowledgeManagement, common: messages.common }}
      >
        <QueryClientProvider client={client}>
          <Page />
        </QueryClientProvider>
      </NextIntlClientProvider>,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    act(() => {
      useAuthStore.getState().setUser(A);
      useAuthStore.getState().setLoading(true);
    });
    expect(fetchMock).not.toHaveBeenCalled();
    act(() => useAuthStore.getState().setLoading(false));
    if (Page === KnowledgeListPage) await ready();
    else await screen.findByRole("heading", { name: "Real knowledge" });
  },
);
