import { expect, test } from "@playwright/test";
import { formAlert, login, register, signOut, uniqueEmail } from "./helpers";

test.describe("authentication", () => {
  test("guests are sent to sign-in and back after login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    // Deep links are remembered so the visitor lands where they were going.
    await page.goto("/analyses/new");
    await expect(page).toHaveURL(/\/login\?next=%2Fanalyses%2Fnew/);
  });

  test("register, sign out, sign in again", async ({ page }) => {
    const { email, name } = await register(page);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByText(name, { exact: true })).toBeVisible();

    await signOut(page);
    await expect(page).toHaveURL(/\/login$/);
    // Signed-out visitors cannot reach protected pages any more.
    await page.goto("/analyses/new");
    await expect(page).toHaveURL(/\/login/);

    await login(page, email);
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
  });

  test("wrong password and unknown email get the same message", async ({ page }) => {
    const { email } = await register(page);
    await signOut(page);

    await login(page, email, "definitely-not-the-password");
    await expect(formAlert(page)).toHaveText("Invalid email or password.");
    await expect(page).toHaveURL(/\/login/);

    await login(page, uniqueEmail("ghost"), "definitely-not-the-password");
    await expect(formAlert(page)).toHaveText("Invalid email or password.");
  });

  test("duplicate registration is refused without leaking anything else", async ({ page }) => {
    const { email } = await register(page);
    await signOut(page);
    await page.goto("/register");
    await page.getByLabel("Name").fill("Again");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("another-password-123");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(formAlert(page)).toContainText("already exists");
  });
});
