import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import polish from "../../../messages/pl.json";
import { useAuthStore } from "@/stores/auth-store";
import { bindKnowledgeLifecycle } from "@/lib/knowledge/knowledge-lifecycle";
import { clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import {
  prepareDocument,
  safeFilename,
  PREVIEW_CHAR_LIMIT,
  MAX_DOCUMENT_BYTES,
  DOCUMENT_CODES,
} from "./knowledge-document-utils";
import type { KnowledgeDocumentRead } from "@/types";
import { qk } from "@/lib/query-keys";
import type { KnowledgeBaseRead, User, WorkspaceRead, WorkspaceRole } from "@/types";
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
  if (parts[6] === "documents") {
    const d = parts[7];
    if (method === "POST") {
      const form = options.body as FormData;
      const file = form.get("file") as File;
      const created = {
        ...documentRow("new"),
        filename: file.name,
        mime_type: file.type,
        size_bytes: file.size,
        parse_status: uploadStatus,
        parse_error_code: uploadStatus === "failed" ? "TEXT_NOT_UTF8" : null,
      };
      documents.push(created);
      return Response.json(created, { status: 201 });
    }
    if (!d) {
      const skip = Number(parsed.searchParams.get("skip")),
        limit = Number(parsed.searchParams.get("limit"));
      return Response.json({ items: documents.slice(skip, skip + limit), total: documents.length });
    }
    const found = documents.find((item) => item.id === d);
    if (!found) return Response.json({}, { status: 404 });
    if (method === "DELETE") {
      documents = documents.filter((item) => item.id !== d);
      return new Response(null, { status: 204 });
    }
    if (parts[8] === "content")
      return Response.json({
        document_id: d,
        content: contentText,
        page_count: null,
        parse_metadata: {},
      });
    if (parts[8] === "download")
      return new Response(new Uint8Array([0, 255, 10, 13]), {
        headers: { "Content-Type": "application/octet-stream" },
      });
    return Response.json(found);
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
  const element = (id = userId, kb = detail) => (
    <NextIntlClientProvider
      locale={locale}
      messages={{
        knowledgeManagement: (locale === "pl" ? polish : messages).knowledgeManagement,
        common: messages.common,
      }}
    >
      <QueryClientProvider client={client}>
        <KnowledgeManagement userId={id} knowledgeBaseId={kb} />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
  const view = render(element());
  return {
    ...view,
    refresh: (id = userId) => view.rerender(element(id)),
    refreshScope: (kb: string) => view.rerender(element(userId, kb)),
  };
}
const kbCalls = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("knowledge-bases"));
const writes = () => kbCalls().filter(([, opts]) => opts.method !== "GET");
beforeAll(() => {
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: () => "blob:initial",
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: () => {},
  });
  return Object.defineProperties(HTMLElement.prototype, {
    hasPointerCapture: { configurable: true, value: () => false },
    setPointerCapture: { configurable: true, value: () => {} },
    releasePointerCapture: { configurable: true, value: () => {} },
    scrollIntoView: { configurable: true, value: () => {} },
  });
});
let documents: KnowledgeDocumentRead[], uploadStatus: "ready" | "failed", contentText: string;
const documentRow = (id = "d1", filename = "真实文档.txt"): KnowledgeDocumentRead => ({
  id,
  filename,
  workspace_id: "w1",
  knowledge_base_id: "kb1",
  created_by_user_id: "a",
  mime_type: "text/plain",
  size_bytes: 4,
  sha256: "a".repeat(64),
  parse_status: "ready",
  parse_error_code: null,
  page_count: null,
  parse_metadata: {},
  created_at: "2026-11-20",
  updated_at: null,
});
beforeEach(() => {
  documents = [documentRow()];
  uploadStatus = "ready";
  contentText = "<script>alert(1)</script> ![image](https://evil.test/a)";
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
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
  vi.mocked(URL.createObjectURL).mockRestore();
  vi.mocked(URL.revokeObjectURL).mockRestore();
  vi.mocked(HTMLAnchorElement.prototype.click).mockRestore();
  unbind();
  client.clear();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});

