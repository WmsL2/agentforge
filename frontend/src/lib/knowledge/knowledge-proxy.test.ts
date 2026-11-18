// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import * as bases from "@/app/api/workspaces/[workspaceId]/knowledge-bases/route";
import * as base from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/route";
import * as docs from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/route";
import * as doc from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/[documentId]/route";
import * as content from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/[documentId]/content/route";
import * as download from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/[documentId]/download/route";
import * as index from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/[documentId]/index/route";
import * as search from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/search/route";
import * as ask from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/ask/route";
import { backendFetch, BackendApiError } from "@/lib/server-api";
vi.mock("@/lib/server-api", async (original) => {
  const actual = await original<typeof import("@/lib/server-api")>();
  return { ...actual, backendFetch: vi.fn() };
});
const mock = vi.mocked(backendFetch);
const params = {
  params: Promise.resolve({ workspaceId: "w/一", knowledgeBaseId: "b?#", documentId: "d/%" }),
};
const root = "/api/v1/workspaces/w%2F%E4%B8%80/knowledge-bases",
  kb = `${root}/b%3F%23`,
  dp = `${kb}/documents/d%2F%25`;
const binary = () =>
  new Response(new Uint8Array([0, 255, 1]), {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": "inline; filename*=utf-8''%E9%B1%BC.pdf",
      "set-cookie": "secret=yes",
      authorization: "secret",
      location: "http://private",
    },
  });
function req(method = "GET", headers: Record<string, string> = {}, body?: string) {
  return new NextRequest("https://app.test/api/test?skip=2&limit=9&evil=1", {
    method,
    headers: { cookie: "access_token=real", ...headers },
    body,
  });
}
// Every handler uses only its own required subset of params.
const cases = [
  [bases.GET, "GET", root, 200],
  [bases.POST, "POST", root, 201],
  [base.GET, "GET", kb, 200],
  [base.PATCH, "PATCH", kb, 200],
  [base.DELETE, "DELETE", kb, 204],
  [docs.GET, "GET", `${kb}/documents`, 200],
  [docs.POST, "POST", `${kb}/documents`, 201],
  [doc.GET, "GET", dp, 200],
  [content.GET, "GET", `${dp}/content`, 200],
  [download.GET, "GET", `${dp}/download`, 200],
  [doc.DELETE, "DELETE", dp, 204],
  [index.POST, "POST", `${dp}/index`, 202],
  [index.GET, "GET", `${dp}/index`, 200],
  [search.POST, "POST", `${kb}/search`, 200],
  [ask.POST, "POST", `${kb}/ask`, 200],
] as const;
beforeEach(() => {
  mock.mockReset().mockResolvedValue({ parse_status: "failed" });
});
afterEach(() => vi.unstubAllGlobals());
async function multipart() {
  const raw =
    '--bound\r\nContent-Disposition: form-data; name="file"; filename="fish.txt"\r\nContent-Type: text/plain\r\n\r\nfish bytes\r\n--bound--\r\n';
  const request = req("POST", { "content-type": "multipart/form-data; boundary=bound" }, raw);
  return request;
}
it.each(cases)("fixed route %s %s", async (handler, method, path, status) => {
  const request =
    handler === docs.POST
      ? await multipart()
      : req(
          method,
          { authorization: "Bearer forged" },
          method === "POST" || method === "PATCH" ? "{}" : undefined,
        );
  if (handler === download.GET) mock.mockResolvedValueOnce(binary());
  const response = await handler(request, params);
  expect(response.status).toBe(status);
  expect(response.headers.get("cache-control")).toContain("no-store");
  expect(mock).toHaveBeenCalledTimes(1);
  const [url, opts] = mock.mock.calls[0]!;
  expect(url).toBe(path);
  expect(opts).toMatchObject({
    method,
    headers: { Authorization: "Bearer real" },
    cache: "no-store",
    redirect: "error",
  });
  if (handler === bases.GET || handler === docs.GET)
    expect(opts?.params).toEqual({ skip: "2", limit: "9" });
  else expect(opts?.params).toBeUndefined();
  if (status === 204) expect(await response.text()).toBe("");
  if (handler === docs.POST) {
    const file = (opts?.body as FormData).get("file") as File;
    expect(file.name).toBe("fish.txt");
    expect(file.type).toBe("text/plain");
    expect(await file.text()).toBe("fish bytes");
    expect(await response.json()).toEqual({ parse_status: "failed" });
  }
});
it.each(cases)("cookie authentication %s %s", async (handler, method) => {
  const response = await handler(
    req(method, { cookie: "", authorization: "Bearer forged" }),
    params,
  );
  expect(response.status).toBe(401);
  expect(mock).not.toHaveBeenCalled();
});
it.each(cases.filter(([, method]) => method !== "GET"))(
  "CSRF before parsing or backend %s %s",
  async (handler, method) => {
    const request = req(method, { origin: "https://evil.test" });
    const parse = vi.spyOn(request, "formData");
    const response = await handler(request, params);
    expect(response.status).toBe(403);
    expect(mock).not.toHaveBeenCalled();
    expect(parse).not.toHaveBeenCalled();
  },
);
it("rejects sec-fetch-site cross-site upload", async () => {
  expect((await docs.POST(req("POST", { "sec-fetch-site": "cross-site" }), params)).status).toBe(
    403,
  );
  expect(mock).not.toHaveBeenCalled();
});
it("handles malformed multipart and missing file safely", async () => {
  expect(
    (await docs.POST(req("POST", { "content-type": "multipart/form-data" }, "broken"), params))
      .status,
  ).toBe(400);
  expect(
    (
      await docs.POST(
        req("POST", { "content-type": "multipart/form-data; boundary=b" }, "--b--\r\n"),
        params,
      )
    ).status,
  ).toBe(422);
  expect(mock).not.toHaveBeenCalled();
});
it("streams binary, preserves Unicode filename, only forwards safe headers", async () => {
  mock.mockResolvedValueOnce(binary());
  const response = await download.GET(req(), params);
  expect(Array.from(new Uint8Array(await response.arrayBuffer()))).toEqual([0, 255, 1]);
  expect(response.headers.get("content-type")).toBe("application/pdf");
  expect(response.headers.get("content-disposition")).toBe(
    "attachment; filename*=utf-8''%E9%B1%BC.pdf",
  );
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  for (const header of ["set-cookie", "authorization", "location"])
    expect(response.headers.has(header)).toBe(false);
  expect(mock.mock.calls[0]![1]?.rawResponse).toBe(true);
});
it.each([401, 403, 404, 422, 503])("forwards structured errors %s", async (status) => {
  const data =
    status === 422
      ? { detail: [{ msg: "invalid", loc: ["body", "question"] }] }
      : { error: { code: "KNOWLEDGE_AGENT_TIMEOUT", message: "timeout", details: {} } };
  mock.mockRejectedValueOnce(new BackendApiError(status, "error", data));
  const response = await download.GET(req(), params);
  expect(response.status).toBe(status);
  expect(await response.json()).toEqual(data);
  expect(response.headers.get("cache-control")).toBe("no-store");
});
it("returns safe gateway errors", async () => {
  mock.mockRejectedValueOnce(new Error("secret http://internal key"));
  const response = await base.GET(req(), params);
  expect(response.status).toBe(502);
  expect(await response.text()).not.toMatch(/secret|internal/);
});
it("index submission forwards no invented configuration", async () => {
  await index.POST(req("POST"), params);
  expect(mock.mock.calls[0]![1]?.body).toBeUndefined();
});
