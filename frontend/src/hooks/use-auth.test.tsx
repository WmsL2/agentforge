import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import ProfileSettingsPage from "@/app/[locale]/(dashboard)/settings/profile/page";
import { useAuth } from "./use-auth";
import { AuthGuard } from "@/components/layout/auth-guard";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { bindKnowledgeLifecycle } from "@/lib/knowledge/knowledge-lifecycle";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import type { User } from "@/types";
vi.mock("@/hooks", async () => {
  const { useAuthStore } = await import("@/stores/auth-store");
  return { useAuth: () => ({ user: useAuthStore((s) => s.user) }) };
});
const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));
const A: User = { id: "A", email: "a@test", is_active: true, created_at: "2026-11-18" };
const B: User = { ...A, id: "B", email: "b@test" };
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const mock = vi.fn();
beforeEach(() => {
  useAuthStore.getState().setUser(A);
  useAuthStore.getState().setAccessToken("a");
  navigation.push.mockReset();
  navigation.replace.mockReset();
  vi.stubGlobal(
    "fetch",
    mock
      .mockReset()
      .mockImplementation((url: string) =>
        Promise.resolve(
          Response.json(
            url === "/api/auth/me"
              ? { ...A, access_token: "a" }
              : url === "/api/auth/login"
                ? { user: B, access_token: "b" }
                : { access_token: "fresh" },
          ),
        ),
      ),
  );
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});
it("AuthGuard hides children and never probes during Logout or restores late /me user", async () => {
  const pending = deferred<Response>();
  mock.mockReturnValueOnce(pending.promise);
  const client = new QueryClient();
  const unbind = bindKnowledgeLifecycle(client);
  const key = qk.knowledge.content("A", "w", "kb", "d");
  client.setQueryData(key, "private");
  render(
    <AuthGuard>
      <div>private child</div>
    </AuthGuard>,
  );
  expect(screen.getByText("private child")).toBeInTheDocument();
  let check!: Promise<void>;
  act(() => {
    check = useAuthStore.getState().checkAuth();
  });
  await waitFor(() => expect(mock).toHaveBeenCalledTimes(1));
  let exit!: Promise<unknown>;
  act(() => {
    exit = apiClient.post("/auth/logout");
  });
  expect(screen.queryByText("private child")).not.toBeInTheDocument();
  expect(client.getQueryData(key)).toBeUndefined();
  await act(async () => {
    await useAuthStore.getState().checkAuth();
  });
  expect(mock).toHaveBeenCalledTimes(1);
  await act(async () => {
    pending.resolve(Response.json({ ...A, access_token: "old" }));
    await check;
    await exit;
  });
  expect(useAuthStore.getState().user).toBeNull();
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(mock.mock.calls.filter(([u]) => u === "/api/auth/me")).toHaveLength(1);
  expect(screen.queryByText("private child")).not.toBeInTheDocument();
  unbind();
  client.clear();
});
it("Login and Logout update state through the coordinated client", async () => {
  const hook = renderHook(() => useAuth());
  await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false));
  await act(() => hook.result.current.login({ email: "b@test", password: "fake" }));
  expect(hook.result.current.user?.id).toBe("B");
  expect(hook.result.current.isAuthenticated).toBe(true);
  await act(() => hook.result.current.logout());
  expect(hook.result.current.user).toBeNull();
  expect(hook.result.current.isAuthenticated).toBe(false);
  expect(navigation.push.mock.calls.map(([path]) => path)).toEqual([ROUTES.CHAT, ROUTES.LOGIN]);
});
it("old Logout completion cannot clear new Login or navigate it to Login", async () => {
  const hook = renderHook(() => useAuth());
  await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false));
  const pending = deferred<Response>();
  mock.mockImplementation((url: string) =>
    url === "/api/auth/logout"
      ? pending.promise
      : Promise.resolve(Response.json({ user: B, access_token: "b" })),
  );
  let exit!: Promise<void>, enter!: ReturnType<typeof hook.result.current.login>;
  act(() => {
    exit = hook.result.current.logout();
  });
  await waitFor(() => expect(mock.mock.calls.some(([u]) => u === "/api/auth/logout")).toBe(true));
  act(() => {
    enter = hook.result.current.login({ email: "b@test", password: "fake" });
  });
  await act(async () => {
    pending.resolve(Response.json({ message: "out" }));
    await exit;
    await enter;
  });
  expect(useAuthStore.getState().user?.id).toBe("B");
  expect(navigation.push).toHaveBeenCalledTimes(1);
  expect(navigation.push).toHaveBeenCalledWith("/chat");
});
it("automatic ten-minute refresh uses /me and stops during Logout", async () => {
  vi.useFakeTimers();
  const hook = renderHook(() => useAuth());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(mock.mock.calls.filter(([u]) => u === "/api/auth/me")).toHaveLength(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
  });
  expect(mock.mock.calls.filter(([u]) => u === "/api/auth/me")).toHaveLength(2);
  await act(() => hook.result.current.logout());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);
  });
  expect(mock.mock.calls.filter(([u]) => u === "/api/auth/me")).toHaveLength(2);
  expect(useAuthStore.getState().user).toBeNull();
  await act(() => hook.result.current.login({ email: "b@test", password: "fake" }));
  mock.mockImplementation(() => Promise.resolve(Response.json({ ...B, access_token: "b" })));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
  });
  expect(mock.mock.calls.filter(([url]) => url === "/api/auth/me")).toHaveLength(3);
  expect(useAuthStore.getState().user?.id).toBe("B");
});
it("explicit refresh uses the same queue and then revalidates /me", async () => {
  const hook = renderHook(() => useAuth());
  await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false));
  mock.mockClear();
  await act(async () => {
    expect(await hook.result.current.refreshToken()).toBe(true);
  });
  expect(mock.mock.calls.map(([u]) => u)).toEqual(["/api/auth/refresh", "/api/auth/me"]);
  expect(useAuthStore.getState().accessToken).toBe("a");
});
it("failed sign-in keeps old Knowledge hidden and never automatically restores the old session", async () => {
  const hook = renderHook(() => useAuth());
  await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false));
  mock.mockResolvedValueOnce(Response.json({ detail: "invalid" }, { status: 422 }));
  await act(async () => {
    await expect(
      hook.result.current.login({ email: "bad", password: "bad" }),
    ).rejects.toMatchObject({ status: 422 });
  });
  const count = mock.mock.calls.length;
  await useAuthStore.getState().checkAuth();
  expect(mock).toHaveBeenCalledTimes(count);
  expect(useAuthStore.getState().user).toBeNull();
});
it("expired /me clears identity and AuthGuard routes to sign-in", async () => {
  useAuthStore.getState().setUser(null);
  mock.mockResolvedValueOnce(Response.json({ detail: "expired" }, { status: 401 }));
  render(
    <AuthGuard>
      <div>private child</div>
    </AuthGuard>,
  );
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith(ROUTES.LOGIN));
  expect(screen.queryByText("private child")).not.toBeInTheDocument();
  expect(mock).toHaveBeenCalledTimes(1);
});

