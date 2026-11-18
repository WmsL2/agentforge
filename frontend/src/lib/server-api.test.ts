// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { backendFetch } from "./server-api";
import { NextRequest } from "next/server";
import { POST as upload } from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/route";
import { GET as download } from "@/app/api/workspaces/[workspaceId]/knowledge-bases/[knowledgeBaseId]/documents/[documentId]/download/route";
const mock = vi.fn();
beforeEach(() => vi.stubGlobal("fetch", mock.mockReset()));
afterEach(() => vi.unstubAllGlobals());
it("retains JSON/raw text/empty behavior", async () => {
  mock
    .mockResolvedValueOnce(Response.json({ n: 1 }))
    .mockResolvedValueOnce(new Response("raw text"))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  expect(await backendFetch("/test")).toEqual({ n: 1 });
  expect(await backendFetch("/test", { raw: true })).toBe("raw text");
  expect(await backendFetch("/test")).toBeNull();
});
it("returns untouched Response and does not consume body", async () => {
  const response = new Response(new Uint8Array([0, 255]));
  const text = vi.spyOn(response, "text"),
    json = vi.spyOn(response, "json");
  mock.mockResolvedValueOnce(response);
  expect(await backendFetch("/file", { rawResponse: true })).toBe(response);
  expect(response.bodyUsed).toBe(false);
  expect(text).not.toHaveBeenCalled();
  expect(json).not.toHaveBeenCalled();
});
it.each([401, 403, 404, 422])(
  "rawResponse still throws structured BackendApiError %s",
  async (status) => {
    const data = { detail: [{ msg: "invalid" }] };
    mock.mockResolvedValueOnce(Response.json(data, { status }));
    await expect(backendFetch("/file", { rawResponse: true })).rejects.toMatchObject({
      status,
      data,
    });
  },
);
it("real multipart proxy/server client preserves Unicode filename, MIME and bytes", async () => {
  const form = new FormData();
  form.append(
    "file",
    new File([new Uint8Array([0, 255, 1, 128])], "资料.txt", {
      type: "text/plain",
    }),
  );
  const req = new NextRequest("https://app.test/api/upload", {
    method: "POST",
    headers: { cookie: "access_token=real" },
    body: form,
  });
  mock.mockImplementationOnce(async (_url: string, options: RequestInit) => {
    expect(options.cache).toBe("no-store");
    expect(options.redirect).toBe("error");
    expect(new Headers(options.headers).has("content-type")).toBe(false);
    const outgoing = new Request("https://backend.test/file", {
      method: "POST",
      body: options.body,
      headers: options.headers,
    });
    expect(outgoing.headers.get("content-type")).toContain("boundary=");
    const file = (await outgoing.formData()).get("file") as File;
    expect(file.name).toBe("资料.txt");
    expect(file.type).toBe("text/plain");
    expect(Array.from(new Uint8Array(await file.arrayBuffer()))).toEqual([0, 255, 1, 128]);
    return Response.json({ parse_status: "failed" }, { status: 201 });
  });
  const response = await upload(req, {
    params: Promise.resolve({ workspaceId: "w", knowledgeBaseId: "b" }),
  });
  expect(response.status).toBe(201);
  expect(await response.json()).toEqual({ parse_status: "failed" });
});
it("real binary path streams exact bytes and rejects upstream redirect without leaking URL", async () => {
  mock.mockResolvedValueOnce(
    new Response(new Uint8Array([0, 128, 255]), {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": "attachment; filename=test.pdf",
      },
    }),
  );
  const params = {
    params: Promise.resolve({ workspaceId: "w", knowledgeBaseId: "b", documentId: "d" }),
  };
  const req = () =>
    new NextRequest("https://app.test/api/download", { headers: { cookie: "access_token=real" } });
  const response = await download(req(), params);
  expect(Array.from(new Uint8Array(await response.arrayBuffer()))).toEqual([0, 128, 255]);
  expect(mock.mock.calls[0]![1]).toMatchObject({
    redirect: "error",
    cache: "no-store",
    headers: { Authorization: "Bearer real" },
  });
  mock.mockRejectedValueOnce(new TypeError("redirect http://private/secret"));
  const failed = await download(req(), params);
  expect(failed.status).toBe(502);
  expect(await failed.text()).not.toMatch(/private|secret/);
});
