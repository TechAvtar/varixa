// Records the Verixa product demo with Playwright, one continuous take, paced to the voice-over.
//
//   node demo/record.mjs            (from the repository root; servers must be running)
//
// Frames come straight from Chromium's screencast (1280x720 CSS pixels at device scale 1.5, so a
// sharp 1920x1080 picture), each with its own timestamp; Playwright's built-in recorder pads a
// high-DPI page into a corner. Each scene is held for at least its narration length
// (demo/out/voice/durations.json, or an estimate before the voice exists). Waiting for an analysis
// is recorded as an "excluded" interval that the editor cuts out. Outputs: demo/out/raw/frames/*.jpg,
// demo/out/raw/frames.json (file + epoch timestamp) and demo/out/raw/marks.json (epoch seconds).
//
// The account is a throwaway created on the local app; its password is random and never printed.

import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("@playwright/test");

const BASE = process.env.DEMO_BASE_URL ?? "http://localhost:3200";
const OUT = path.join(here, "out", "raw");
const SIGNED_IMAGE = path.join(root, "apps/web/e2e/fixtures/signed_sample.jpg");
const script = JSON.parse(fs.readFileSync(path.join(here, "script.json"), "utf8"));
const GAP = script.gap_after_seconds ?? 0.6;

const durationsFile = path.join(here, "out", "voice", "durations.json");
const voice = fs.existsSync(durationsFile) ? JSON.parse(fs.readFileSync(durationsFile, "utf8")) : {};
const need = (id) => {
  const scene = script.scenes.find((s) => s.id === id);
  const estimate = scene.text.split(/\s+/).length / 2.5; // ~150 words per minute
  return (voice[id] ?? estimate) + GAP;
};
if (!Object.keys(voice).length) console.log("No voice durations yet: pacing with estimates (dry run).");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A visible cursor: headless Chromium draws none, so the page gets a dot that follows the mouse
// and a ripple on every click.
const CURSOR = `
(() => {
  if (window.__demoCursor) return; window.__demoCursor = true;
  const add = () => {
    const c = document.createElement('div');
    c.style.cssText = 'position:fixed;z-index:2147483647;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:rgba(17,24,39,.55);border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);pointer-events:none;left:-40px;top:-40px;transition:transform .12s';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      c.style.transform = 'scale(.7)';
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;z-index:2147483646;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;border:2px solid rgba(37,99,235,.8);pointer-events:none;left:' + e.clientX + 'px;top:' + e.clientY + 'px;transition:transform .45s ease-out,opacity .45s ease-out';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 500);
    }, true);
    addEventListener('mouseup', () => { c.style.transform = 'scale(1)'; }, true);
    if (window.__demoMouse) { c.style.left = window.__demoMouse[0] + 'px'; c.style.top = window.__demoMouse[1] + 'px'; }
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', add); else add();
})();`;

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 1.5,
    colorScheme: "light",
    locale: "en-US",
  });
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  const FRAMES = path.join(OUT, "frames");
  fs.rmSync(FRAMES, { recursive: true, force: true });
  fs.mkdirSync(FRAMES, { recursive: true });
  const frames = [];
  const cdp = await context.newCDPSession(page);
  cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
    const file = `f${String(frames.length).padStart(6, "0")}.jpg`;
    fs.writeFileSync(path.join(FRAMES, file), Buffer.from(data, "base64"));
    frames.push({ file, t: metadata.timestamp });
    await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: 92,
    maxWidth: 1920,
    maxHeight: 1080,
    everyNthFrame: 1,
  });
  const t0 = Date.now();
  // Marks are epoch seconds, the clock the screencast timestamps use.
  const now = () => Date.now() / 1000;
  const elapsed = () => (Date.now() - t0) / 1000;

  let mouse = [640, 360];
  const glide = async (x, y, steps = 25) => {
    await page.mouse.move(x, y, { steps });
    mouse = [x, y];
    await page.evaluate((m) => (window.__demoMouse = m), mouse);
  };
  const glideTo = async (locator, steps = 25) => {
    await locator.scrollIntoViewIfNeeded();
    const box = await locator.boundingBox();
    if (!box) return;
    await glide(box.x + box.width / 2, box.y + box.height / 2, steps);
  };
  const click = async (locator) => {
    await glideTo(locator);
    await sleep(250);
    await locator.click();
  };
  const scrollBy = async (dy, steps = 12) => {
    for (let i = 0; i < steps; i++) {
      await page.mouse.wheel(0, dy / steps);
      await sleep(60);
    }
  };
  const go = async (url) => {
    await page.goto(BASE + url, { waitUntil: "networkidle" });
    await glide(...mouse, 1); // redraw the cursor at its last position after navigation
  };

  const marks = { scenes: [], excluded: [] };
  let current = null;
  const begin = (id) => {
    current = { id, start: now(), excluded: 0 };
  };
  // Time spent in excluded intervals does not count towards the scene's narration length.
  const effective = () => now() - current.start - current.excluded;
  const hold = async () => {
    const remaining = need(current.id) - effective();
    if (remaining > 0) await sleep(remaining * 1000);
  };
  const end = async () => {
    await hold();
    marks.scenes.push({ id: current.id, start: current.start, end: now() });
  };
  const excluded = async (fn) => {
    const start = now();
    await fn();
    const stop = now();
    marks.excluded.push({ start, end: stop, scene: current.id });
    current.excluded += stop - start;
  };
  const statusText = () =>
    page.getByText(/^(Queued|Processing|Completed|Failed)$/).first().textContent();
  const waitForCompleted = async (id, timeoutMs = 180_000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await page.goto(`${BASE}/analyses/${id}?tab=overview`, { waitUntil: "networkidle" });
      const status = (await statusText().catch(() => "")) ?? "";
      if (status === "Completed") return;
      if (status === "Failed") throw new Error(`analysis ${id} failed`);
      await sleep(1500);
    }
    throw new Error(`analysis ${id} did not complete in time`);
  };
  const idFromUrl = () => page.url().split("/analyses/")[1]?.split(/[?#]/)[0] ?? "";
  const tab = (name) => page.getByRole("tab", { name, exact: true }).or(page.locator("a", { hasText: new RegExp(`^${name}$`) })).first();
  const clickable = (name) => page.locator("a, button", { hasText: name }).first();

  // s01 — landing page
  await go("/");
  begin("s01_welcome");
  await glideTo(page.getByRole("heading", { name: "Verixa" }), 30);
  await sleep(1500);
  await glideTo(clickable("Create account"), 30);
  await end();

  // s02 — create an account
  begin("s02_account");
  await click(clickable("Create account"));
  await page.waitForURL("**/register");
  const email = `demo-${Date.now().toString(36)}@example.com`;
  const password = randomBytes(12).toString("base64url");
  await click(page.getByLabel("Name"));
  await page.getByLabel("Name").pressSequentially("Demo Analyst", { delay: 45 });
  await click(page.getByLabel("Email"));
  await page.getByLabel("Email").pressSequentially(email, { delay: 22 });
  await click(page.getByLabel("Password", { exact: true }));
  await page.getByLabel("Password", { exact: true }).pressSequentially(password, { delay: 22 });
  await click(page.getByRole("button", { name: "Create account" }));
  await page.waitForURL("**/dashboard", { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await end();

  // s03 — dashboard
  begin("s03_dashboard");
  await glideTo(page.getByRole("heading", { name: "Dashboard" }), 30);
  await sleep(800);
  await glide(640, 330, 30);
  await sleep(1200);
  const newAnalysis = page.getByRole("main").locator("a", { hasText: "New analysis" }).first();
  await glideTo(newAnalysis, 30);
  await hold();
  await newAnalysis.click();
  await page.waitForURL("**/analyses/new**");
  await page.waitForLoadState("networkidle");
  marks.scenes.push({ id: current.id, start: current.start, end: now() });

  // s04 — upload a signed image
  begin("s04_upload");
  await page.locator('input[type="file"]').first().setInputFiles(SIGNED_IMAGE);
  await sleep(600);
  await glideTo(page.getByText(/signed_sample\.jpg/).first(), 30).catch(() => {});
  await sleep(1200);
  await click(page.getByLabel("Title (optional)"));
  await page.getByLabel("Title (optional)").pressSequentially("Signed product photo", { delay: 60 });
  await sleep(800);
  await glideTo(page.getByText("Content Credentials sidecar (optional)").first(), 30);
  await hold();
  await click(page.getByRole("button", { name: "Start analysis" }));
  await page.waitForURL(/\/analyses\/[0-9a-f-]{36}/, { timeout: 60_000 });
  marks.scenes.push({ id: current.id, start: current.start, end: now() });
  const imageId = idFromUrl();

  // s05 — the pipeline runs (show the steps for the narration, cut the rest of the wait)
  begin("s05_pipeline");
  await page.waitForLoadState("networkidle");
  const steps = page.getByText(/steps?/i).first();
  await glideTo(steps, 30).catch(() => {});
  while (effective() < need("s05_pipeline")) {
    await sleep(2000);
    await page.reload({ waitUntil: "networkidle" });
    await glide(...mouse, 1);
  }
  await excluded(() => waitForCompleted(imageId));
  await end();

  // s06 — overview and evidence levels
  begin("s06_overview");
  await glide(640, 300, 30);
  await sleep(600);
  await scrollBy(700, 20);
  await sleep(1500);
  await scrollBy(700, 20);
  await sleep(1500);
  await hold();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await sleep(600);
  marks.scenes.push({ id: current.id, start: current.start, end: now() });

  // s07 — provenance
  begin("s07_provenance");
  await click(tab("Provenance"));
  await page.waitForLoadState("networkidle");
  await sleep(1500);
  await scrollBy(500, 20);
  await sleep(2000);
  await scrollBy(500, 20);
  await end();

  // s08 — forensics with a map overlay
  begin("s08_forensics");
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await click(tab("Forensics"));
  await page.waitForLoadState("networkidle");
  await sleep(800);
  const mapSelect = page.locator('select[id$="-map"]').first();
  if (await mapSelect.count()) {
    await glideTo(mapSelect, 30);
    const options = await mapSelect.locator("option").evaluateAll((o) => o.map((x) => x.value));
    const first = options.find((v) => v && v !== "none");
    if (first) {
      await mapSelect.selectOption(first);
      await sleep(2500);
      const second = options.find((v) => v && v !== "none" && v !== first);
      if (second) {
        await mapSelect.selectOption(second);
        await sleep(2000);
      }
    }
  }
  await scrollBy(400, 20);
  await end();

  // s09 — AI signal
  begin("s09_ai");
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await click(tab("AI Analysis"));
  await page.waitForLoadState("networkidle");
  await sleep(1500);
  await scrollBy(400, 20);
  await end();

  // s10 — a text analysis
  begin("s10_text");
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await click(clickable("New analysis"));
  await page.waitForURL("**/analyses/new**");
  await click(page.getByRole("tab", { name: "Text" }));
  await page.waitForURL("**mode=text**");
  await page.waitForLoadState("networkidle");
  const textBox = page.getByLabel("Text", { exact: true });
  await click(textBox);
  const lead = script.demo_text.slice(0, 44);
  await textBox.pressSequentially(lead, { delay: 30 });
  await textBox.fill(script.demo_text);
  await sleep(900);
  await page.getByLabel("Title (optional)").fill("Pangram article");
  await hold();
  await click(page.getByRole("button", { name: "Start analysis" }).and(page.locator(":enabled")));
  await page.waitForURL(/\/analyses\/[0-9a-f-]{36}/, { timeout: 60_000 });
  marks.scenes.push({ id: current.id, start: current.start, end: now() });
  const textId = idFromUrl();

  // s11 — phrase matches
  begin("s11_matches");
  await excluded(() => waitForCompleted(textId));
  await click(tab("Matches"));
  await page.waitForLoadState("networkidle");
  await sleep(1500);
  const firstLink = page.getByRole("tabpanel").getByRole("link").first();
  if (await firstLink.count()) await glideTo(firstLink, 30);
  await sleep(1500);
  await scrollBy(400, 20);
  await end();

  // s12 — PDF export
  begin("s12_export");
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await click(tab("Overview"));
  await page.waitForLoadState("networkidle");
  const exportButton = page.getByRole("button", { name: "Generate PDF report" });
  await glideTo(exportButton, 35);
  await sleep(500);
  await excluded(async () => {
    await exportButton.click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("link", { name: /download|pdf/i }).first().waitFor({ timeout: 60_000 });
  });
  await glideTo(page.getByRole("link", { name: /download|pdf/i }).first(), 30);
  await end();

  // s13 — outro on the dashboard
  begin("s13_outro");
  await go("/dashboard");
  await glide(640, 360, 30);
  await end();
  await sleep(1000);

  await cdp.send("Page.stopScreencast").catch(() => {});
  await sleep(500);
  marks.recording_end = now();
  await context.close();
  await browser.close();
  fs.writeFileSync(path.join(OUT, "frames.json"), JSON.stringify(frames));
  fs.writeFileSync(path.join(OUT, "marks.json"), JSON.stringify(marks, null, 2));
  console.log(`recorded ${elapsed().toFixed(1)} s, ${frames.length} frames -> demo/out/raw/frames`);
  console.log(`scenes ${marks.scenes.length}, excluded intervals ${marks.excluded.length}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
