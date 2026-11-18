// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest, type NextResponse } from "next/server";
import { QueryClient } from "@tanstack/react-query";
import { apiClient } from "./api-client";
import { useAuthStore } from "@/stores/auth-store";
import { authTransitionEpoch } from "./auth-transition";
import { knowledgeApi } from "./knowledge/knowledge-api";
import { bindKnowledgeLifecycle } from "./knowledge/knowledge-lifecycle";
import { qk } from "./query-keys";
import { POST as refresh } from "@/app/api/auth/refresh/route";
import { GET as me } from "@/app/api/auth/me/route";
import { POST as login } from "@/app/api/auth/login/route";
import { POST as logout } from "@/app/api/auth/logout/route";
import { POST as oauth } from "@/app/api/auth/oauth-callback/route";
import { POST as magic } from "@/app/api/auth/magic-link/verify/route";
import { backendFetch, BackendApiError } from "./server-api";
import type { User } from "@/types";
vi.mock("./server-api", async (original) => ({
  ...(await original<typeof import("./server-api")>()),
  backendFetch: vi.fn(),
}));
const backend = vi.mocked(backendFetch);
const A: User = { id: "A", email: "a@test", is_active: true, created_at: "2026-11-18" };
const B: User = { ...A, id: "B", email: "b@test" };
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
const outcome = <T>(promise: Promise<T>) =>
  promise.then(
    (data) => ({ data, error: undefined }),
    (error) => ({ data: undefined, error: error as Error }),
  );
let jar: Map<string, string>,
  sent: string[],
  logoutTokens: string[],
  client: QueryClient,
  unbind: () => void;
const realBackend = async (
  path: string,
  opts?: Parameters<typeof backendFetch>[1],
): Promise<unknown> => {
  if (path === "/api/v1/auth/login" || path === "/api/v1/auth/magic-link/verify")
    return { access_token: "b", refresh_token: "rb" };
  if (path === "/api/v1/auth/me") {
    const token = new Headers(opts?.headers).get("authorization");
    if (token?.includes("b")) return B;
    return A;
  }
  if (path === "/api/v1/auth/refresh") {
    const payload = JSON.parse(String(opts?.body)) as { refresh_token: string };
    return payload.refresh_token === "rb"
      ? { access_token: "b2", refresh_token: "rb2" }
      : { access_token: "a2", refresh_token: "ra2" };
  }
  if (path === "/api/v1/auth/logout") {
    logoutTokens.push((JSON.parse(String(opts?.body)) as { refresh_token: string }).refresh_token);
    return null;
  }
  throw new Error("Unexpected backend path");
};
beforeEach(() => {
  jar = new Map([
    ["access_token", "a"],
    ["refresh_token", "ra"],
  ]);
  sent = [];
  logoutTokens = [];
  useAuthStore.getState().setUser(A);
  useAuthStore.getState().setAccessToken("a");
  client = new QueryClient();
  unbind = bindKnowledgeLifecycle(client);
  backend.mockReset().mockImplementation(realBackend);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options: RequestInit = {}) => {
      const path = new URL(url, "https://app.test").pathname;
      sent.push(path);
      if (path.includes("/knowledge-bases"))
        return Response.json({ detail: "expired" }, { status: 401 });
      const request = new NextRequest(`https://app.test${path}`, {
        ...options,
        signal: options.signal ?? undefined,
        headers: {
          cookie: Array.from(jar)
            .map(([k, v]) => `${k}=${v}`)
            .join("; "),
          "content-type": "application/json",
        },
      });
      const handlers: Record<string, (r: NextRequest) => Promise<NextResponse>> = {
        "/api/auth/refresh": refresh,
        "/api/auth/me": me,
        "/api/auth/login": login,
        "/api/auth/logout": logout,
        "/api/auth/oauth-callback": oauth,
        "/api/auth/magic-link/verify": magic,
      };
      const handler = handlers[path];
      if (!handler) throw new Error("Unexpected browser path");
      const response = await handler(request);
      // Browser model: real route Set-Cookie applies before JS observes the response.
      // Generation checks cannot undo this side effect; ordering must prevent overlap.
      for (const cookie of response.cookies.getAll()) {
        if (cookie.maxAge === 0) jar.delete(cookie.name);
        else jar.set(cookie.name, cookie.value);
      }
      return response;
    }),
  );
});
afterEach(() => {
  unbind();
  client.clear();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});
