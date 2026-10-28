import { NextIntlClientProvider } from "next-intl";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";

const mocks = vi.hoisted(() => ({
  pathname: "/dashboard",
  close: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
}));

vi.mock("@/stores", () => ({
  useSidebarStore: () => ({ isOpen: true, close: mocks.close }),
  useAuthStore: () => ({ user: { role: "admin" } }),
}));

import { Sidebar } from "./sidebar";

const cases = [
  ["/workflows", "Workflows", "/workflows"],
  ["/workflows/123", "Workflows", "/workflows"],
  ["/pl/workflows", "Workflows", "/pl/workflows"],
  ["/pl/workflows/123", "Workflows", "/pl/workflows"],
  ["/admin", "Admin", "/admin"],
  ["/admin/users", "Admin", "/admin"],
  ["/pl/admin/users", "Admin", "/pl/admin"],
  ["/dashboard", "Dashboard", "/dashboard"],
  ["/chat", "Chat", "/chat"],
  ["/profile", "Profile", "/profile"],
] as const;

describe("Sidebar active navigation", () => {
  it.each(cases)("marks %s as %s", (pathname, label, href) => {
    mocks.pathname = pathname;

    render(
      <NextIntlClientProvider locale="en" messages={{ nav: messages.nav }}>
        <Sidebar />
      </NextIntlClientProvider>,
    );

    const activeLink = screen.getByRole("link", { name: label });
    expect(activeLink).toHaveAttribute("aria-current", "page");
    expect(activeLink).toHaveAttribute("href", href);
    expect(screen.getAllByRole("link").filter((link) => link.hasAttribute("aria-current"))).toEqual([
      activeLink,
    ]);
  });
});
