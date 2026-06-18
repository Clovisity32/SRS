/**
 * Quick screenshot script — captures the current UI state.
 * Saves to debug/snapshot.png (desktop) and debug/snapshot-mobile.png (mobile).
 * Skips auth-gated views if no Google session is active.
 *
 * Run: node scripts/screenshot.js
 * Requires: npx playwright install chromium (done once)
 */

const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const BASE = "http://localhost:8080";
const DEBUG = path.join(__dirname, "..", "debug");

async function waitForApp(page) {
  try {
    await page.waitForSelector("#mainContent:not(.hidden)", { timeout: 8000 });
    return true;
  } catch {
    const loginVisible = await page.locator("#loginScreen").first().isVisible();
    return loginVisible ? false : null;
  }
}

(async () => {
  if (!fs.existsSync(DEBUG)) fs.mkdirSync(DEBUG, { recursive: true });

  const browser = await chromium.launch();

  // ── Desktop ──────────────────────────────────────────────────────────────
  {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });
    await page.goto(BASE, { waitUntil: "networkidle" });
    const authed = await waitForApp(page);

    if (authed) {
      // Open Settings modal to test the flex layout fix
      const settingsBtn = page.locator("#settingsBtn");
      if (await settingsBtn.first().isVisible()) {
        await settingsBtn.first().click();
        await page.waitForSelector("#settingsModal", {
          state: "visible",
          timeout: 3000,
        });
        await page.screenshot({
          path: path.join(DEBUG, "snapshot-settings.png"),
          fullPage: false,
        });
        console.log(
          "  saved debug/snapshot-settings.png (settings modal open)",
        );
        // Scroll the content to bottom to verify Save button is visible without scrolling
        await page
          .locator("#settingsModal .overflow-y-auto")
          .first()
          .evaluate((el) => (el.scrollTop = el.scrollHeight));
        await page.screenshot({
          path: path.join(DEBUG, "snapshot-settings-scrolled.png"),
          fullPage: false,
        });
        console.log(
          "  saved debug/snapshot-settings-scrolled.png (content scrolled to bottom)",
        );
        await page.keyboard.press("Escape");
      }
    }

    await page.screenshot({
      path: path.join(DEBUG, "snapshot.png"),
      fullPage: false,
    });
    console.log("  saved debug/snapshot.png (desktop)");
    await page.close();
  }

  // ── Mobile (390px) ───────────────────────────────────────────────────────
  {
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
    });
    await page.goto(BASE, { waitUntil: "networkidle" });
    const authed = await waitForApp(page);

    if (authed) {
      // Open Settings modal on mobile to test save button visibility
      const mobileSettingsBtn = page.locator("#mobileSettingsNavBtn");
      if (await mobileSettingsBtn.first().isVisible()) {
        await mobileSettingsBtn.first().click();
        await page.waitForSelector("#settingsModal", {
          state: "visible",
          timeout: 3000,
        });
        await page.screenshot({
          path: path.join(DEBUG, "snapshot-mobile-settings.png"),
          fullPage: false,
        });
        console.log(
          "  saved debug/snapshot-mobile-settings.png (mobile settings modal)",
        );

        // Check Save & Close button is visible without outer scroll
        const saveBtn = page.locator("#saveSettingsBtn");
        const visible = await saveBtn.first().isVisible();
        const box = await saveBtn.first().boundingBox();
        console.log(
          `  Save button visible: ${visible}, boundingBox: ${JSON.stringify(box)}`,
        );
        if (box && box.y + box.height <= 844) {
          console.log("  PASS: Save button is within mobile viewport");
        } else {
          console.log("  FAIL: Save button is outside mobile viewport bounds");
        }
      }
    }

    await page.screenshot({
      path: path.join(DEBUG, "snapshot-mobile.png"),
      fullPage: false,
    });
    console.log("  saved debug/snapshot-mobile.png (mobile)");
    await page.close();
  }

  await browser.close();
  console.log("Done.");
})();
