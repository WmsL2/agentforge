import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  ApiError,
  apiClient,
  getApiErrorMessage,
} from "./api-client";

describe("getApiErrorMessage", () => {
  it("returns a string detail", () => {
    expect(
      getApiErrorMessage({
        detail: "Invalid credentials",
      }),
    ).toBe("Invalid credentials");
  });

  it("normalizes FastAPI validation errors", () => {
    expect(
      getApiErrorMessage({
        detail: [
          {
            type: "value_error",
            loc: [
              "body",
              "username",
            ],
            msg: "Invalid email address",
            input:
              "dev@agentforge.local",
          },
        ],
      }),
    ).toBe("Invalid email address");
  });

  it("normalizes nested error objects", () => {
    expect(
      getApiErrorMessage({
        error: {
          message:
            "Authentication failed",
        },
      }),
    ).toBe(
      "Authentication failed",
    );
  });

  it("falls back for unknown error shapes", () => {
    expect(
      getApiErrorMessage({
        unexpected: {
          value: true,
        },
      }),
    ).toBe("Request failed");
  });
});

describe("apiClient error handling", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      fetchMock,
    );

    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("always exposes a string ApiError message for FastAPI 422 responses", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            type:
              "value_error",
            loc: [
              "body",
              "username",
            ],
            msg:
              "Invalid email address",
            input:
              "dev@agentforge.local",
          },
        ],
      }),
    } as Response);

    try {
      await apiClient.post(
        "/auth/login",
        {
          email:
            "dev@agentforge.local",
          password: "password",
        },
      );

      throw new Error(
        "Expected request to fail",
      );
    } catch (error) {
      expect(
        error,
      ).toBeInstanceOf(ApiError);

      const apiError =
        error as ApiError;

      expect(
        apiError.status,
      ).toBe(422);

      expect(
        apiError.message,
      ).toBe(
        "Invalid email address",
      );

      expect(
        typeof apiError.message,
      ).toBe("string");
    }
  });
});
describe("API client JSON and cancellation regressions", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("preserves get/post/put/patch/delete and empty 204 behavior", async () => {
    const mock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", mock);
    expect(await apiClient.get("/workspaces", { params: { skip: "1" } })).toBeNull();
    await apiClient.post("/auth/login", { email: "a" });
    await apiClient.put("/chat/settings", { enabled: true });
    await apiClient.patch("/workflows/id", { name: "new" });
    await apiClient.delete("/workspaces/id");
    expect(mock.mock.calls.map(([url, options]) => [url, options.method, options.body])).toEqual([
      ["/api/workspaces?skip=1", "GET", undefined],
      ["/api/auth/login", "POST", '{"email":"a"}'],
      ["/api/chat/settings", "PUT", '{"enabled":true}'],
      ["/api/workflows/id", "PATCH", '{"name":"new"}'],
      ["/api/workspaces/id", "DELETE", undefined],
    ]);
    for (const [, options] of mock.mock.calls)
      expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
  });
  it("does not fetch an already cancelled request", async () => {
    const mock = vi.fn();
    vi.stubGlobal("fetch", mock);
    const controller = new AbortController();
    controller.abort();
    await expect(apiClient.get("/workflows", { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(mock).not.toHaveBeenCalled();
  });
  it("retries a JSON 401 only once even when retry is also unauthorized", async () => {
    const mock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ access_token: "fresh" }))
      .mockResolvedValueOnce(Response.json({ detail: "denied" }, { status: 401 }));
    vi.stubGlobal("fetch", mock);
    await expect(apiClient.get("/workflows")).rejects.toMatchObject({
      status: 401,
      data: { detail: "denied" },
    });
    expect(mock).toHaveBeenCalledTimes(3);
    expect(mock.mock.calls[1]![0]).toBe("/api/auth/refresh");
  });
});
