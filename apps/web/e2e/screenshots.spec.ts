import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
  SIGNED_IMAGE,
  createImageAnalysis,
  createTextAnalysis,
  register,
  waitForCompleted,
} from "./helpers";

/**
 * Walkthrough that saves screenshots of the main screens for reviewers. Off by default so CI
 * stays fast; run with E2E_SCREENSHOTS=1 and find the images under e2e/screenshots/.
 */
const OUT = process.env.E2E_SCREENSHOTS_DIR ?? path.resolve(__dirname, "screenshots");

test.describe("screenshot walkthrough", () => {
  test.skip(!process.env.E2E_SCREENSHOTS, "set E2E_SCREENSHOTS=1 to capture screenshots");

  test("captures the main screens", async ({ page }) => {
    fs.mkdirSync(OUT, { recursive: true });
    const shot = async (name: string) => {
      await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
    };

    await page.goto("/");
    await shot("01-landing");
    await page.goto("/register");
    await shot("02-register");

    await register(page);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 30_000 });
    await shot("03-dashboard-empty");

    await page.goto("/analyses/new?mode=image");
    await shot("04-new-image-analysis");
    const id = await createImageAnalysis(page, "Signed sample (C2PA)", SIGNED_IMAGE);
    await waitForCompleted(page, id);
    await shot("05-report-overview");

    for (const tab of ["Metadata", "Provenance", "Forensics", "Timeline", "Matches"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tabpanel", { name: tab.toLowerCase() })).toBeVisible();
      await shot(`06-report-${tab.toLowerCase()}`);
    }

    const textId = await createTextAnalysis(
      page,
      "The council met on Tuesday evening to review the harbour proposal. Members asked for " +
        "a revised budget and a traffic study before the next vote. The chair said the " +
        "decision would be published on the town website within a week.",
      "Council minutes",
    );
    await waitForCompleted(page, textId);
    await shot("07-text-report");

    await page.goto("/dashboard");
    await shot("08-dashboard-with-analyses");
  });
});
