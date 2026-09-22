import { expect, test } from "@playwright/test";
import { createImageAnalysis, pasteText, register, statusBadge, waitForCompleted } from "./helpers";

test.describe("report export", () => {
  test("a PDF is generated, listed and downloadable through a signed link", async ({ page }) => {
    await register(page);
    const id = await createImageAnalysis(page, "Export me");
    await waitForCompleted(page, id);

    await page.getByRole("button", { name: "Generate PDF report" }).click();
    await expect(page).toHaveURL(/report=ready/);
    const download = page.getByRole("link", { name: "Download" });
    await expect(download).toBeVisible();
    await expect(page.getByText("PDF", { exact: true })).toBeVisible();

    const href = await download.getAttribute("href");
    expect(href).toMatch(/\/api\/v1\/files\/.+\?exp=\d+&sig=[0-9a-f]{64}/);
    const response = await page.request.get(href as string);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("application/pdf");
    expect(response.headers()["content-disposition"]).toContain("verixa-report-");
    const body = await response.body();
    expect(body.subarray(0, 5).toString("latin1")).toBe("%PDF-");

    // A tampered signature opens nothing.
    const tampered = (href as string).replace(/sig=[0-9a-f]{4}/, "sig=0000");
    expect((await page.request.get(tampered)).status()).toBe(403);
  });

  test("export is unavailable until the analysis has completed", async ({ page }) => {
    await register(page);
    await pasteText(page, "Short note.");
    await page.getByRole("button", { name: "Start analysis" }).click();
    await expect(page).toHaveURL(/\/analyses\//);
    // Straight after submission the status is queued/processing or already done; the button
    // is enabled only in the latter case, never for an unfinished analysis.
    const status = (await statusBadge(page).textContent())?.trim();
    const button = page.getByRole("button", { name: "Generate PDF report" });
    if (status === "Completed") await expect(button).toBeEnabled();
    else await expect(button).toBeDisabled();
  });
});
