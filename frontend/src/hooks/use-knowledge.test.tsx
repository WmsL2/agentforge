import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { User } from "@/types";
import { useAuthStore } from "@/stores/auth-store";
import { qk } from "@/lib/query-keys";
import { knowledgeApi } from "@/lib/knowledge/knowledge-api";
import { bindKnowledgeLifecycle, clearKnowledgeScope } from "@/lib/knowledge/knowledge-lifecycle";
import { ApiError } from "@/lib/api-client";
import { workspaceApi } from "@/lib/workflow/workspace-api";
import { useWorkspaceMembers, useWorkspaceMutations } from "./use-workspaces";
import {
  useKnowledgeAsk,
  useKnowledgeSearch,
  useKnowledgeBase,
  useKnowledgeBases,
  useKnowledgeDocuments,
  useKnowledgeDocument,
  useKnowledgeDocumentContent,
  useKnowledgeIndexStatus,
  useKnowledgeBaseMutations,
  useKnowledgeDocumentMutations,
  useKnowledgeIndexMutation,
} from "./use-knowledge";
vi.mock("@/lib/knowledge/knowledge-api", () => ({
  knowledgeApi: {
    listKnowledgeBases: vi.fn(),
    getKnowledgeBase: vi.fn(),
    listDocuments: vi.fn(),
    getDocument: vi.fn(),
    getDocumentContent: vi.fn(),
    getIndexStatus: vi.fn(),
    createKnowledgeBase: vi.fn(),
    updateKnowledgeBase: vi.fn(),
    deleteKnowledgeBase: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    requestIndex: vi.fn(),
    downloadDocument: vi.fn(),
    search: vi.fn(),
    ask: vi.fn(),
  },
}));
vi.mock("@/lib/workflow/workspace-api", () => ({
  workspaceApi: { deleteWorkspace: vi.fn(), listMembers: vi.fn() },
}));
const api = vi.mocked(knowledgeApi);
let client: QueryClient, unbind: () => void;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (v: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: { id: "u" } as User, isAuthenticated: true });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  unbind = bindKnowledgeLifecycle(client);
});
afterEach(() => {
  cleanup();
  unbind();
  client.clear();
  useAuthStore.getState().logout();
});
it("keys isolate all resource levels and pagination", () => {
  const keys = [
    qk.knowledge.list("u", "w", 0, 50),
    qk.knowledge.list("v", "w", 0, 50),
    qk.knowledge.list("u", "v", 0, 50),
    qk.knowledge.list("u", "w", 1, 50),
    qk.knowledge.list("u", "w", 0, 2),
    qk.knowledge.base("u", "w", "b"),
    qk.knowledge.base("u", "w", "c"),
    qk.knowledge.document("u", "w", "b", "d"),
    qk.knowledge.document("u", "w", "b", "e"),
    qk.knowledge.content("u", "w", "b", "d"),
    qk.knowledge.index("u", "w", "b", "d"),
  ];
  expect(new Set(keys.map((k) => JSON.stringify(k))).size).toBe(keys.length);
  expect(qk.knowledge.root()).toEqual(["knowledge"]);
  expect(qk.knowledge.user("u")).toEqual(["knowledge", "u"]);
});
it("does not request with missing identity or IDs; content is opt-in", () => {
  renderHook(
    () => {
      useKnowledgeBases();
      useKnowledgeBase("u", "w");
      useKnowledgeDocuments("u");
      useKnowledgeDocument("u", "w", "b");
      useKnowledgeDocumentContent("u", "w", "b", "d");
      useKnowledgeIndexStatus("u", "w");
      useKnowledgeBase("other", "w", "b");
    },
    { wrapper },
  );
  Object.values(api).forEach((fn) => expect(fn).not.toHaveBeenCalled());
});
it("reads with signal, conservative caching, no index polling", async () => {
  api.getIndexStatus.mockResolvedValue({
    document_id: "d",
    status: "not_indexed",
    job_id: null,
    active_generation_id: null,
    chunk_count: 0,
    embedding_model: null,
    index_version: null,
    error_code: null,
  });
  const hook = renderHook(() => useKnowledgeIndexStatus("u", "w", "b", "d"), { wrapper });
  await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
  expect(api.getIndexStatus.mock.calls[0]![3]).toMatchObject({
    userId: "u",
    signal: expect.any(AbortSignal),
  });
  const options = client.getQueryCache().getAll()[0]!.options;
  expect(options).toMatchObject({ staleTime: 0, gcTime: 0, retry: false, refetchInterval: false });
  hook.unmount();
  await waitFor(() => expect(client.getQueryCache().getAll()).toHaveLength(0));
});
it("switches workspace without showing prior query result and aborts old query", async () => {
  const old = deferred<Awaited<ReturnType<typeof knowledgeApi.getDocument>>>();
  api.getDocument
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce({ id: "new" } as Awaited<ReturnType<typeof knowledgeApi.getDocument>>);
  const hook = renderHook(({ w }) => useKnowledgeDocument("u", w, "b", "d"), {
    wrapper,
    initialProps: { w: "A" },
  });
  await waitFor(() => expect(api.getDocument).toHaveBeenCalledTimes(1));
  const signal = api.getDocument.mock.calls[0]![3]?.signal;
  hook.rerender({ w: "B" });
  expect(hook.result.current.data).toBeUndefined();
  await waitFor(() => expect(hook.result.current.data?.id).toBe("new"));
  expect(signal?.aborted).toBe(true);
  old.resolve({ id: "old" } as Awaited<ReturnType<typeof knowledgeApi.getDocument>>);
  await act(async () => {
    await old.promise;
  });
  expect(hook.result.current.data?.id).toBe("new");
});
it("creates and updates only corresponding workspace list and detail", async () => {
  const list = qk.knowledge.list("u", "w"),
    other = qk.knowledge.list("u", "other"),
    base = qk.knowledge.base("u", "w", "b");
  for (const k of [list, other, base]) client.setQueryData(k, { value: 1 });
  api.createKnowledgeBase.mockResolvedValue({ id: "new" } as Awaited<
    ReturnType<typeof knowledgeApi.createKnowledgeBase>
  >);
  api.updateKnowledgeBase.mockResolvedValue({ id: "b" } as Awaited<
    ReturnType<typeof knowledgeApi.updateKnowledgeBase>
  >);
  const hook = renderHook(() => useKnowledgeBaseMutations("u", "w"), { wrapper });
  await act(() => hook.result.current.create.mutateAsync({ name: "new" }));
  expect(client.getQueryState(list)?.isInvalidated).toBe(true);
  expect(client.getQueryState(other)?.isInvalidated).toBe(false);
  await act(() =>
    hook.result.current.update.mutateAsync({
      knowledgeBaseId: "b",
      payload: { description: null },
    }),
  );
  expect(client.getQueryState(base)?.isInvalidated).toBe(true);
});
it("KB deletion removes every child but preserves other workspaces", async () => {
  const keys = [
    qk.knowledge.base("u", "w", "b"),
    qk.knowledge.documents("u", "w", "b"),
    qk.knowledge.content("u", "w", "b", "d"),
    qk.knowledge.index("u", "w", "b", "d"),
  ];
  keys.forEach((k) => client.setQueryData(k, "secret"));
  const other = qk.knowledge.content("u", "other", "b", "d");
  client.setQueryData(other, "keep");
  api.deleteKnowledgeBase.mockResolvedValue(null);
  const hook = renderHook(() => useKnowledgeBaseMutations("u", "w"), { wrapper });
  await act(() => hook.result.current.remove.mutateAsync("b"));
  keys.forEach((k) => expect(client.getQueryData(k)).toBeUndefined());
  expect(client.getQueryData(other)).toBe("keep");
});
it("upload invalidates document pagination, delete removes detail/content/index, index invalidates status", async () => {
  const lists = [
    qk.knowledge.documents("u", "w", "b", 0, 50),
    qk.knowledge.documents("u", "w", "b", 50, 50),
  ];
  const children = [
    qk.knowledge.document("u", "w", "b", "d"),
    qk.knowledge.content("u", "w", "b", "d"),
    qk.knowledge.index("u", "w", "b", "d"),
  ];
  [...lists, ...children].forEach((k) => client.setQueryData(k, "old"));
  api.uploadDocument.mockResolvedValue({ parse_status: "failed" } as Awaited<
    ReturnType<typeof knowledgeApi.uploadDocument>
  >);
  api.deleteDocument.mockResolvedValue(null);
  api.requestIndex.mockResolvedValue({ status: "pending" } as Awaited<
    ReturnType<typeof knowledgeApi.requestIndex>
  >);
  const hook = renderHook(
    () => ({
      docs: useKnowledgeDocumentMutations("u", "w", "b"),
      index: useKnowledgeIndexMutation("u", "w", "b", "d"),
    }),
    { wrapper },
  );
  await act(() => hook.result.current.docs.upload.mutateAsync(new File(["x"], "x.txt")));
  lists.forEach((k) => expect(client.getQueryState(k)?.isInvalidated).toBe(true));
  await act(() => hook.result.current.index.mutateAsync());
  expect(client.getQueryState(children[2]!)?.isInvalidated).toBe(true);
  await act(() => hook.result.current.docs.remove.mutateAsync("d"));
  children.forEach((k) => expect(client.getQueryData(k)).toBeUndefined());
});
it("failed writes do not change cache or retry; concurrent duplicate write is coalesced", async () => {
  const pending = deferred<Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>>();
  api.createKnowledgeBase.mockReturnValue(pending.promise);
  const key = qk.knowledge.list("u", "w");
  client.setQueryData(key, "keep");
  const hook = renderHook(() => useKnowledgeBaseMutations("u", "w"), { wrapper });
  let first!: Promise<unknown>, second!: Promise<unknown>;
  act(() => {
    first = hook.result.current.create.mutateAsync({ name: "x" });
    second = hook.result.current.create.mutateAsync({ name: "x" });
  });
  expect(first).toBe(second);
  pending.reject(new ApiError(422, "bad"));
  await act(async () => {
    await expect(first).rejects.toMatchObject({ status: 422 });
  });
  expect(api.createKnowledgeBase).toHaveBeenCalledTimes(1);
  expect(client.getQueryState(key)?.isInvalidated).toBe(false);
  expect(client.getQueryData(key)).toBe("keep");
});
it.each(["workspace", "logout", "user"])(
  "isolates late mutations after %s change",
  async (mode) => {
    const pending = deferred<Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>>();
    api.createKnowledgeBase.mockReturnValue(pending.promise);
    const key = qk.knowledge.list("u", "A");
    client.setQueryData(key, "old");
    const hook = renderHook(({ u, w }) => useKnowledgeBaseMutations(u, w), {
      wrapper,
      initialProps: { u: "u", w: "A" },
    });
    let promise!: Promise<unknown>;
    act(() => {
      promise = hook.result.current.create.mutateAsync({ name: "x" });
    });
    await waitFor(() => expect(api.createKnowledgeBase).toHaveBeenCalledTimes(1));
    if (mode === "workspace") hook.rerender({ u: "u", w: "B" });
    else
      act(() => {
        useAuthStore.getState().logout();
        if (mode === "user")
          useAuthStore.setState({ user: { id: "new" } as User, isAuthenticated: true });
      });
    if (mode === "user") hook.rerender({ u: "new", w: "A" });
    pending.resolve({ id: "old" } as Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>);
    await act(async () => {
      await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    });
    expect(hook.result.current.create.data).toBeUndefined();
    expect(client.getQueryData(qk.knowledge.list("new", "A"))).toBeUndefined();
    if (mode !== "workspace") expect(client.getQueryData(key)).toBeUndefined();
    else expect(client.getQueryState(key)?.isInvalidated).toBe(false);
  },
);
it("Search/Ask are manual, latest response wins, completed result clears on scope change", async () => {
  const old = deferred<Awaited<ReturnType<typeof knowledgeApi.ask>>>();
  api.ask
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce({ answer: "new", status: "answered", sources: [] });
  const hook = renderHook(
    ({ w }) => ({ ask: useKnowledgeAsk("u", w, "b"), search: useKnowledgeSearch("u", w, "b") }),
    { wrapper, initialProps: { w: "A" } },
  );
  expect(api.ask).not.toHaveBeenCalled();
  expect(api.search).not.toHaveBeenCalled();
  let first!: Promise<unknown>;
  act(() => {
    first = hook.result.current.ask.mutateAsync({ question: "old" });
  });
  await waitFor(() => expect(api.ask).toHaveBeenCalledTimes(1));
  await act(() => hook.result.current.ask.mutateAsync({ question: "new" }));
  await waitFor(() => expect(hook.result.current.ask.data?.answer).toBe("new"));
  old.resolve({ answer: "old", status: "answered", sources: [] });
  await act(async () => {
    await expect(first).rejects.toMatchObject({ name: "AbortError" });
  });
  expect(hook.result.current.ask.data?.answer).toBe("new");
  hook.rerender({ w: "B" });
  expect(hook.result.current.ask.data).toBeUndefined();
  expect(client.getQueryCache().getAll()).toHaveLength(0);
  hook.rerender({ w: "A" });
  expect(hook.result.current.ask.data).toBeUndefined();
});
it("Search/Ask failure never retries", async () => {
  api.search.mockRejectedValue(new ApiError(503, "timeout"));
  const hook = renderHook(() => useKnowledgeSearch("u", "w", "b"), { wrapper });
  await act(async () => {
    await expect(hook.result.current.mutateAsync({ query: "q" })).rejects.toMatchObject({
      status: 503,
    });
  });
  expect(api.search).toHaveBeenCalledTimes(1);
});
it("logout cancels queries and clears completed answer/download mutation state without clearing new identity", async () => {
  api.ask.mockResolvedValue({ answer: "secret", status: "answered", sources: [] });
  api.downloadDocument.mockResolvedValue({
    blob: new Blob(["secret"]),
    contentType: null,
    contentDisposition: null,
  });
  const hook = renderHook(
    () => ({
      ask: useKnowledgeAsk("u", "w", "b"),
      docs: useKnowledgeDocumentMutations("u", "w", "b"),
    }),
    { wrapper },
  );
  await act(() => hook.result.current.ask.mutateAsync({ question: "q" }));
  await act(() => hook.result.current.docs.download.mutateAsync("d"));
  const other = qk.knowledge.content("new", "w", "b", "d");
  client.setQueryData(other, "keep");
  act(() => useAuthStore.getState().logout());
  expect(hook.result.current.ask.data).toBeUndefined();
  expect(hook.result.current.docs.download.data).toBeUndefined();
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  expect(client.getQueryData(other)).toBe("keep");
});
it("document deletion clears completed private download result", async () => {
  api.downloadDocument.mockResolvedValue({
    blob: new Blob(["secret"]),
    contentType: null,
    contentDisposition: null,
  });
  const hook = renderHook(() => useKnowledgeDocumentMutations("u", "w", "b"), { wrapper });
  await act(() => hook.result.current.download.mutateAsync("d"));
  expect(hook.result.current.download.data).toBeDefined();
  act(() => clearKnowledgeScope(client, qk.knowledge.document("u", "w", "b", "d")));
  expect(hook.result.current.download.data).toBeUndefined();
});
it("workspace deletion clears only that workspace", async () => {
  const old = qk.knowledge.content("u", "w", "b", "d"),
    other = qk.knowledge.content("u", "other", "b", "d");
  client.setQueryData(old, "secret");
  client.setQueryData(other, "keep");
  vi.mocked(workspaceApi.deleteWorkspace).mockResolvedValue(null);
  const hook = renderHook(() => useWorkspaceMutations("u"), { wrapper });
  await act(() => hook.result.current.remove.mutateAsync("w"));
  expect(client.getQueryData(old)).toBeUndefined();
  expect(client.getQueryData(other)).toBe("keep");
});
it("confirmed membership loss clears only the affected workspace", async () => {
  const old = qk.knowledge.content("u", "w", "b", "d"),
    other = qk.knowledge.content("u", "other", "b", "d");
  client.setQueryData(old, "secret");
  client.setQueryData(other, "keep");
  vi.mocked(workspaceApi.listMembers).mockRejectedValue(new ApiError(404, "workspace absent"));
  const hook = renderHook(() => useWorkspaceMembers("u", "w"), { wrapper });
  await waitFor(() => expect(hook.result.current.isError).toBe(true));
  expect(client.getQueryData(old)).toBeUndefined();
  expect(client.getQueryData(other)).toBe("keep");
});
it("cleanup cancels an in-flight read before it can recreate cleared data", async () => {
  const pending = deferred<Awaited<ReturnType<typeof knowledgeApi.getDocument>>>();
  api.getDocument.mockReturnValue(pending.promise);
  const hook = renderHook(() => useKnowledgeDocument("u", "w", "b", "d"), { wrapper });
  await waitFor(() => expect(api.getDocument).toHaveBeenCalledTimes(1));
  const signal = api.getDocument.mock.calls[0]![3]?.signal;
  act(() => clearKnowledgeScope(client, qk.knowledge.workspace("u", "w")));
  expect(signal?.aborted).toBe(true);
  pending.resolve({ id: "late" } as Awaited<ReturnType<typeof knowledgeApi.getDocument>>);
  await act(async () => {
    await pending.promise;
  });
  expect(client.getQueryData(qk.knowledge.document("u", "w", "b", "d"))).toBeUndefined();
  expect(hook.result.current.data).toBeUndefined();
});

