import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import pl from "../../../messages/pl.json";
import { useAuthStore, useSidebarStore } from "@/stores";
import type { User } from "@/types";
const state = vi.hoisted(() => ({ pathname: "/knowledge", role: "member" }));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock("@/hooks", async () => {
  const { useAuthStore } = await import("@/stores");
  return {
    useAuth: () => ({ user: useAuthStore.getState().user, isAuthenticated: true, logout: vi.fn() }),
  };
});
vi.mock("@/components/theme", () => ({ ThemeToggle: () => null }));
vi.mock("@/components/language-switcher", () => ({ LanguageSwitcherIcon: () => null }));
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { MobileTabBar } from "@/components/layout/mobile-tab-bar";
const surfaces = [Header, Sidebar, MobileTabBar];
beforeEach(() => {
  useSidebarStore.setState({ isOpen: true });
});
it.each(
  surfaces.flatMap((Surface) =>
    ["member", "admin"].flatMap((role) =>
      ["/knowledge", "/knowledge/kb1", "/pl/knowledge", "/pl/knowledge/kb1"].map((path) => ({
        Surface,
        role,
        path,
      })),
    ),
  ),
)("Knowledge entry and active locale: $Surface.name $role $path", ({ Surface, role, path }) => {
  state.pathname = path;
  useAuthStore
    .getState()
    .setUser({ id: "u", email: "u@test", role, is_active: true, created_at: "2026-11-20" } as User);
  const messages = path.startsWith("/pl/") ? pl : en;
  render(
    <NextIntlClientProvider
      locale={messages === pl ? "pl" : "en"}
      messages={{ nav: messages.nav, common: messages.common }}
    >
      <Surface />
    </NextIntlClientProvider>,
  );
  const entry = screen.getByRole("link", { name: messages.nav.knowledge });
  expect(entry).toHaveAttribute("href", path.startsWith("/pl/") ? "/pl/knowledge" : "/knowledge");
  expect(entry).toHaveAttribute("aria-current", "page");
  expect(
    screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page"),
  ).toEqual([entry]);
  expect(screen.getByRole("link", { name: messages.nav.workflows })).toBeInTheDocument();
});
it("new translation namespace has identical keys and no legacy scope terminology", () => {
  const keys = (value: object, prefix = ""): string[] =>
    Object.entries(value).flatMap(([key, entry]) =>
      entry && typeof entry === "object" ? keys(entry, `${prefix}${key}.`) : [`${prefix}${key}`],
    );
  expect(keys(en.knowledgeManagement).sort()).toEqual(keys(pl.knowledgeManagement).sort());
  expect(JSON.stringify(en.knowledgeManagement)).not.toMatch(/Personal|Organization|App Scope/);
});
