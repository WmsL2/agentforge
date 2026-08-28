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