it.each(["/auth/login", "/auth/oauth-callback", "/auth/magic-link/verify"])(
  "coordinates sign-in entry %s and logout",
  async (endpoint) => {
    await apiClient.post(endpoint, {
      email: "b@test",
      password: "fake",
      access_token: "b",
      refresh_token: "rb",
      token: "fake",
    });
    expect(useAuthStore.getState().user?.id).toBe("B");
    expect(jar.get("access_token")).toBe("b");
    await apiClient.post("/auth/logout");
    expect(useAuthStore.getState().user).toBeNull();
    expect(jar.size).toBe(0);
    await useAuthStore.getState().checkAuth();
    expect(sent.filter((p) => p === "/api/auth/me")).toHaveLength(0);
  },
);
it("drains old refresh cookies before logout, invalidates Knowledge immediately and never replays old work", async () => {
  const pending = deferred<unknown>();
  backend.mockImplementation((path, opts) =>
    path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
  );
  const key = qk.knowledge.content("A", "w", "kb", "d");
  client.setQueryData(key, "private");
  const old = outcome(knowledgeApi.getKnowledgeBase("w", "kb"));
  await vi.waitFor(() => expect(sent).toContain("/api/auth/refresh"));
  const exit = apiClient.post("/auth/logout");
  expect(useAuthStore.getState().user).toBeNull();
  expect(client.getQueryData(key)).toBeUndefined();
  await useAuthStore.getState().checkAuth();
  expect(sent).not.toContain("/api/auth/me");
  expect(sent).not.toContain("/api/auth/logout");
  pending.resolve({ access_token: "a2", refresh_token: "ra2" });
  expect((await old).error?.name).toBe("AbortError");
  await exit;
  expect(logoutTokens).toEqual(["ra2"]);
  expect(jar.size).toBe(0);
  expect(sent.filter((p) => p.includes("knowledge-bases"))).toHaveLength(1);
});
it.each([false, true])(
  "old refresh success/error cookies settle before new login: error=%s",
  async (failure) => {
    const pending = deferred<unknown>();
    backend.mockImplementation((path, opts) =>
      path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
    );
    const old = outcome(apiClient.post("/auth/refresh"));
    await vi.waitFor(() => expect(sent).toContain("/api/auth/refresh"));
    const next = apiClient.post("/auth/login", { email: "b@test", password: "fake" });
    expect(useAuthStore.getState().user).toBeNull();
    expect(sent).not.toContain("/api/auth/login");
    if (failure) pending.reject(new BackendApiError(401, "expired"));
    else pending.resolve({ access_token: "a2", refresh_token: "ra2" });
    expect((await old).error?.name).toBe("AbortError");
    await next;
    expect(jar.get("access_token")).toBe("b");
    expect(jar.get("refresh_token")).toBe("rb");
    expect(useAuthStore.getState().user?.id).toBe("B");
    expect(useAuthStore.getState().accessToken).toBe("b");
  },
);
it("old /me refresh and queued probes cannot restore identity during logout", async () => {
  const pending = deferred<unknown>();
  jar.delete("access_token");
  backend.mockImplementation((path, opts) =>
    path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
  );
  const old = outcome(apiClient.get("/auth/me"));
  await vi.waitFor(() => expect(sent).toContain("/api/auth/me"));
  const queued = outcome(apiClient.get("/auth/me"));
  const exit = apiClient.post("/auth/logout");
  await useAuthStore.getState().checkAuth();
  pending.resolve({ access_token: "a2", refresh_token: "ra2" });
  await exit;
  expect((await old).error?.name).toBe("AbortError");
  expect((await queued).error?.name).toBe("AbortError");
  expect(sent.filter((p) => p === "/api/auth/me")).toHaveLength(1);
  expect(useAuthStore.getState().user).toBeNull();
  expect(jar.size).toBe(0);
});
it("late /me error cannot clear a newer login's cookies or user", async () => {
  const pending = deferred<unknown>();
  jar.delete("access_token");
  backend.mockImplementation((path, opts) =>
    path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
  );
  const old = outcome(apiClient.get("/auth/me"));
  await vi.waitFor(() => expect(sent).toContain("/api/auth/me"));
  const next = apiClient.post("/auth/login", { email: "b@test", password: "fake" });
  pending.reject(new BackendApiError(401, "expired"));
  await old;
  await next;
  expect(jar.get("access_token")).toBe("b");
  expect(useAuthStore.getState().user?.id).toBe("B");
});
it("a cancelled cookie writer still holds the barrier until its response arrives", async () => {
  const pending = deferred<unknown>();
  backend.mockImplementation((path, opts) =>
    path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
  );
  const controller = new AbortController();
  const old = outcome(apiClient.post("/auth/refresh", undefined, { signal: controller.signal }));
  await vi.waitFor(() => expect(sent).toContain("/api/auth/refresh"));
  controller.abort();
  const next = apiClient.post("/auth/login", { email: "b@test", password: "fake" });
  await Promise.resolve();
  expect(sent).not.toContain("/api/auth/login");
  pending.resolve({ access_token: "a2", refresh_token: "ra2" });
  await old;
  await next;
  expect(jar.get("access_token")).toBe("b");
});
it("new session uses its own refresh flight and never waits for/reuses old result", async () => {
  const pending = deferred<unknown>();
  let first = true;
  backend.mockImplementation((path, opts) => {
    if (path === "/api/v1/auth/refresh" && first) {
      first = false;
      return pending.promise;
    }
    return realBackend(path, opts);
  });
  const old = outcome(knowledgeApi.getKnowledgeBase("w", "kb"));
  await vi.waitFor(() => expect(sent).toContain("/api/auth/refresh"));
  const next = apiClient.post("/auth/login", { email: "b@test", password: "fake" });
  pending.resolve({ access_token: "a2", refresh_token: "ra2" });
  await old;
  await next;
  const epoch = authTransitionEpoch();
  await expect(knowledgeApi.getKnowledgeBase("w", "kb")).rejects.toMatchObject({ status: 401 });
  expect(authTransitionEpoch()).toBe(epoch);
  expect(jar.get("access_token")).toBe("b2");
  expect(sent.filter((p) => p === "/api/auth/refresh")).toHaveLength(2);
  expect(useAuthStore.getState().user?.id).toBe("B");
});
it("parallel same-session Knowledge 401s share one refresh and retry only once", async () => {
  const pending = deferred<unknown>();
  backend.mockImplementation((path, opts) =>
    path === "/api/v1/auth/refresh" ? pending.promise : realBackend(path, opts),
  );
  const a = outcome(knowledgeApi.getKnowledgeBase("w", "one")),
    b = outcome(knowledgeApi.getKnowledgeBase("w", "two"));
  await vi.waitFor(() => expect(sent.filter((p) => p === "/api/auth/refresh")).toHaveLength(1));
  pending.resolve({ access_token: "a2" });
  expect((await a).error).toMatchObject({ status: 401 });
  expect((await b).error).toMatchObject({ status: 401 });
  expect(sent.filter((p) => p === "/api/auth/refresh")).toHaveLength(1);
  expect(sent.filter((p) => p.includes("knowledge-bases"))).toHaveLength(4);
});

