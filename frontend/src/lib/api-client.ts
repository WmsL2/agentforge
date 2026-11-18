/**
 * Client-side API client.
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 */

import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import { coordinateAuthentication, type AuthOperation } from "./auth-transition";
import { authIdentity, sameAuthIdentity, aborted } from "./auth-identity";

import { getApiErrorMessage } from "./error-message";

export { getApiErrorMessage } from "./error-message";

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

export interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string>;
  body?: unknown;
  identityGuard?: () => boolean;
  responseType?: "blob";
}

const REFRESH_ENDPOINT = "/auth/refresh";

let refreshFlight: { identity: ReturnType<typeof authIdentity>; promise: Promise<boolean> } | null =
  null;

function refreshAccessToken(): Promise<boolean> {
  const identity = authIdentity();
  if (refreshFlight && sameAuthIdentity(refreshFlight.identity)) return refreshFlight.promise;
  const flight = { identity, promise: Promise.resolve(false) };
  flight.promise = apiClient
    .post<{ access_token?: string }>(REFRESH_ENDPOINT)
    .then(() => sameAuthIdentity(identity))
    .catch(() => false)
    .finally(() => {
      if (refreshFlight === flight) refreshFlight = null;
    });
  refreshFlight = flight;
  return flight.promise;
}

const loginEndpoints = new Set(["/auth/login", "/auth/oauth-callback", "/auth/magic-link/verify"]);
function authOperation(endpoint: string): AuthOperation | undefined {
  if (loginEndpoints.has(endpoint)) return "login";
  if (endpoint === "/auth/logout") return "logout";
  if (endpoint === "/auth/me" || endpoint === REFRESH_ENDPOINT) return "probe";
  return undefined;
}

export interface DownloadResponse {
  blob: Blob;
  contentDisposition: string | null;
  contentType: string | null;
}

class ApiClient {
  private request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const kind = authOperation(endpoint);
    if (!kind) return this.perform<T>(endpoint, options);
    const original = authIdentity();
    return coordinateAuthentication(
      kind,
      useAuthStore.getState().isAuthenticated,
      () => {
        useAuthStore.setState({
          user: null,
          isAuthenticated: false,
          accessToken: null,
          isLoading: kind === "login",
        });
      },
      async (current) => {
        try {
          const data = await this.perform<T>(
            endpoint,
            {
              ...options,
              identityGuard: () => current() && (kind !== "probe" || sameAuthIdentity(original)),
            },
            true,
          );
          if (!current()) aborted();
          if (kind !== "logout" && data && typeof data === "object") {
            const auth = data as { user?: User; access_token?: string };
            if (kind === "login" && auth.user) useAuthStore.getState().setUser(auth.user);
            if (endpoint === "/auth/me") {
              const { access_token, ...user } = data as unknown as User & { access_token?: string };
              if (access_token) useAuthStore.getState().setAccessToken(access_token);
              useAuthStore.getState().setUser(user);
            }
            if (auth.access_token) useAuthStore.getState().setAccessToken(auth.access_token);
          }
          return data;
        } catch (error) {
          if (
            current() &&
            error instanceof ApiError &&
            error.status === 401 &&
            endpoint === "/auth/me"
          )
            useAuthStore.getState().logout();
          throw error;
        } finally {
          if (current()) useAuthStore.getState().setLoading(false);
        }
      },
    );
  }

  private async perform<T>(
    endpoint: string,
    options: RequestOptions = {},
    coordinated = false,
  ): Promise<T> {
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
        const response = await fetch(url, {
          ...fetchOptions,
          ...(coordinated ? { signal: undefined, cache: "no-store" as const } : {}),
          headers,
          body:
            body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
        });
        // Drain a clone while holding the cookie queue, even if the caller cancels.
        if (coordinated && typeof response.clone === "function")
          await response.clone().arrayBuffer();
        return response;
      } catch (error) {
        check();
        if (guarded && !(error instanceof DOMException && error.name === "AbortError")) {
          throw new ApiError(0, "Network request failed");
        }
        throw error;
      }
    };

    let response = await doFetch();

    if (response.status === 401 && !coordinated) {
      check();
      const refreshed = await refreshAccessToken();
      if (!sameAuthIdentity(identity)) aborted();

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
      try {
        return await consume();
      } catch (error) {
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

    try {
      return JSON.parse(text) as T;
    } catch (error) {
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
