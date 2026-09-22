import { expect, test } from "@playwright/test";
import { createTextAnalysis, pasteText, register, waitForCompleted } from "./helpers";

test.describe("text analysis", () => {
  test("pasted text is analysed and its statistics are reported", async ({ page }) => {
    await register(page);
    const id = await createTextAnalysis(page, undefined, "Harbour ledger");
    await expect(page.getByRole("heading", { name: "Harbour ledger" })).toBeVisible();

    await waitForCompleted(page, id);
    await expect(page.getByText("Text statistics", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Overall evidence summary")).toContainText("VERIFIED");
    // AI detection is a signal at most: the panel says so and never rates it above POSSIBLE.
    await page.getByRole("tab", { name: "AI Analysis" }).click();
    const panel = page.getByRole("tabpanel", { name: "ai" });
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("never proof");
    await expect(panel).toContainText("not calibrated");
    await expect(panel).not.toContainText(/\b(VERIFIED|STRONG)\b/);
  });

  test("empty text cannot be submitted", async ({ page }) => {
    await register(page);
    await pasteText(page, "Some words first, to prove the form is live.");
    await page.getByLabel("Text", { exact: true }).fill("   ");
    await expect(page.getByRole("button", { name: "Start analysis" })).toBeDisabled();
  });
});
