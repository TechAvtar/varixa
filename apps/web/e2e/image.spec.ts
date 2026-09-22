import { expect, test } from "@playwright/test";
import { createImageAnalysis, formAlert, pickImage, register, waitForCompleted } from "./helpers";

test.describe("image analysis", () => {
  test("upload runs the pipeline and the report shows verified file facts", async ({ page }) => {
    await register(page);
    const id = await createImageAnalysis(page, "Harbour photo");
    await expect(page.getByRole("heading", { name: "Harbour photo" })).toBeVisible();

    await waitForCompleted(page, id);
    const summary = page.getByLabel("Overall evidence summary");
    await expect(summary).toContainText("VERIFIED");
    await expect(summary).toContainText("evidence engine");

    // Every report tab exists; sections without data say so instead of inventing findings.
    const tabs = page.getByRole("tablist").getByRole("tab");
    await expect(tabs).toHaveCount(7);
    // The stored original is described by its hash, never by guesses.
    await expect(page.getByText(/^[0-9a-f]{64}$/).first()).toBeVisible();

    await page.getByRole("tab", { name: "Forensics" }).click();
    await expect(page.getByRole("tabpanel", { name: "forensics" })).toBeVisible();
    await page.getByRole("tab", { name: "Timeline" }).click();
    await expect(page.getByRole("tabpanel", { name: "timeline" })).toBeVisible();

    // The new analysis is listed on the dashboard.
    await page.goto("/dashboard");
    await expect(page.getByRole("link", { name: "Harbour photo" })).toBeVisible();
  });

  test("a non-image is refused and nothing is created", async ({ page }) => {
    await register(page);
    await pickImage(page, {
      name: "notes.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("this is not a jpeg at all"),
    });
    await page.getByRole("button", { name: "Start analysis" }).click();
    await expect(formAlert(page)).toContainText("not a supported image");
    await page.goto("/dashboard");
    await expect(page.getByText("Total analyses").locator("..")).toContainText("0");
  });
});
