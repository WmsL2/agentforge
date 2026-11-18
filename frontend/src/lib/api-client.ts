/**
 * Client-side API client.
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 */

import { useAuthStore } from "@/stores";
import { authIdentity, sameAuthIdentity, aborted } from "./auth-identity";

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

export interface RequestOptions
  extends Omit<RequestInit, "body"> {
  params?: Record<string, string>;
  body?: unknown;
  identityGuard?: () => boolean;
  responseType?: "blob";
}

const REFRESH_ENDPOINT =
  "/auth/refresh";

let refreshPromise:
  | Promise<boolean>
  | null = null;

function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    const identity = authIdentity();
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

          if (data?.access_token && sameAuthIdentity(identity)) {
            useAuthStore
              .getState()
              .setAccessToken(
                data.access_token,
              );
          }
        } catch {
          // Cookies may still have been rotated successfully.
        }

        return sameAuthIdentity(identity);
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

export interface DownloadResponse {
  blob: Blob;
  contentDisposition: string | null;
  contentType: string | null;
}

class ApiClient {
  private async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, body, identityGuard, responseType, ...fetchOptions } = options;

    let url = `/api${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams(params);

      url += `?${searchParams.toString()}`;
    }

    const identity = authIdentity();
    const guarded = Boolean(identityGuard) || endpoint.includes("/knowledge-bases");
    const check = () => {
      if (
        fetchOptions.signal?.aborted ||
        (guarded && (!sameAuthIdentity(identity) || identityGuard?.() === false))
      )
        aborted();
    };
    const doFetch = async () => {
      check();
      const headers = new Headers(fetchOptions.headers);
      if (body instanceof FormData) headers.delete("Content-Type");
      else if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      try {
        return await fetch(url, {
          ...fetchOptions,
          headers,
          body:
            body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
        });
      } catch (error) {
        check();
        if (guarded && !(error instanceof DOMException && error.name === "AbortError")) {
          throw new ApiError(0, "Network request failed");
        }
        throw error;
      }
    };

    let response = await doFetch();

    if (response.status === 401 && endpoint !== REFRESH_ENDPOINT) {
      check();
      const refreshed = await refreshAccessToken();

      check();
      if (refreshed) {
        response = await doFetch();
      }
    }

    check();
    if (!response.ok) {
      let errorData: unknown;

      try {
        errorData = await response.json();
      } catch {
        errorData = null;
      }

      check();
      throw new ApiError(response.status, getApiErrorMessage(errorData), errorData);
    }

    const read = async <R>(consume: () => Promise<R>): Promise<R> => {
      try { return await consume(); }
      catch (error) {
        check();
        if (guarded) throw new ApiError(0, "Network request failed");
        throw error;
      }
    };
    if (responseType === "blob") {
      const blob = await read(() => response.blob());
      check();
      return {
        blob,
        contentDisposition: response.headers.get("Content-Disposition"),
        contentType: response.headers.get("Content-Type"),
      } as T;
    }
    const text = await read(() => response.text());
    check();

    if (!text) {
      return null as T;
    }

    try { return JSON.parse(text) as T; }
    catch (error) {
      if (guarded) throw new ApiError(response.status, "Invalid server response");
      throw error;
    }
  }

  download(endpoint: string, options?: RequestOptions) {
    return this.request<DownloadResponse>(endpoint, {
      ...options,
      method: "GET",
      responseType: "blob",
    });
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