import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { blockAuthProbes } from "@/lib/auth-transition";
import { workflowRunReadKey, workflowRunReadRetry } from "@/lib/workflow/workflow-run-lifecycle";
import { ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import {
  useWorkflowRun,
  useWorkflowRuns,
  useWorkflowRunSteps,
  useWorkflowTrace,
} from "./use-workflow-runs";

const user = {
  id: "a",
  email: "a@test",
  role: "user" as const,
  is_active: true,
  created_at: "now",
};
let client: QueryClient;
const fetchMock = vi.fn();
function useReads() {
  return [
    useWorkflowRuns("a", "wf", 0, 10),
    useWorkflowRun("a", "wf", "run"),
    useWorkflowRunSteps("a", "wf", "run", "completed"),
    useWorkflowTrace("a", "wf", "run", "completed"),
  ];
}
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  useAuthStore.getState().setUser(user);
  client = new QueryClient({
    defaultOptions: { queries: { staleTime: 5 * 60 * 1000, gcTime: 30 * 60 * 1000, retry: false } },
  });
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.unstubAllGlobals();
  useAuthStore.getState().setUser(null);
});

it("all four reads reject a request-user mismatch even on forced refetch before HTTP", async () => {
  useAuthStore.getState().setUser({ ...user, id: "b" });
  const { result } = renderHook(useReads, { wrapper });
  let outcomes: PromiseSettledResult<unknown>[] = [];
  await act(async () => {
    outcomes = await Promise.allSettled(
      result.current.map((query) => query.refetch({ throwOnError: true })),
    );
  });
  expect(outcomes).toHaveLength(4);
  for (const outcome of outcomes) {
    expect(outcome.status).toBe("rejected");
    if (outcome.status === "rejected") expect(outcome.reason.name).toBe("AbortError");
  }
  expect(fetchMock).not.toHaveBeenCalled();
});
it("QueryClient cancellation aborts all four transport signals and prevents cache adoption", async () => {
  const resolve: ((value: Response) => void)[] = [];
  fetchMock.mockImplementation(() => new Promise<Response>((r) => resolve.push(r)));
  renderHook(useReads, { wrapper });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  const signals = fetchMock.mock.calls.map(([, options]) => options.signal as AbortSignal);
  await act(async () => {
    await client.cancelQueries({ queryKey: qk.workflowRuns.workflow("a", "wf") });
  });
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  await act(async () => {
    for (const complete of resolve) complete(Response.json({ secret: "CANCELLED" }));
  });
  const queries = client.getQueryCache().getAll();
  const protectedQueries = queries.filter(
    (query) => query.queryKey.at(-1) !== "authorization-denied",
  );
  expect(protectedQueries).toHaveLength(4);
  expect(protectedQueries.every((query) => query.state.data === undefined)).toBe(true);
  const denialQueries = queries.filter((query) => query.queryKey.at(-1) === "authorization-denied");
  expect(denialQueries).toHaveLength(4);
  expect(denialQueries.every((query) => query.state.data === false)).toBe(true);
});
it.each([403, 404])("never automatically retries access denial %s", (status) => {
  expect(workflowRunReadRetry(0, new ApiError(status, "denied"))).toBe(false);
});
it("never retries AbortError", () => {
  expect(workflowRunReadRetry(0, new DOMException("cancelled", "AbortError"))).toBe(false);
});
it("retains one retry for temporary HTTP/network errors", () => {
  for (const error of [
    new ApiError(500, "temporary"),
    new ApiError(503, "temporary"),
    new ApiError(0, "network"),
    new TypeError("network"),
  ]) {
    expect(workflowRunReadRetry(0, error)).toBe(true);
    expect(workflowRunReadRetry(1, error)).toBe(false);
  }
});
it("transition epoch partitions cache keys independently of user ID", () => {
  const key = qk.workflowRuns.detail("a", "wf", "run");
  const before = workflowRunReadKey(key);
  blockAuthProbes();
  expect(workflowRunReadKey(key)).not.toEqual(before);
});
it("an identity change while consuming the HTTP response body cannot commit data", async () => {
  let finish!: (text: string) => void;
  const body = new Promise<string>((r) => {
    finish = r;
  });
  const response = Response.json({});
  const consumeBody = vi.fn(() => body);
  response.text = consumeBody;
  fetchMock.mockResolvedValue(response);
  const { result } = renderHook(() => useWorkflowRun("a", "wf", "run"), { wrapper });
  await waitFor(() => expect(consumeBody).toHaveBeenCalledOnce());
  const oldKey = workflowRunReadKey(qk.workflowRuns.detail("a", "wf", "run"));
  await act(async () => {
    useAuthStore.getState().logout();
    finish('{"secret":"OLD-BODY"}');
  });
  expect(result.current.data).toBeUndefined();
  expect(client.getQueryData(oldKey)).toBeUndefined();
});
