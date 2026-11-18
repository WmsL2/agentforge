"use client";

import { useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuthStore } from "@/stores";
import { apiClient, ApiError } from "@/lib/api-client";
import { authTransitionEpoch } from "@/lib/auth-transition";
import type { User, LoginRequest, RegisterRequest } from "@/types";
import { ROUTES } from "@/lib/constants";
import { isAppAdmin } from "@/lib/utils";

// One automatic timer; every /me request uses the same cookie-writer coordinator.
let authConsumers = 0;
let tokenRefreshTimer: ReturnType<typeof setInterval> | null = null;
const TOKEN_REFRESH_INTERVAL_MS = 10 * 60 * 1000;
function ensureTokenRefresh() {
  if (tokenRefreshTimer) return;
  tokenRefreshTimer = setInterval(() => {
    if (useAuthStore.getState().isAuthenticated) void useAuthStore.getState().checkAuth();
  }, TOKEN_REFRESH_INTERVAL_MS);
}
function stopTokenRefresh() {
  if (tokenRefreshTimer) clearInterval(tokenRefreshTimer);
  tokenRefreshTimer = null;
}

export function useAuth() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, checkAuth } = useAuthStore();
  useEffect(() => {
    authConsumers++;
    void checkAuth();
    ensureTokenRefresh();
    return () => {
      if (--authConsumers === 0) stopTokenRefresh();
    };
  }, [checkAuth]);

  const login = useCallback(
    async (credentials: LoginRequest) => {
      const request = apiClient.post<{ user: User; access_token: string; message: string }>(
        "/auth/login",
        credentials,
      );
      const ticket = authTransitionEpoch();
      const response = await request;
      if (ticket === authTransitionEpoch()) {
        ensureTokenRefresh();
        router.push(isAppAdmin(response.user) ? ROUTES.DASHBOARD : ROUTES.CHAT);
      }
      return response;
    },
    [router],
  );
  const register = useCallback(
    (data: RegisterRequest) =>
      apiClient.post<{ id: string; email: string }>("/auth/register", data),
    [],
  );
  const logout = useCallback(async () => {
    stopTokenRefresh();
    const request = apiClient.post("/auth/logout"); // Clears local identity synchronously, then drains old cookie writers.
    const ticket = authTransitionEpoch();
    try {
      await request;
    } catch {
      /* A newer transition owns navigation if this one was superseded. */
    }
    if (ticket === authTransitionEpoch()) {
      toast.success("Logged out");
      router.push(ROUTES.LOGIN);
    }
  }, [router]);
  const refreshToken = useCallback(async () => {
    const ticket = authTransitionEpoch();
    try {
      await apiClient.post("/auth/refresh");
      await apiClient.get<User>("/auth/me");
      return ticket === authTransitionEpoch();
    } catch (error) {
      if (ticket !== authTransitionEpoch()) return false;
      if (error instanceof ApiError && error.status === 401) {
        useAuthStore.getState().logout();
        router.push(ROUTES.LOGIN);
      }
      return false;
    }
  }, [router]);
  return { user, isAuthenticated, isLoading, login, register, logout, refreshToken };
}