it("executes queued Logout with A's rotated token before Login B even after epoch changes", async () => {
  const refreshPending = deferred<unknown>();
  const logoutPending = deferred<unknown>();
  backend.mockImplementation((path, opts) => {
    if (path === "/api/v1/auth/refresh") return refreshPending.promise;
    if (path === "/api/v1/auth/logout") {
      logoutTokens.push(
        (JSON.parse(String(opts?.body)) as { refresh_token: string }).refresh_token,
      );
      return logoutPending.promise;
    }
    return realBackend(path, opts);
  });
  const oldRefresh = outcome(apiClient.post("/auth/refresh"));
  await vi.waitFor(() => expect(sent).toEqual(["/api/auth/refresh"]));
  const oldLogout = outcome(apiClient.post("/auth/logout"));
  const newLogin = apiClient.post("/auth/login", { email: "b@test", password: "fake" });
  expect(sent).toEqual(["/api/auth/refresh"]);
  refreshPending.resolve({ access_token: "a2", refresh_token: "ra2" });
  try {
    await vi.waitFor(() => expect(sent).toEqual(["/api/auth/refresh", "/api/auth/logout"]));
    expect(logoutTokens).toEqual(["ra2"]);
    expect(jar.get("access_token")).toBe("a2");
    expect(jar.get("refresh_token")).toBe("ra2");
    expect(useAuthStore.getState().user).toBeNull();
  } finally {
    logoutPending.resolve(null);
    await newLogin;
    await oldRefresh;
    await oldLogout;
  }
  expect(sent).toEqual(["/api/auth/refresh", "/api/auth/logout", "/api/auth/login"]);
  expect((await oldRefresh).error?.name).toBe("AbortError");
  expect((await oldLogout).error?.name).toBe("AbortError");
  expect(jar.get("access_token")).toBe("b");
  expect(jar.get("refresh_token")).toBe("rb");
  expect(useAuthStore.getState().user?.id).toBe("B");
  expect(useAuthStore.getState().accessToken).toBe("b");
});

it("rejects A's late ordinary 401 before refreshing or retrying under B", async () => {
  const pending = deferred<Response>();
  const transport = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url, options) =>
    url === "/api/users/me" ? pending.promise : transport(url, options),
  );
  const old = outcome(apiClient.get("/users/me"));
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/users/me")).toHaveLength(1);
  await apiClient.post("/auth/login", { email: "b@test", password: "fake" });
  const epoch = authTransitionEpoch();
  pending.resolve(Response.json({ detail: "A expired" }, { status: 401 }));
  expect((await old).error?.name).toBe("AbortError");
  expect(sent).toEqual(["/api/auth/login"]);
  expect(backend.mock.calls.filter(([path]) => path === "/api/v1/auth/refresh")).toHaveLength(0);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/users/me")).toHaveLength(1);
  expect(authTransitionEpoch()).toBe(epoch);
  expect(jar.get("access_token")).toBe("b");
  expect(jar.get("refresh_token")).toBe("rb");
  expect(useAuthStore.getState().user?.id).toBe("B");
  expect(useAuthStore.getState().accessToken).toBe("b");
});
