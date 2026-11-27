// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET as ready } from "@/app/api/health/ready/route";
import { GET as basic } from "@/app/api/health/route";
import { parseReadiness } from "./health";
const fetchMock = vi.fn();
const body = (status = "ready") => ({
  status,
  timestamp: "2026-11-27T00:00:00+00:00",
  service: "agentforge",
  checks: {
    database: {
      status: status === "ready" ? "healthy" : "unhealthy",
      latency_ms: 1,
      ...(status === "ready" ? {} : { error: "DATABASE_TIMEOUT" }),
    },
    redis: { status: "healthy", latency_ms: 2 },
    worker: { status: "configured", connectivity_checked: false },
  },
});
beforeEach(() => vi.stubGlobal("fetch", fetchMock.mockReset()));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it.each([200, 503])("preserves valid readiness HTTP %s and nested failures", async (status) => {
  fetchMock.mockResolvedValue(
    Response.json(
      { ...body(status === 200 ? "ready" : "not_ready"), password: "must-not-relay" },
      { status },
    ),
  );
  const r = await ready();
  const data = await r.json();
  expect(r.status).toBe(status);
  expect(data.status).toBe(status === 200 ? "ready" : "not_ready");
  expect(data.database).toEqual(data.checks.database);
  if (status === 503) expect(data.database.error).toBe("DATABASE_TIMEOUT");
  expect(JSON.stringify(data)).not.toContain("must-not-relay");
  expect(r.headers.get("cache-control")).toBe("no-store");
  expect(fetchMock.mock.calls[0]![1]).toMatchObject({
    cache: "no-store",
    redirect: "error",
    signal: expect.any(AbortSignal),
  });
});
it.each([
  null,
  { status: "healthy" },
  { ...body(), status: "not_ready" },
  { ...body(), checks: { database: { status: "healthy" } } },
])("rejects malformed upstream data", async (value) => {
  fetchMock.mockResolvedValue(Response.json(value));
  const r = await ready();
  expect(r.status).toBe(502);
  expect(await r.json()).toEqual({ detail: "Invalid readiness response" });
});
it("sanitizes malformed 503 and arbitrary upstream errors", async () => {
  fetchMock
    .mockResolvedValueOnce(
      Response.json({ detail: "postgresql://u:secret@private/db" }, { status: 503 }),
    )
    .mockRejectedValueOnce(new Error("private upstream"));
  expect((await ready()).status).toBe(502);
  const r = await ready();
  expect(r.status).toBe(503);
  expect(JSON.stringify(await r.json())).not.toMatch(/private|secret/);
});
it("enforces a finite abort budget without waiting for a real network", async () => {
  const c = new AbortController();
  const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(c.signal);
  fetchMock.mockImplementation(
    (_url, options) =>
      new Promise((_resolve, reject) =>
        options.signal.addEventListener("abort", () => reject(new Error("synthetic timeout"))),
      ),
  );
  const pending = ready();
  c.abort();
  expect((await pending).status).toBe(503);
  expect(timeout).toHaveBeenCalledWith(6000);
});
it("keeps basic health compatible, bounded and uncached", async () => {
  fetchMock.mockResolvedValue(Response.json({ status: "healthy", max_upload_size_mb: 50 }));
  const r = await basic();
  expect(await r.json()).toEqual({ status: "healthy", max_upload_size_mb: 50 });
  expect(fetchMock.mock.calls[0]![1]).toMatchObject({
    cache: "no-store",
    signal: expect.any(AbortSignal),
  });
});
it("allowlists safe check fields and never invents separate vector health", () => {
  const value = body("not_ready");
  const raw = {
    ...value,
    checks: {
      ...value.checks,
      database: {
        status: "unhealthy",
        error: "password=secret",
        stack: "private-host",
        latency_ms: Infinity,
      },
      llm: { status: "unknown" },
      vector_store: { status: "healthy" },
    },
  };
  const parsed = parseReadiness(raw);
  expect(parsed?.checks.database.error).toBe("DEPENDENCY_CHECK_FAILED");
  expect(parsed?.checks.database.latency_ms).toBeUndefined();
  expect(JSON.stringify(parsed)).not.toMatch(/secret|private-host|vector_store/);
});
