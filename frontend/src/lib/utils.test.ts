import { describe, it, expect } from "vitest";
import { cn, formatDate } from "./utils";

describe("cn utility function", () => {
  it("should merge class names", () => {
    const result = cn("class1", "class2");
    expect(result).toBe("class1 class2");
  });

  it("should handle conditional classes", () => {
    const result = cn("base", { active: true, disabled: false });
    expect(result).toContain("base");
    expect(result).toContain("active");
    expect(result).not.toContain("disabled");
  });

  it("should handle undefined and null values", () => {
    const result = cn("base", undefined, null, "extra");
    expect(result).toBe("base extra");
  });

  it("should merge tailwind classes correctly", () => {
    // tailwind-merge should handle conflicting utilities
    const result = cn("px-2 py-1", "px-4");
    expect(result).toContain("px-4");
    expect(result).toContain("py-1");
  });

  it("should handle empty input", () => {
    const result = cn();
    expect(result).toBe("");
  });

  it("should handle array of classes", () => {
    const result = cn(["class1", "class2"]);
    expect(result).toContain("class1");
    expect(result).toContain("class2");
  });
});

it("formats profile dates consistently and handles absent or invalid dates", () => {
  expect(formatDate("2026-11-18T12:00:00Z")).toBe("Nov 18, 2026");
  expect(formatDate(new Date("2026-11-18T12:00:00Z"))).toBe("Nov 18, 2026");
  expect(formatDate(null)).toBe("—");
  expect(formatDate(undefined)).toBe("—");
  expect(formatDate("not-a-date")).toBe("—");
});
