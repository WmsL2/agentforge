
import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test.describe("Login Page", () => {
    test("should display login form", async ({ page }) => {
      await page.goto("/login");

      // Check for login form elements
      await expect(page.getByRole("heading", { name: /sign in|log in|login/i })).toBeVisible();
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/password/i)).toBeVisible();
      await expect(page.getByRole("button", { name: /sign in|log in|login/i })).toBeVisible();
    });

    test("should show validation errors for empty form", async ({ page }) => {
      await page.goto("/login");

      const emailInput = page.getByLabel(/email/i);
      const passwordInput = page.getByLabel(/password/i);

      await page.getByRole("button", { name: /sign in|log in|login/i }).click();

      expect(
        await emailInput.evaluate(
          (element) => (element as HTMLInputElement).validity.valueMissing
        )
      ).toBe(true);

      expect(
        await passwordInput.evaluate(
          (element) => (element as HTMLInputElement).validity.valueMissing
        )
      ).toBe(true);
    });

    test("should show error for invalid credentials", async ({ page }) => {
      await page.goto("/login");

      await page.getByLabel(/email/i).fill("invalid@example.com");
      await page.getByLabel(/password/i).fill("wrongpassword");
      await page.getByRole("button", { name: /sign in|log in|login/i }).click();

      await expect(
        page.locator("#main").getByText(/invalid|incorrect|failed|error/i)
      ).toBeVisible({ timeout: 5000 });
    });

    test("should have link to registration", async ({ page }) => {
      await page.goto("/login");

      // Should have link to register page
      const registerLink = page.getByRole("link", { name: /sign up|register|create account/i });
      await expect(registerLink).toBeVisible();
    });
  });

  test.describe("Registration Page", () => {
    test("should display registration form", async ({ page }) => {
      await page.goto("/register");

      // Check for registration form elements
      await expect(page.getByRole("heading", { name: /sign up|register|create/i })).toBeVisible();
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/password/i).first()).toBeVisible();
      await expect(page.getByRole("button", { name: /sign up|register|create/i })).toBeVisible();
    });

    test("should validate password requirements", async ({ page }) => {
      await page.goto("/register");

      await page.getByLabel(/email/i).fill("newuser@example.com");
      await page.getByLabel(/password/i).first().fill("weak");
      await page.getByLabel(/confirm password/i).fill("weak");

      await page.getByRole("button", { name: /sign up|register|create/i }).click();

      await expect(
        page.getByText("Password must be at least 8 characters", { exact: true })
      ).toBeVisible();
    });

    test("should have link to login", async ({ page }) => {
      await page.goto("/register");

      // Should have link to login page
      const loginLink = page.getByRole("link", { name: /sign in|log in|login|already have/i });
      await expect(loginLink).toBeVisible();
    });
  });

  test.describe("Authenticated User", () => {
    // Use authenticated state from setup
    test.use({
      storageState: ".playwright/.auth/user.json",
    });

    test("should access dashboard when authenticated", async ({ page }) => {
      await page.goto("/dashboard");

      await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/i);
    });

    test("should show user menu or profile", async ({ page }) => {
      await page.goto("/dashboard");

      const userMenuButton = page.getByRole("button", {
        name: /profile/i,
      });

      await expect(userMenuButton).toBeVisible();
    });

    test("should be able to logout", async ({ page }) => {
      await page.goto("/dashboard");

      const userMenuButton = page.getByRole("button", {
        name: /profile/i,
      });

      await expect(userMenuButton).toBeVisible();
      await userMenuButton.click();

      const logoutButton = page
        .getByRole("button", { name: /log out|sign out|logout/i })
        .or(page.getByRole("menuitem", { name: /log out|sign out|logout/i }));

      await expect(logoutButton).toBeVisible();
      await logoutButton.click();

      await expect(page).toHaveURL(/login|\/$/);
    });
  });
});
