"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  authTransitionEpoch,
  canProbeAuthentication,
  blockAuthProbes,
  resumeAuthProbes,
} from "@/lib/auth-transition";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  accessToken: string | null;
  avatarVersion: number;

  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  setAccessToken: (token: string | null) => void;
  checkAuth: () => Promise<void>;
  logout: () => void;
  bumpAvatarVersion: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      isLoading: true,
      accessToken: null,
      avatarVersion: 0,

      setUser: (user) => {
        if (user) resumeAuthProbes();
        set({
          user,
          isAuthenticated: user !== null,
          isLoading: false,
        });
      },

      setLoading: (loading) => set({ isLoading: loading }),

      setAccessToken: (token) => set({ accessToken: token }),

      bumpAvatarVersion: () => set((s) => ({ avatarVersion: s.avatarVersion + 1 })),

      checkAuth: async () => {
        const state = useAuthStore.getState();
        if (!canProbeAuthentication(state.isAuthenticated)) return;
        const ticket = authTransitionEpoch();
        set({ isLoading: true });
        try {
          const { apiClient } = await import("@/lib/api-client");
          if (ticket !== authTransitionEpoch()) return;
          await apiClient.get<User>("/auth/me");
        } catch {
          // The coordinated client owns identity updates; stale errors do not log out a new user.
        } finally {
          if (ticket === authTransitionEpoch()) set({ isLoading: false });
        }
      },

      logout: () => {
        blockAuthProbes();
        set({ user: null, isAuthenticated: false, isLoading: false, accessToken: null });
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        // Note: accessToken is intentionally NOT persisted - kept in-memory only
      }),
    },
  ),
);
