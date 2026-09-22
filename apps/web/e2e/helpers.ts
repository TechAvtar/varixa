import { expect, type Locator, type Page } from "@playwright/test";
import path from "node:path";

export const PASSWORD = "e2e-password-123456";
export const SAMPLE_IMAGE = path.resolve(__dirname, "fixtures/sample.jpg");

/** Long enough for language detection and the statistics step; plainly human-written. */
export const SAMPLE_TEXT = `The harbour master kept a ledger of every vessel that entered the bay, noting the tide, the weather and the cargo declared at the quay. Over the years the ledger became the town's memory: fishermen consulted it to settle arguments about storms, and the council read it aloud when the old lighthouse was finally repaired.

Nobody remembered who had started the ledger. The first pages were water-stained and written in a careful, slanting hand that recorded the price of salt beside the names of the boats. Later entries were shorter and more practical, but the habit of writing something every evening never broke, even during the winter when the bay froze and no ship came for weeks.`;

/** Verixa's own form alerts (Next also renders an empty route announcer with role=alert). */
export function formAlert(page: Page): Locator {
  return page.locator('[role="alert"][data-slot="alert"]');
}

/** Production pages hydrate as soon as their scripts have run; wait for that before typing. */
async function open(page: Page, url: string) {
  await page.goto(url, { waitUntil: "networkidle" });
}

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/**
 * Client components only react to input after hydration, and in dev mode that can land after
 * Playwright's first fill. Repeat the interaction until the UI reflects it.
 */
async function untilReflected(act: () => Promise<void>, reflected: Locator, attempts = 8) {
  for (let i = 0; i < attempts; i += 1) {
    await act();
    try {
      await expect(reflected).toBeVisible({ timeout: 1_500 });
      return;
    } catch {
      // not hydrated yet; try again
    }
  }
  throw new Error("the form never reflected the input");
}

/** Registers a new account through the UI; ends on the dashboard, signed in. */
export async function register(page: Page, email = uniqueEmail(), name = "E2E User") {
  await open(page, "/register");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  // The first server actions after a cold start can take a while; allow for it.
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
  return { email, name };
}

/** Signs out and waits for the redirect, so the next navigation cannot race it. */
export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 });
}

export async function login(page: Page, email: string, password = PASSWORD) {
  await open(page, "/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Selects a file in the upload form (path or in-memory payload) and waits for the preview. */
export async function pickImage(
  page: Page,
  file: string | { name: string; mimeType: string; buffer: Buffer },
) {
  await open(page, "/analyses/new?mode=image");
  await untilReflected(
    () => page.locator('input[name="file"]').setInputFiles(file),
    page.getByRole("button", { name: "Remove" }),
  );
}

/** Uploads the sample JPEG and returns the analysis id from the report URL. */
export async function createImageAnalysis(page: Page, title?: string): Promise<string> {
  await pickImage(page, SAMPLE_IMAGE);
  if (title) await page.getByLabel("Title (optional)").fill(title);
  await page.getByRole("button", { name: "Start analysis" }).click();
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]{36}/);
  return analysisIdFromUrl(page);
}

/** Pastes text into the text form and waits until the submit button reacts to it. */
export async function pasteText(page: Page, text: string) {
  await open(page, "/analyses/new?mode=text");
  await untilReflected(
    () => page.getByLabel("Text", { exact: true }).fill(text),
    page.getByRole("button", { name: "Start analysis" }).and(page.locator(":enabled")),
  );
}

export async function createTextAnalysis(page: Page, text = SAMPLE_TEXT, title?: string) {
  await pasteText(page, text);
  if (title) await page.getByLabel("Title (optional)").fill(title);
  await page.getByRole("button", { name: "Start analysis" }).click();
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]{36}/);
  return analysisIdFromUrl(page);
}

export function analysisIdFromUrl(page: Page): string {
  const match = /\/analyses\/([0-9a-f-]{36})/.exec(page.url());
  if (!match) throw new Error(`no analysis id in ${page.url()}`);
  return match[1];
}

/** The status badge in the report header (the Processing card title is not a status). */
export function statusBadge(page: Page): Locator {
  return page
    .locator("main header")
    .getByText(/^(Queued|Processing|Completed|Failed)$/)
    .first();
}

/** The report page does not auto-refresh; reload until the pipeline has finished. */
export async function waitForCompleted(page: Page, id: string, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await page.goto(`/analyses/${id}?tab=overview`);
    const status = (await statusBadge(page).textContent())?.trim();
    if (status === "Completed") return;
    if (status === "Failed") throw new Error(`analysis ${id} failed`);
    if (Date.now() > deadline)
      throw new Error(`analysis ${id} still ${status} after ${timeoutMs}ms`);
    await page.waitForTimeout(1_000);
  }
}