it.each(["logout", "switch"])(
  "pending Query cannot restore cleared data after %s",
  async (mode) => {
    const pending = deferred<Awaited<ReturnType<typeof knowledgeApi.getDocument>>>();
    api.getDocument.mockReturnValue(pending.promise);
    const hook = renderHook(({ u }) => useKnowledgeDocument(u, "w", "b", "d"), {
      wrapper,
      initialProps: { u: "u" },
    });
    await waitFor(() => expect(api.getDocument).toHaveBeenCalledTimes(1));
    const signal = api.getDocument.mock.calls[0]![3]?.signal;
    act(() => {
      useAuthStore.getState().logout();
      if (mode === "switch")
        useAuthStore.setState({ user: { id: "v" } as User, isAuthenticated: true });
    });
    expect(signal?.aborted).toBe(true);
    pending.resolve({ id: "old" } as Awaited<ReturnType<typeof knowledgeApi.getDocument>>);
    await act(async () => {
      await pending.promise;
    });
    expect(client.getQueryData(qk.knowledge.document("u", "w", "b", "d"))).toBeUndefined();
    expect(hook.result.current.data).toBeUndefined();
  },
);
it("workspace cleanup isolates pending Ask and create without late callbacks", async () => {
  const ask = deferred<Awaited<ReturnType<typeof knowledgeApi.ask>>>(),
    create = deferred<Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>>();
  api.ask.mockReturnValue(ask.promise);
  api.createKnowledgeBase.mockReturnValue(create.promise);
  const hook = renderHook(
    () => ({ ask: useKnowledgeAsk("u", "w", "b"), bases: useKnowledgeBaseMutations("u", "w") }),
    { wrapper },
  );
  let a!: Promise<unknown>, b!: Promise<unknown>;
  act(() => {
    a = hook.result.current.ask.mutateAsync({ question: "q" });
    b = hook.result.current.bases.create.mutateAsync({ name: "n" });
  });
  await waitFor(() => expect(api.ask).toHaveBeenCalledTimes(1));
  act(() => clearKnowledgeScope(client, qk.knowledge.workspace("u", "w")));
  ask.resolve({ answer: "old", status: "answered", sources: [] });
  create.resolve({ id: "old" } as Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>);
  await act(async () => {
    await expect(a).rejects.toMatchObject({ name: "AbortError" });
    await expect(b).rejects.toMatchObject({ name: "AbortError" });
  });
  expect(hook.result.current.ask.data).toBeUndefined();
  expect(hook.result.current.bases.create.data).toBeUndefined();
  expect(client.getQueryCache().getAll()).toHaveLength(0);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
});
it("parsed content explicitly enabled uses signal and zero retention", async () => {
  api.getDocumentContent.mockResolvedValue({
    document_id: "d",
    content: "parsed",
    page_count: null,
    parse_metadata: {},
  });
  const hook = renderHook(() => useKnowledgeDocumentContent("u", "w", "b", "d", true), { wrapper });
  await waitFor(() => expect(hook.result.current.data?.content).toBe("parsed"));
  expect(api.getDocumentContent.mock.calls[0]![3]?.signal).toBeInstanceOf(AbortSignal);
  expect(client.getQueryCache().getAll()[0]!.options).toMatchObject({ gcTime: 0, staleTime: 0 });
});

