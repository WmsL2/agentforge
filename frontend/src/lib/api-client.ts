/**
 * Client-side API client.
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 */

import { useAuthStore } from "@/stores";

import {
  getApiErrorMessage,
} from "./error-message";

export {
  getApiErrorMessage,
} from "./error-message";

export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public data?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions
  extends Omit<RequestInit, "body"> {
  params?: Record<string, string>;
  body?: unknown;
}

const REFRESH_ENDPOINT =
  "/auth/refresh";

let refreshPromise:
  | Promise<boolean>
  | null = null;

function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(
      `/api${REFRESH_ENDPOINT}`,
      {
        method: "POST",
        headers: {
          "Content-Type":
            "application/json",
        },
      },
    )
      .then(async (response) => {
        if (!response.ok) {
          return false;
        }

        try {
          const data =
            (await response.json()) as {
              access_token?: string;
            };

          if (data?.access_token) {
            useAuthStore
              .getState()
              .setAccessToken(
                data.access_token,
              );
          }
        } catch {
          // Cookies may still have been rotated successfully.
        }

        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

class ApiClient {
  private async request<T>(
    endpoint: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const {
      params,
      body,
      ...fetchOptions
    } = options;

    let url = `/api${endpoint}`;

    if (params) {
      const searchParams =
        new URLSearchParams(params);

      url += `?${searchParams.toString()}`;
    }

    const doFetch = () =>
      fetch(url, {
        ...fetchOptions,
        headers: {
          "Content-Type":
            "application/json",
          ...fetchOptions.headers,
        },
        body:
          body !== undefined
            ? JSON.stringify(body)
            : undefined,
      });

    let response = await doFetch();

    if (
      response.status === 401 &&
      endpoint !== REFRESH_ENDPOINT
    ) {
      const refreshed =
        await refreshAccessToken();

      if (refreshed) {
        response = await doFetch();
      }
    }

    if (!response.ok) {
      let errorData: unknown;

      try {
        errorData =
          await response.json();
      } catch {
        errorData = null;
      }

      throw new ApiError(
        response.status,
        getApiErrorMessage(
          errorData,
        ),
        errorData,
      );
    }

    const text =
      await response.text();

    if (!text) {
      return null as T;
    }

    return JSON.parse(text) as T;
  }

  get<T>(
    endpoint: string,
    options?: RequestOptions,
  ) {
    return this.request<T>(
      endpoint,
      {
        ...options,
        method: "GET",
      },
    );
  }

  post<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions,
  ) {
    return this.request<T>(
      endpoint,
      {
        ...options,
        method: "POST",
        body,
      },
    );
  }

  put<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions,
  ) {
    return this.request<T>(
      endpoint,
      {
        ...options,
        method: "PUT",
        body,
      },
    );
  }

  patch<T>(
    endpoint: string,
    body?: unknown,
    options?: RequestOptions,
  ) {
    return this.request<T>(
      endpoint,
      {
        ...options,
        method: "PATCH",
        body,
      },
    );
  }

  delete<T>(
    endpoint: string,
    options?: RequestOptions,
  ) {
    return this.request<T>(
      endpoint,
      {
        ...options,
        method: "DELETE",
      },
    );
  }
}

export const apiClient =
  new ApiClient();