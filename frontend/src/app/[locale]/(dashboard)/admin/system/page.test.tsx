import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-client";
import Page from "./page";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {
    constructor(
      public status: number,
      message: string,
      public data?: unknown,
    ) {
      super(message);
    }
  },
  apiClient: { get },
}));
vi.mock("@/components/ui", async () => ({
  Button: (await import("@/components/ui/button")).Button,
}));
vi.mock("@/components/states", () => ({ LoadingState: () => <div>Loading health</div> }));
const data = (status = "ready") => ({
  status,
  timestamp: "2026-11-27T00:00:00Z",
  service: "agentforge",
  checks: {
    database: {
      status: status === "ready" ? "healthy" : "unhealthy",
      latency_ms: 3,
      ...(status === "ready" ? {} : { error: "DATABASE_CONNECTION_FAILED" }),
    },
    redis: { status: "healthy", latency_ms: 2 },
    llm: { status: "configured", connectivity_checked: false },
    embedding: { status: "not_configured", connectivity_checked: false },
    worker: { status: "unknown", connectivity_checked: false },
    knowledge_agent: { status: "not_configured", enabled: false, connectivity_checked: false },
  },
});
beforeEach(() => {
  get.mockReset();
});
afterEach(() => vi.useRealTimers());
it("renders actual ready/configured/unknown states without uptime or unsupported services", async () => {
  get.mockResolvedValue(data());
  render(<Page />);
  await screen.findByText("API dependencies ready");
  expect(screen.getByText("Configured")).toBeInTheDocument();
  expect(screen.getByText("Unknown")).toBeInTheDocument();
  expect(screen.getByText("Single probe: 3ms")).toBeInTheDocument();
  expect(screen.getByText("PostgreSQL / pgvector")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(
    /90d|p50|99\.|Stripe|All systems operational|Vector store/,
  );
  expect(get).toHaveBeenCalledWith(
    "/health/ready",
    expect.objectContaining({ signal: expect.any(AbortSignal), cache: "no-store" }),
  );
});
it("keeps valid 503 details and never falls back to basic health", async () => {
  get.mockRejectedValue(new ApiError(503, "Unavailable", data("not_ready")));
  render(<Page />);
  await screen.findByText("API not ready");
  expect(screen.getByText("DATABASE_CONNECTION_FAILED")).toBeInTheDocument();
  expect(screen.getByText("Unhealthy")).toBeInTheDocument();
  expect(get.mock.calls.every(([path]) => path === "/health/ready")).toBe(true);
});
it("failed refresh removes old readiness, sanitizes errors and supports manual refresh", async () => {
  get.mockResolvedValueOnce(data()).mockRejectedValueOnce(new Error("private-host secret"));
  render(<Page />);
  await screen.findByText("API dependencies ready");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText("Readiness unavailable");
  expect(screen.queryByText("API dependencies ready")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/private-host|secret/);
});
it("does not overlap periodic/manual requests and aborts on unmount", async () => {
  vi.useFakeTimers();
  let resolve!: (value: unknown) => void;
  get.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const { unmount } = render(<Page />);
  expect(get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => {
    vi.advanceTimersByTime(30_000);
  });
  expect(get).toHaveBeenCalledTimes(1);
  const signal = get.mock.calls[0]![1].signal;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(data()));
});
it("periodic refresh remains useful after a completed request", async () => {
  vi.useFakeTimers();
  get.mockResolvedValue(data());
  render(<Page />);
  await act(async () => {});
  expect(get).toHaveBeenCalledTimes(1);
  await act(async () => {
    vi.advanceTimersByTime(30_000);
  });
  expect(get).toHaveBeenCalledTimes(2);
});
it("stale StrictMode request cannot replace a newer result", async () => {
  let first!: (value: unknown) => void;
  let second!: (value: unknown) => void;
  get
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          first = r;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          second = r;
        }),
    );
  render(
    <StrictMode>
      <Page />
    </StrictMode>,
  );
  await act(async () => second(data()));
  await screen.findByText("API dependencies ready");
  await act(async () => first(data("not_ready")));
  expect(screen.queryByText("API not ready")).not.toBeInTheDocument();
});