it("never returns a different pending write's result as success", async () => {
  const pending = deferred<Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>>();
  api.createKnowledgeBase.mockReturnValue(pending.promise);
  const hook = renderHook(() => useKnowledgeBaseMutations("u", "w"), { wrapper });
  let first!: Promise<unknown>;
  act(() => {
    first = hook.result.current.create.mutateAsync({ name: "first" });
  });
  await act(async () => {
    await expect(
      hook.result.current.create.mutateAsync({ name: "different" }),
    ).rejects.toMatchObject({ name: "InvalidStateError" });
  });
  pending.resolve({ id: "first" } as Awaited<ReturnType<typeof knowledgeApi.createKnowledgeBase>>);
  await act(async () => {
    await first;
  });
  expect(api.createKnowledgeBase).toHaveBeenCalledTimes(1);
});

it("manual refetch cannot bypass missing identity or resource guards", async () => {
  const hook = renderHook(
    () => ({ anonymous: useKnowledgeBases(), document: useKnowledgeDocument("u", "w", "b") }),
    { wrapper },
  );
  await act(async () => {
    await hook.result.current.anonymous.refetch();
    await hook.result.current.document.refetch();
  });
  expect(api.listKnowledgeBases).not.toHaveBeenCalled();
  expect(api.getDocument).not.toHaveBeenCalled();
});