const docPath = "/api/workspaces/w1/knowledge-bases/kb1/documents";
const documentCalls = () =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes("/documents"));
async function listReady() {
  mount("kb1");
  await screen.findByRole("button", { name: "真实文档.txt" });
}
async function openDetail() {
  await listReady();
  await userEvent.click(screen.getByRole("button", { name: "真实文档.txt" }));
  await screen.findByText("SHA-256");
}
async function openUpload(file?: File) {
  mount("kb1");
  await userEvent.click(await screen.findByRole("button", { name: "Upload document" }));
  if (file) fireEvent.change(screen.getByLabelText("File"), { target: { files: [file] } });
  return screen.getByRole("dialog");
}
async function submitUpload() {
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Upload document" }),
  );
}
it("waits for verified base before querying documents", async () => {
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/knowledge-bases/kb1", () => pending.promise);
  mount("kb1");
  await waitFor(() => expect(kbCalls().length).toBe(1));
  expect(documentCalls()).toHaveLength(0);
  await act(async () => pending.resolve(Response.json(base())));
  await screen.findByRole("button", { name: "真实文档.txt" });
  expect(String(documentCalls()[0]![0])).toContain("skip=0&limit=10");
});
it("does not mount documents for a base in the wrong scope", async () => {
  overrides.set("GET /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json(base("wrong", "w2")),
  );
  mount("kb1");
  await screen.findByText(messages.knowledgeManagement.scopeError);
  expect(documentCalls()).toHaveLength(0);
});
it("uses real pagination and recovers after deleting last row", async () => {
  documents = Array.from({ length: 11 }, (_, i) => documentRow(`d${i}`, `file${i}.txt`));
  mount("kb1");
  await screen.findByRole("button", { name: "file0.txt" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await userEvent.click(await screen.findByRole("button", { name: "Delete document file10.txt" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete document" }),
  );
  await screen.findByRole("button", { name: "file0.txt" });
  expect(documents).toHaveLength(10);
});
it("shows empty and retries list errors without fabricated initial total", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${docPath}`, () => pending.promise);
  mount("kb1");
  await waitFor(() => expect(documentCalls()).toHaveLength(1));
  expect(screen.queryByText("0 documents")).not.toBeInTheDocument();
  await act(async () => pending.resolve(Response.json({}, { status: 500 })));
  await screen.findByText("Unable to load documents");
  overrides.delete(`GET ${docPath}`);
  documents = [];
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("No documents");
});
it("omits wrong-scope list rows", async () => {
  documents = [{ ...documentRow(), workspace_id: "w2", filename: "secret" }];
  mount("kb1");
  await screen.findByText("No documents");
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});
for (const [name, type] of [
  ["a.PDF", "application/pdf"],
  ["a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  ["a.txt", "text/plain"],
  ["a.md", "text/markdown"],
  ["a.markdown", "text/plain"],
])
  it(`uploads ${name} through real FormData without indexing`, async () => {
    await openUpload(new File(["actual bytes"], name!, { type }));
    await submitUpload();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const write = documentCalls().find(([, o]) => o.method === "POST")!;
    const form = write[1].body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect((form.get("file") as File).name).toBe(name);
    expect((form.get("file") as File).size).toBe(12);
    expect(new Headers(write[1].headers).has("Content-Type")).toBe(false);
    expect(kbCalls().some(([url]) => String(url).includes("index"))).toBe(false);
  });
for (const [file, key] of [
  [undefined, "chooseFile"],
  [new File([], "a.txt", { type: "text/plain" }), "DOCUMENT_EMPTY"],
  [new File(["x"], "a.exe", { type: "text/plain" }), "DOCUMENT_TYPE_UNSUPPORTED"],
  [new File(["x"], "a.md", { type: "text/x-markdown" }), "DOCUMENT_MIME_MISMATCH"],
] as const)
  it(`rejects invalid upload ${key}`, async () => {
    await openUpload(file);
    await submitUpload();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      messages.knowledgeManagement.documents.errors[key],
    );
    expect(writes()).toHaveLength(0);
  });
it("accepts exactly 10 MiB and refuses one extra byte", () => {
  expect(
    "file" in
      prepareDocument(
        new File([new Uint8Array(MAX_DOCUMENT_BYTES)], "a.txt", { type: "text/plain" }),
      ),
  ).toBe(true);
  expect(
    prepareDocument(
      new File([new Uint8Array(MAX_DOCUMENT_BYTES + 1)], "a.txt", { type: "text/plain" }),
    ),
  ).toEqual({ error: "DOCUMENT_TOO_LARGE" });
});
it("fills only absent MIME while retaining filename and bytes", async () => {
  const original = new File(["hello"], "Żółć.MD", { lastModified: 42 });
  const result = prepareDocument(original);
  expect("file" in result).toBe(true);
  if ("file" in result) {
    expect(result.file.type).toBe("text/markdown");
    expect(result.file.name).toBe(original.name);
    expect(result.file.size).toBe(5);
    expect(result.file.lastModified).toBe(42);
  }
  await openUpload(original);
  await submitUpload();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("retains file on failed POST and prevents duplicate pending submits", async () => {
  const pending = deferred<Response>();
  overrides.set(`POST ${docPath}`, () => pending.promise);
  await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
  await submitUpload();
  await submitUpload();
  expect(writes()).toHaveLength(1);
  await act(async () => pending.resolve(Response.json({ detail: "secret" }, { status: 500 })));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("File")).not.toBeDisabled();
  expect((screen.getByLabelText("File") as HTMLInputElement).files?.[0]?.name).toBe("a.txt");
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});
it("treats 201 failed as saved and forbids resubmitting", async () => {
  uploadStatus = "failed";
  await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
  await submitUpload();
  await screen.findByText(/Document saved, but parsing failed/);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(
    within(screen.getByRole("dialog")).queryByRole("button", { name: "Upload document" }),
  ).not.toBeInTheDocument();
  expect(documents).toHaveLength(2);
});
it("loads latest metadata and fetches content only on demand as bounded inert text", async () => {
  contentText = "<script>alert(1)</script>" + "x".repeat(PREVIEW_CHAR_LIMIT);
  await openDetail();
  expect(documentCalls().some(([u]) => String(u).endsWith("content"))).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await screen.findByText(/Partial preview/);
  expect(document.querySelector("pre")!.textContent).toHaveLength(PREVIEW_CHAR_LIMIT);
  expect(document.querySelector("pre script")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Hide preview" }));
  expect(document.querySelector("pre")).toBeNull();
});
for (const status of ["failed", "unexpected"])
  it(`never previews ${status} metadata`, async () => {
    documents = [
      { ...documentRow(), parse_status: status as "failed", parse_error_code: "PDF_CORRUPT" },
    ];
    await openDetail();
    expect(screen.queryByRole("button", { name: "Preview text" })).not.toBeInTheDocument();
    expect(documentCalls().some(([u]) => String(u).endsWith("content"))).toBe(false);
  });
for (const field of ["id", "workspace_id", "knowledge_base_id"])
  it(`rejects mismatched metadata ${field}`, async () => {
    overrides.set(`GET ${docPath}/d1`, () => Response.json({ ...documentRow(), [field]: "wrong" }));
    await listReady();
    await userEvent.click(screen.getByRole("button", { name: "真实文档.txt" }));
    await screen.findByText(messages.knowledgeManagement.scopeError);
    expect(screen.queryByRole("button", { name: "Download original" })).not.toBeInTheDocument();
  });
it("handles 409 content unavailable without clearing workspace", async () => {
  overrides.set(`GET ${docPath}/d1/content`, () =>
    Response.json({ error: { code: "DOCUMENT_CONTENT_UNAVAILABLE" } }, { status: 409 }),
  );
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await screen.findByText("Parsed content is unavailable.");
  expect(client.getQueryData(qk.knowledge.base("a", "w1", "kb1"))).toBeDefined();
});
it("rejects content with another document id", async () => {
  overrides.set(`GET ${docPath}/d1/content`, () =>
    Response.json({ document_id: "wrong", content: "private" }),
  );
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await screen.findByText(messages.knowledgeManagement.scopeError);
  expect(screen.queryByText("private")).not.toBeInTheDocument();
});
it("downloads untouched blob with Unicode metadata filename and cleans anchor and URL", async () => {
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0]![0] as Blob;
  expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([0, 255, 10, 13]);
  const anchor = vi.mocked(HTMLAnchorElement.prototype.click).mock
    .instances[0] as unknown as HTMLAnchorElement;
  expect(anchor.download).toBe("真实文档.txt");
  expect(anchor.isConnected).toBe(false);
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test"), {
    timeout: 2000,
  });
});
it("sanitizes unsafe filenames while preserving Unicode", () => {
  expect(safeFilename("../路径\\x\x00.txt")).toBe("_路径_x_.txt");
  expect(safeFilename("... ")).toBe("document");
});
it("never downloads an error response", async () => {
  overrides.set(`GET ${docPath}/d1/download`, () =>
    Response.json({ detail: "secret" }, { status: 500 }),
  );
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await screen.findByRole("alert");
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
for (const reason of ["close", "delete", "logout", "account", "same-user", "workspace-loss"])
  it(`suppresses late downloads after ${reason}`, async () => {
    const pending = deferred<Response>();
    overrides.set(`GET ${docPath}/d1/download`, () => pending.promise);
    await openDetail();
    await userEvent.click(screen.getByRole("button", { name: "Download original" }));
    await waitFor(() =>
      expect(documentCalls().some(([u]) => String(u).endsWith("download"))).toBe(true),
    );
    await act(async () => {
      if (reason === "close") fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
      else if (reason === "delete")
        clearKnowledgeScope(client, qk.knowledge.document("a", "w1", "kb1", "d1"));
      else if (reason === "workspace-loss")
        clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1"));
      else {
        useAuthStore.getState().logout();
        if (reason !== "logout") useAuthStore.getState().setUser(reason === "account" ? B : A);
      }
    });
    await act(async () => pending.resolve(new Response("private")));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
for (const role of ["owner", "admin", "member"] as const)
  it(`applies workspace ${role} permissions`, async () => {
    roles.w1 = role;
    await listReady();
    expect(Boolean(screen.queryByRole("button", { name: "Upload document" }))).toBe(
      role !== "member",
    );
    expect(Boolean(screen.queryByRole("button", { name: "Delete document 真实文档.txt" }))).toBe(
      role !== "member",
    );
    await userEvent.click(screen.getByRole("button", { name: "真实文档.txt" }));
    await screen.findByRole("button", { name: "Download original" });
  });
it("supports cancel and retains delete dialog on server failure", async () => {
  await listReady();
  await userEvent.click(screen.getByRole("button", { name: "Delete document 真实文档.txt" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(writes()).toHaveLength(0);
  overrides.set(`DELETE ${docPath}/d1`, () => Response.json({}, { status: 500 }));
  await userEvent.click(screen.getByRole("button", { name: "Delete document 真实文档.txt" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete document" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});
it("revalidates membership and stops writes on upload 403", async () => {
  overrides.set(`POST ${docPath}`, () => {
    roles.w1 = "member";
    return Response.json({}, { status: 403 });
  });
  await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
  await submitUpload();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument(),
  );
});
it("keeps workspace after single document 404", async () => {
  overrides.set(`GET ${docPath}/d1`, () => Response.json({}, { status: 404 }));
  await listReady();
  await userEvent.click(screen.getByRole("button", { name: "真实文档.txt" }));
  await screen.findByText("Unable to load document details");
  await waitFor(() =>
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === "/api/workspaces/w1")).toHaveLength(
      1,
    ),
  );
  expect(client.getQueryData(qk.knowledge.base("a", "w1", "kb1"))).toBeDefined();
});
it("preserves translation keys and maps every actual parser error", () => {
  expect(Object.keys(messages.knowledgeManagement.documents).sort()).toEqual(
    Object.keys(polish.knowledgeManagement.documents).sort(),
  );
  for (const code of DOCUMENT_CODES) {
    expect(messages.knowledgeManagement.documents.errors).toHaveProperty(code);
    expect(polish.knowledgeManagement.documents.errors).toHaveProperty(code);
  }
});

it("latest download wins when two requests finish out of order", async () => {
  const first = deferred<Response>(),
    second = deferred<Response>();
  let n = 0;
  overrides.set(`GET ${docPath}/d1/download`, () => (++n === 1 ? first.promise : second.promise));
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(n).toBe(1));
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(n).toBe(2));
  await act(async () => second.resolve(new Response("new bytes")));
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
  await act(async () => first.resolve(new Response("old bytes")));
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
});
for (const change of ["workspace", "base", "logout", "account", "same-user"])
  it(`isolates a pending upload after ${change}`, async () => {
    const pending = deferred<Response>();
    overrides.set(`POST ${docPath}`, () => pending.promise);
    await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
    await submitUpload();
    await act(async () => {
      if (change === "workspace") clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1"));
      else if (change === "base") clearKnowledgeScope(client, qk.knowledge.base("a", "w1", "kb1"));
      else {
        useAuthStore.getState().logout();
        if (change !== "logout") useAuthStore.getState().setUser(change === "account" ? B : A);
      }
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await act(async () =>
      pending.resolve(
        Response.json(
          { ...documentRow("new"), parse_status: "failed", parse_error_code: "TEXT_NOT_UTF8" },
          { status: 201 },
        ),
      ),
    );
    expect(screen.queryByText(/Document saved, but/)).not.toBeInTheDocument();
    expect(route.push).not.toHaveBeenCalled();
  });
it("cancels content when preview is closed", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${docPath}/d1/content`, () => pending.promise);
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await waitFor(() =>
    expect(documentCalls().some(([u]) => String(u).endsWith("content"))).toBe(true),
  );
  const call = documentCalls().find(([u]) => String(u).endsWith("content"))!;
  await userEvent.click(screen.getByRole("button", { name: "Hide preview" }));
  expect(call[1].signal.aborted).toBe(true);
  await act(async () =>
    pending.resolve(Response.json({ document_id: "d1", content: "late secret" })),
  );
  expect(screen.queryByText("late secret")).not.toBeInTheDocument();
});
it("hides delayed content after confirmed workspace revocation", async () => {
  const pending = deferred<Response>();
  overrides.set(`GET ${docPath}/d1/content`, () => pending.promise);
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await waitFor(() =>
    expect(documentCalls().some(([u]) => String(u).endsWith("content"))).toBe(true),
  );
  await act(async () => clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1")));
  await act(async () =>
    pending.resolve(Response.json({ document_id: "d1", content: "revoked secret" })),
  );
  expect(screen.queryByText("revoked secret")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("precisely clears deleted document while preserving other scopes", async () => {
  await listReady();
  const other = qk.knowledge.document("a", "w1", "kb1", "other"),
    foreign = qk.knowledge.document("a", "w2", "kb2", "foreign");
  client.setQueryData(other, { keep: true });
  client.setQueryData(foreign, { keep: true });
  client.setQueryData(qk.knowledge.content("a", "w1", "kb1", "d1"), {
    document_id: "d1",
    content: "old",
  });
  await userEvent.click(screen.getByRole("button", { name: "Delete document 真实文档.txt" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete document" }),
  );
  await screen.findByText("No documents");
  expect(client.getQueryData(qk.knowledge.content("a", "w1", "kb1", "d1"))).toBeUndefined();
  expect(client.getQueryData(other)).toEqual({ keep: true });
  expect(client.getQueryData(foreign)).toEqual({ keep: true });
});
it("does not issue document requests while membership is unknown", async () => {
  const pending = deferred<Response>();
  overrides.set("GET /api/workspaces/w1/members", () => pending.promise);
  mount("kb1");
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("members"))).toBe(true),
  );
  expect(documentCalls()).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument();
});
it("closes write dialog on permission revalidation and downgrade", async () => {
  await openUpload();
  roles.w1 = "member";
  await act(async () => {
    await client.invalidateQueries({ queryKey: qk.workspaces.members("a", "w1") });
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument();
});

for (const resource of ["workspace", "base"])
  it(`switches actual ${resource} while download is pending`, async () => {
    const pending = deferred<Response>();
    overrides.set(`GET ${docPath}/d1/download`, () => pending.promise);
    const view = mount("kb1");
    await userEvent.click(await screen.findByRole("button", { name: "真实文档.txt" }));
    await userEvent.click(await screen.findByRole("button", { name: "Download original" }));
    await waitFor(() =>
      expect(documentCalls().some(([u]) => String(u).endsWith("download"))).toBe(true),
    );
    database.w1!.push(base("kb2"));
    if (resource === "workspace") route.search = "workspace_id=w2";
    view.refreshScope("kb2");
    await screen.findByRole("heading", {
      name: resource === "workspace" ? "Other workspace secret" : "Real knowledge",
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const call = documentCalls().find(([u]) => String(u).endsWith("download"))!;
    expect(call[1].signal.aborted).toBe(true);
    await act(async () => pending.resolve(new Response("old")));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(
      documentCalls().some(([u]) =>
        String(u).includes(
          resource === "workspace"
            ? "/w2/knowledge-bases/kb2/documents?skip=0"
            : "/w1/knowledge-bases/kb2/documents?skip=0",
        ),
      ),
    ).toBe(true);
  });
it("late upload failure cannot close a new base upload dialog", async () => {
  const pending = deferred<Response>();
  overrides.set(`POST ${docPath}`, () => pending.promise);
  database.w1!.push(base("kb2"));
  const view = mount("kb1");
  await userEvent.click(await screen.findByRole("button", { name: "Upload document" }));
  fireEvent.change(screen.getByLabelText("File"), {
    target: { files: [new File(["x"], "old.txt", { type: "text/plain" })] },
  });
  await submitUpload();
  view.refreshScope("kb2");
  await userEvent.click(await screen.findByRole("button", { name: "Upload document" }));
  fireEvent.change(screen.getByLabelText("File"), {
    target: { files: [new File(["new"], "new.txt", { type: "text/plain" })] },
  });
  await act(async () =>
    pending.resolve(Response.json({ detail: "old server secret" }, { status: 500 })),
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect((screen.getByLabelText("File") as HTMLInputElement).files![0]!.name).toBe("new.txt");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(route.push).not.toHaveBeenCalled();
});
it("renders latest metadata instead of stale row and omits private parser fields", async () => {
  overrides.set(`GET ${docPath}/d1`, () =>
    Response.json({
      ...documentRow(),
      filename: "<img src=x onerror=alert(1)>",
      parse_metadata: {
        storage_path: "/private/token",
        stack_trace: "secret trace",
        paragraph_count: 12,
      },
    }),
  );
  await openDetail();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(screen.queryByText("/private/token")).not.toBeInTheDocument();
  expect(screen.getByText("12")).toBeInTheDocument();
  expect(document.querySelector("[role=dialog] img")).toBeNull();
});
it("does not run upload callbacks after confirmed base removal", async () => {
  const pending = deferred<Response>();
  overrides.set(`POST ${docPath}`, () => pending.promise);
  await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
  await submitUpload();
  await act(async () => clearKnowledgeScope(client, qk.knowledge.base("a", "w1", "kb1")));
  await act(async () => pending.resolve(Response.json(documentRow("new"), { status: 201 })));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(route.push).not.toHaveBeenCalled();
});

for (const code of DOCUMENT_CODES)
  it(`shows safe request error for ${code} without exposing detail`, async () => {
    overrides.set(`POST ${docPath}`, () =>
      Response.json({ error: { code }, detail: "/secret/token traceback" }, { status: 400 }),
    );
    await openUpload(new File(["x"], "a.txt", { type: "text/plain" }));
    await submitUpload();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      messages.knowledgeManagement.documents.errors[code],
    );
    expect(screen.queryByText("/secret/token traceback")).not.toBeInTheDocument();
    expect((screen.getByLabelText("File") as HTMLInputElement).files![0]!.name).toBe("a.txt");
  });
it("resets pagination after an actual base switch", async () => {
  documents = Array.from({ length: 11 }, (_, i) => documentRow(`d${i}`, `file${i}.txt`));
  database.w1!.push(base("kb2"));
  const view = mount("kb1");
  await screen.findByRole("button", { name: "file0.txt" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("button", { name: "file10.txt" });
  view.refreshScope("kb2");
  await waitFor(() =>
    expect(
      documentCalls().some(([u]) => String(u).includes("/kb2/documents?skip=0&limit=10")),
    ).toBe(true),
  );
  expect(screen.queryByRole("button", { name: "file10.txt" })).not.toBeInTheDocument();
});
it("confirms base 404 independently without clearing a different workspace", async () => {
  await listReady();
  const other = qk.knowledge.document("a", "w2", "kb2", "other");
  client.setQueryData(other, { keep: true });
  overrides.set(`GET ${docPath}/d1`, () => Response.json({}, { status: 404 }));
  overrides.set("GET /api/workspaces/w1/knowledge-bases/kb1", () =>
    Response.json({}, { status: 404 }),
  );
  await userEvent.click(screen.getByRole("button", { name: "真实文档.txt" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(client.getQueryData(other)).toEqual({ keep: true });
  expect(client.getQueryData(qk.knowledge.base("a", "w1", "kb1"))).toBeUndefined();
});

for (const extension of ["constructor", "__proto__", "toString"])
  it(`rejects inherited extension ${extension}`, () => {
    expect(prepareDocument(new File(["x"], `file.${extension}`, { type: "text/plain" }))).toEqual({
      error: "DOCUMENT_TYPE_UNSUPPORTED",
    });
  });
it("does not restart a list after synchronous scope revocation", async () => {
  await listReady();
  const before = documentCalls().length;
  await act(async () => clearKnowledgeScope(client, qk.knowledge.workspace("a", "w1")));
  await screen.findByText(messages.knowledgeManagement.scopeError);
  await act(async () => {
    await client.invalidateQueries({ queryKey: qk.knowledge.workspace("a", "w1") });
  });
  expect(documentCalls()).toHaveLength(before);
  expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument();
});
it("preserves actual bytes when completing empty MIME", async () => {
  const original = new File([new Uint8Array([0, 195, 169, 255])], "Żółć.md");
  const result = prepareDocument(original);
  if (!("file" in result)) throw new Error("Expected valid file");
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(result.file);
  });
  expect([...new Uint8Array(bytes)]).toEqual([0, 195, 169, 255]);
});

it("retains delete confirmation on document 404 without clearing the workspace", async () => {
  await listReady();
  overrides.set(`DELETE ${docPath}/d1`, () => Response.json({}, { status: 404 }));
  await userEvent.click(screen.getByRole("button", { name: "Delete document 真实文档.txt" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete document" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(client.getQueryData(qk.knowledge.base("a", "w1", "kb1"))).toBeDefined();
});
it("shows content unavailable for an unstructured 409", async () => {
  overrides.set(`GET ${docPath}/d1/content`, () =>
    Response.json({ detail: "private trace" }, { status: 409 }),
  );
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Preview text" }));
  await screen.findByText("Parsed content is unavailable.");
  expect(screen.queryByText("private trace")).not.toBeInTheDocument();
});
it("revalidates and disables document delete on 403", async () => {
  await listReady();
  overrides.set(`DELETE ${docPath}/d1`, () => {
    roles.w1 = "member";
    return Response.json({}, { status: 403 });
  });
  await userEvent.click(screen.getByRole("button", { name: "Delete document 真实文档.txt" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Delete document" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Delete document 真实文档.txt" }),
    ).not.toBeInTheDocument(),
  );
});

it("does not download or close the new dialog after switching documents", async () => {
  documents.push(documentRow("d2", "new document.txt"));
  const pending = deferred<Response>();
  overrides.set(`GET ${docPath}/d1/download`, () => pending.promise);
  await openDetail();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() =>
    expect(documentCalls().some(([u]) => String(u).endsWith("download"))).toBe(true),
  );
  await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
  await userEvent.click(screen.getByRole("button", { name: "new document.txt" }));
  await screen.findByText("SHA-256");
  await act(async () => pending.resolve(new Response("old bytes")));
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(within(screen.getByRole("dialog")).getByText("new document.txt")).toBeInTheDocument();
});
it("isolates selected file and late upload success after actual workspace switch", async () => {
  const pending = deferred<Response>();
  overrides.set(`POST ${docPath}`, () => pending.promise);
  const view = mount("kb1");
  await userEvent.click(await screen.findByRole("button", { name: "Upload document" }));
  fireEvent.change(screen.getByLabelText("File"), {
    target: { files: [new File(["old"], "old.txt", { type: "text/plain" })] },
  });
  await submitUpload();
  route.search = "workspace_id=w2";
  view.refreshScope("kb2");
  await userEvent.click(await screen.findByRole("button", { name: "Upload document" }));
  expect((screen.getByLabelText("File") as HTMLInputElement).files).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("File"), {
    target: { files: [new File(["new"], "new.txt", { type: "text/plain" })] },
  });
  await act(async () => pending.resolve(Response.json(documentRow("old result"), { status: 201 })));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect((screen.getByLabelText("File") as HTMLInputElement).files![0]!.name).toBe("new.txt");
  expect(route.push).not.toHaveBeenCalled();
});