it.each([
  ["profile", "logout"],
  ["profile", "login"],
  ["avatar", "logout"],
  ["avatar", "login"],
])("late %s response cannot restore user after %s", async (kind, transition) => {
  const pending = deferred<Response>();
  mock.mockImplementation((url: string) => {
    if (url === "/api/sessions") return Promise.resolve(Response.json({ sessions: [] }));
    if (url === "/api/users/me" || url === "/api/users/me/avatar") return pending.promise;
    return Promise.resolve(
      Response.json(
        url === "/api/auth/login" ? { user: B, access_token: "b" } : { message: "out" },
      ),
    );
  });
  const view = render(<ProfileSettingsPage />);
  if (kind === "profile") {
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "edited" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  } else {
    const input = view.container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, {
      target: { files: [new File(["bytes"], "avatar.png", { type: "image/png" })] },
    });
  }
  await waitFor(() =>
    expect(
      mock.mock.calls.some(
        ([u]) => u === (kind === "profile" ? "/api/users/me" : "/api/users/me/avatar"),
      ),
    ).toBe(true),
  );
  await act(() =>
    apiClient.post(transition === "login" ? "/auth/login" : "/auth/logout", {
      email: "b@test",
      password: "fake",
    }),
  );
  await act(async () => {
    pending.resolve(Response.json({ ...A, full_name: "late" }));
    await pending.promise;
  });
  expect(useAuthStore.getState().user?.id).toBe(transition === "login" ? "B" : undefined);
  expect(useAuthStore.getState().user?.full_name).not.toBe("late");
});
