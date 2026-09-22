import { expect, test } from "@playwright/test";
import { createTextAnalysis, register, waitForCompleted } from "./helpers";

test.describe("deletion and ownership", () => {
  test("another account never sees the analysis", async ({ browser, page }) => {
    await register(page);
    const id = await createTextAnalysis(page);

    const other = await browser.newContext();
    const otherPage = await other.newPage();
    await register(otherPage, undefined, "Other User");
    await otherPage.goto(`/analyses/${id}`);
    await expect(otherPage.getByText("Analysis not found")).toBeVisible();
    await otherPage.goto("/dashboard");
    await expect(otherPage.getByText("Total analyses").locator("..")).toContainText("0");
    await other.close();
  });

  test("deleting removes the report and its listing", async ({ page }) => {
    await register(page);
    const id = await createTextAnalysis(page, undefined, "Delete me");
    await waitForCompleted(page, id);

    // Dismissing the confirmation changes nothing.
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Delete analysis" }).click();
    await expect(page).toHaveURL(new RegExp(`/analyses/${id}`));

    page.once("dialog", (dialog) => {
      expect(dialog.message()).toContain("Delete me");
      void dialog.accept();
    });
    await page.getByRole("button", { name: "Delete analysis" }).click();
    await expect(page).toHaveURL(/\/dashboard\?deleted=1/);
    await expect(page.getByText("Analysis deleted")).toBeVisible();
    await expect(page.getByRole("link", { name: "Delete me" })).toHaveCount(0);

    await page.goto(`/analyses/${id}`);
    await expect(page.getByText("Analysis not found")).toBeVisible();
  });
});
