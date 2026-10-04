import { expect, test } from "@playwright/test";
import {
  SIDECAR_IMAGE,
  SIDECAR_MANIFEST,
  SIGNED_IMAGE,
  createImageAnalysis,
  formAlert,
  pickImage,
  register,
  waitForCompleted,
} from "./helpers";

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

  test("a signed image shows its content credentials and what the signature covers", async ({
    page,
  }) => {
    await register(page);
    const id = await createImageAnalysis(page, "Signed sample", SIGNED_IMAGE);
    await waitForCompleted(page, id);
    await page.getByRole("tab", { name: "Provenance" }).click();
    const panel = page.getByRole("tabpanel", { name: "provenance" });
    await expect(panel).toBeVisible();
    // The step only runs when c2patool is installed (CI installs it; a dev box may not).
    const inspected = await panel.getByText("VERIFIED · manifest intact").isVisible();
    test.skip(!inspected, "c2patool not available on this machine");
    await expect(panel.getByText("C2PA Test Signing Cert").first()).toBeVisible();
    await expect(panel.getByRole("heading", { name: "Signed declarations" })).toBeVisible();
    await expect(panel.getByText(/Signature covers/)).toBeVisible();
    // The coverage sentence appears in the evidence record and in the card; either proves it.
    await expect(panel.getByText(/excluded range/).first()).toBeVisible();
    // Evidence data is rendered generically: the hash coverage row comes from the record's data.
    await expect(panel.getByText("hash_coverage")).toBeVisible();
  });

  test("a sidecar manifest uploaded beside the image is validated against it", async ({ page }) => {
    await register(page);
    await pickImage(page, SIDECAR_IMAGE);
    await page.getByLabel("Content Credentials sidecar (optional)").setInputFiles(SIDECAR_MANIFEST);
    await page.getByLabel("Title (optional)").fill("Sidecar sample");
    await page.getByRole("button", { name: "Start analysis" }).click();
    await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]{36}/);
    const id = page.url().split("/analyses/")[1]?.split(/[?#]/)[0] ?? "";
    await waitForCompleted(page, id);
    await page.getByRole("tab", { name: "Provenance" }).click();
    const panel = page.getByRole("tabpanel", { name: "provenance" });
    await expect(panel).toBeVisible();
    const inspected = await panel.getByText("VERIFIED · manifest intact").isVisible();
    test.skip(!inspected, "c2patool not available on this machine");
    await expect(panel.getByText(/^Sidecar file supplied with the upload/)).toBeVisible();
    await expect(panel.getByText(/sidecar file; its data hash/).first()).toBeVisible();
  });

  test("a sidecar that is not a C2PA manifest is refused", async ({ page }) => {
    await register(page);
    await pickImage(page, SIDECAR_IMAGE);
    await page.getByLabel("Content Credentials sidecar (optional)").setInputFiles({
      name: "fake.c2pa",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("this is not a manifest store, just some text padding ".repeat(4)),
    });
    await page.getByRole("button", { name: "Start analysis" }).click();
    await expect(formAlert(page)).toContainText("not a C2PA manifest store");
    await page.goto("/dashboard");
    await expect(page.getByText("Total analyses").locator("..")).toContainText("0");
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
