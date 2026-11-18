import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { knowledgeApi as api } from "./knowledge-api";
import { useAuthStore } from "@/stores/auth-store";
import { apiClient, ApiError } from "@/lib/api-client";
import { QueryClient } from "@tanstack/react-query";
import { bindKnowledgeLifecycle } from "./knowledge-lifecycle";
import { qk } from "@/lib/query-keys";
import { getKnowledgeErrorCode } from "./knowledge-error";
import type { User } from "@/types";

const fetchMock = vi.fn();
const w = "w/一",
  b = "b?#",
  d = "d/%";
const base = "/api/workspaces/w%2F%E4%B8%80/knowledge-bases";
const kb = `${base}/b%3F%23`,
  doc = `${kb}/documents/d%2F%25`;
const file = new File([new Uint8Array([0, 255, 1])], "资料.txt", { type: "text/plain" });
beforeEach(() => {
  useAuthStore.setState({ user: { id: "u" } as User, isAuthenticated: true });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset().mockImplementation(() => Promise.resolve(Response.json({ ok: true })));
});
afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});
const cases: [string, () => Promise<unknown>, string, string, unknown?][] = [
  ["list", () => api.listKnowledgeBases(w, { skip: 2, limit: 9 }), "GET", `${base}?skip=2&limit=9`],
  [
    "create",
    () => api.createKnowledgeBase(w, { name: "N", description: null }),
    "POST",
    base,
    { name: "N", description: null },
  ],
  ["get", () => api.getKnowledgeBase(w, b), "GET", kb],
  [
    "update",
    () => api.updateKnowledgeBase(w, b, { description: null }),
    "PATCH",
    kb,
    { description: null },
  ],
  ["delete", () => api.deleteKnowledgeBase(w, b), "DELETE", kb],
  [
    "documents",
    () => api.listDocuments(w, b, { skip: 1, limit: 3 }),
    "GET",
    `${kb}/documents?skip=1&limit=3`,
  ],
  ["upload", () => api.uploadDocument(w, b, file), "POST", `${kb}/documents`, file],
  ["document", () => api.getDocument(w, b, d), "GET", doc],
  ["content", () => api.getDocumentContent(w, b, d), "GET", `${doc}/content`],
  ["download", () => api.downloadDocument(w, b, d), "GET", `${doc}/download`],
  ["delete document", () => api.deleteDocument(w, b, d), "DELETE", doc],
  ["index", () => api.requestIndex(w, b, d), "POST", `${doc}/index`],
  ["index status", () => api.getIndexStatus(w, b, d), "GET", `${doc}/index`],
  [
    "search",
    () => api.search(w, b, { query: "q", top_k: 20, min_score: null }),
    "POST",
    `${kb}/search`,
    { query: "q", top_k: 20, min_score: null },
  ],
  ["ask", () => api.ask(w, b, { question: "q" }), "POST", `${kb}/ask`, { question: "q" }],
];
describe("15 wire operations", () => {
  it.each(cases)("%s", async (_name, run, method, url, body) => {
    await run();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [actual, opts] = fetchMock.mock.calls[0]!;
    expect(actual).toBe(url);
    expect(opts.method).toBe(method);
    expect(opts.cache).toBe("no-store");
    if (body === file) {
      expect(opts.body).toBeInstanceOf(FormData);
      const uploaded = opts.body.get("file") as File;
      expect(uploaded.name).toBe(file.name);
      expect(uploaded.type).toBe(file.type);
      expect(uploaded.size).toBe(3);
      expect(opts.headers.has("content-type")).toBe(false);
    } else expect(opts.body).toBe(body === undefined ? undefined : JSON.stringify(body));
    expect(String(opts.body)).not.toContain("actor_user_id");
  });
});
it("preserves 201 parse failure and empty 204", async () => {
  fetchMock
    .mockResolvedValueOnce(Response.json({ parse_status: "failed" }, { status: 201 }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  expect(await api.uploadDocument(w, b, file)).toEqual({ parse_status: "failed" });
  expect(await api.deleteDocument(w, b, d)).toBeNull();
});
it("refreshes multipart once using same file; no boundary override", async () => {
  fetchMock
    .mockResolvedValueOnce(Response.json({ detail: "expired" }, { status: 401 }))
    .mockResolvedValueOnce(Response.json({ access_token: "fresh" }))
    .mockResolvedValueOnce(Response.json({ parse_status: "ready" }));
  await api.uploadDocument(w, b, file);
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls[0]![1].body).toBe(fetchMock.mock.calls[2]![1].body);
  expect(fetchMock.mock.calls[2]![1].headers.has("content-type")).toBe(false);
});
it.each([403, 409, 422, 500, 502, 503])("does not retry upload for %s", async (status) => {
  fetchMock.mockResolvedValueOnce(
    Response.json(
      { error: { code: "DOCUMENT_TOO_LARGE", message: "large", details: { max: 10 } } },
      { status },
    ),
  );
  await expect(api.uploadDocument(w, b, file)).rejects.toMatchObject({ status });
  // 403 may revalidate membership, but never resubmits the upload.
  expect(fetchMock.mock.calls.filter(([, o]) => o.method === "POST")).toHaveLength(1);
});
it("reads only successful binary as Blob", async () => {
  const response = new Response(new Uint8Array([0, 255, 2]), {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": "attachment; filename*=utf-8''%E9%B1%BC.pdf",
    },
  });
  const json = vi.spyOn(response, "json"),
    text = vi.spyOn(response, "text");
  fetchMock.mockResolvedValueOnce(response);
  const result = await api.downloadDocument(w, b, d);
  expect(Array.from(new Uint8Array(await result.blob.arrayBuffer()))).toEqual([0, 255, 2]);
  expect(result.contentType).toBe("application/pdf");
  expect(result.contentDisposition).toContain("filename*=");
  expect(json).not.toHaveBeenCalled();
  expect(text).not.toHaveBeenCalled();
});
it.each([401, 403, 404])("preserves download JSON error %s", async (status) => {
  const data = { detail: [{ msg: "denied" }] };
  fetchMock.mockImplementation(() => Promise.resolve(Response.json(data, { status })));
  await expect(api.downloadDocument(w, b, d)).rejects.toMatchObject({ status, data });
});
it("preserves stable structured error codes", () => {
  const data = { error: { code: "KNOWLEDGE_AGENT_TIMEOUT", message: "timeout", details: {} } };
  const error = new ApiError(503, "timeout", data);
  expect(getKnowledgeErrorCode(error)).toBe("KNOWLEDGE_AGENT_TIMEOUT");
  expect(error.data).toBe(data);
  expect(getKnowledgeErrorCode(new Error("KNOWLEDGE_AGENT_TIMEOUT"))).toBeUndefined();
});
it("does not resend after cancellation during refresh", async () => {
  let finish!: (r: Response) => void;
  const refresh = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const controller = new AbortController();
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 401 })).mockReturnValueOnce(refresh);
  const request = api.getDocument(w, b, d, { signal: controller.signal });
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  controller.abort();
  finish(Response.json({ access_token: "late" }));
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
it.each(["logout", "switch"])("does not resend old request or set token after %s", async (mode) => {
  let finish!: (r: Response) => void;
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 401 })).mockReturnValueOnce(
    new Promise<Response>((r) => {
      finish = r;
    }),
  );
  const request = api.getDocument(w, b, d);
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  useAuthStore.getState().logout();
  if (mode === "switch")
    useAuthStore.setState({
      user: { id: "other" } as User,
      isAuthenticated: true,
      accessToken: "new-user",
    });
  finish(Response.json({ access_token: "old-user" }));
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(useAuthStore.getState().accessToken).not.toBe("old-user");
});
it("returns safe network errors", async () => {
  fetchMock.mockRejectedValueOnce(new Error("http://private/secret-key"));
  await expect(api.getKnowledgeBase(w, b)).rejects.toMatchObject({
    status: 0,
    message: "Network request failed",
  });
});
it("retains existing JSON client methods", async () => {
  await apiClient.put("/example", { n: 1 });
  expect(fetchMock.mock.calls[0]![1].body).toBe('{"n":1}');
});

