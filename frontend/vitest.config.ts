import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      include: [
        "src/lib/auth-cookies.ts",
        "src/lib/utils.ts",
        "src/stores/auth-store.ts",
        "src/components/ui/button.tsx",
      ],
      exclude: ["node_modules", ".next", "e2e", "**/*.d.ts", "**/*.config.*", "vitest.setup.ts"],
      thresholds: {
        statements: 50,
        branches: 90,
        functions: 40,
        lines: 50,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
