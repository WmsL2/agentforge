import { describe, expect, it } from "vitest";

import { isRouteActive, localizeHref } from "./active-route";

describe("localized workflow navigation", () => {
  it("keeps default locale paths unprefixed", () => {
    expect(localizeHref("/workflows", "/workflows")).toBe("/workflows");
    expect(isRouteActive("/workflows/flow-1", "/workflows")).toBe(true);
  });

  it("preserves the Polish locale prefix and active state", () => {
    expect(localizeHref("/pl/dashboard", "/workflows")).toBe("/pl/workflows");
    expect(isRouteActive("/pl/workflows/flow-1", "/workflows")).toBe(true);
  });
});