it.each([true, false])(
  "resource 404 only clears workspace after confirmed membership loss: %s",
  async (revoked) => {
    const client = new QueryClient();
    const unbind = bindKnowledgeLifecycle(client);
    const key = qk.knowledge.content("u", w, b, d),
      other = qk.knowledge.content("u", "other", b, d);
    client.setQueryData(key, "secret");
    client.setQueryData(other, "keep");
    fetchMock
      .mockResolvedValueOnce(Response.json({ detail: "document missing" }, { status: 404 }))
      .mockResolvedValueOnce(
        Response.json(revoked ? { detail: "workspace missing" } : { id: w }, {
          status: revoked ? 404 : 200,
        }),
      );
    await expect(api.getDocument(w, b, d)).rejects.toMatchObject({ status: 404 });
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/workspaces/w%2F%E4%B8%80");
    expect(client.getQueryData(key)).toBe(revoked ? undefined : "secret");
    expect(client.getQueryData(other)).toBe("keep");
    unbind();
    client.clear();
  },
);
it("same user logout/login generation still blocks old refresh replay", async () => {
  let finish!: (r: Response) => void;
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 401 })).mockReturnValueOnce(
    new Promise<Response>((r) => {
      finish = r;
    }),
  );
  const request = api.getDocument(w, b, d);
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  useAuthStore.getState().logout();
  useAuthStore.setState({ user: { id: "u" } as User, isAuthenticated: true });
  finish(Response.json({ access_token: "old" }));
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("omits empty pagination and ignores extra query parameters", async () => {
  await api.listKnowledgeBases(w);
  expect(fetchMock.mock.calls[0]![0]).toBe(base);
  await api.listDocuments(w, b, { skip: 0, limit: 2, evil: 1 } as { skip: number; limit: number });
  expect(fetchMock.mock.calls[1]![0]).toBe(`${kb}/documents?skip=0&limit=2`);
});
it("does not leak body stream or JSON parse failures", async () => {
  const response = new Response("file");
  vi.spyOn(response, "blob").mockRejectedValue(new Error("http://secret key=private"));
  fetchMock.mockResolvedValueOnce(response);
  await expect(api.downloadDocument(w, b, d)).rejects.toMatchObject({
    message: "Network request failed",
  });
  fetchMock.mockResolvedValueOnce(new Response("private invalid JSON"));
  await expect(api.getKnowledgeBase(w, b)).rejects.toMatchObject({
    message: "Invalid server response",
  });
});
