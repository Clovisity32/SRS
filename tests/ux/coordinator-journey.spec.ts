/**
 * Coordinator Journey — Smart Relief Allocator
 *
 * Role: School coordinator who manages teacher relief assignments.
 * Entry: http://localhost:8080 (static index.html)
 * Auth: Firebase anonymous sign-in (automatic)
 *
 * Note: Uses stable element IDs instead of data-testid — the app has
 * no build step, so adding testids would require HTML edits. All IDs
 * used here are defined in the HTML and are unlikely to change.
 */

import { test, expect, Page } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

const SS = (name: string) => path.join("debug", `ux-coordinator-${name}.png`);

async function waitForApp(page: Page) {
  // Firebase anonymous auth + Firestore snapshot — give up to 20 s
  await page.waitForFunction(
    () =>
      document.getElementById("loadingOverlay")?.classList.contains("hidden"),
    { timeout: 20000 },
  );
  await page.waitForSelector("#mainContent:not(.hidden)", { timeout: 5000 });
}

// ── Step 1: App loads ────────────────────────────────────────────────────────
test("01 — app loads and shows dashboard", async ({ page }) => {
  await page.goto("/");
  await waitForApp(page);

  await page.screenshot({ path: SS("01-load") });

  await expect(page.locator("#assignReliefBtn")).toBeVisible();
  await expect(page.locator(".tab-button").first()).toBeVisible();
  await expect(page.locator("#dateDisplay")).not.toHaveText("");
});

// ── Step 2: Assign Relief modal opens ────────────────────────────────────────
test("02 — Assign Relief modal opens with all 3 steps visible", async ({
  page,
}) => {
  await page.goto("/");
  await waitForApp(page);

  await page.click("#assignReliefBtn");
  await page.screenshot({ path: SS("02-modal-open") });

  await expect(page.locator("#assignReliefModal")).toBeVisible();
  // Step badges 1 (teacher), 2 (date), 3 (periods) must all be present
  const badges = page.locator(".step-badge");
  await expect(badges).toHaveCount(3);
  await expect(page.locator("#teacherSelect")).toBeVisible();
  await expect(page.locator("#calendarContainer")).toBeVisible();
  await expect(page.locator("#findTeachersBtn")).toBeDisabled();
});

// ── Step 3: Selecting a teacher populates the period list ────────────────────
test("03 — selecting a teacher populates period list", async ({ page }) => {
  await page.goto("/");
  await waitForApp(page);

  await page.click("#assignReliefBtn");

  const teacherSelect = page.locator("#teacherSelect");
  const optionCount = await teacherSelect.locator("option").count();

  if (optionCount <= 1) {
    // No teachers loaded — record and skip gracefully
    await page.screenshot({ path: SS("03-no-teachers") });
    test.skip();
    return;
  }

  await teacherSelect.selectOption({ index: 1 });
  await page.screenshot({ path: SS("03-teacher-selected") });

  // Period container should update (either shows periods or "no classes" message)
  const container = page.locator("#periodSelectContainer");
  await expect(container).not.toContainText("Please select a teacher");
});

// ── Step 4: Full assign flow ─────────────────────────────────────────────────
// Correct two-phase flow:
//   Phase A — "Find Available Teachers" creates pending task(s) and closes modal
//   Phase B — clicking a pending task in the sidebar sets selectedReliefContext,
//             which triggers the tier view; then "Assign" completes the assignment
test("04 — full assign flow: pending task → click in sidebar → tier view → assign", async ({
  page,
}) => {
  await page.goto("/");
  await waitForApp(page);

  // ── Phase A: ensure at least one pending task exists ────────────────────────
  // Use existing Firestore data if present; otherwise create a task on a future date.
  let hasPendingTask =
    (await page.locator(".relief-task-item").count()) > 0 &&
    (await page.locator(".relief-task-item").first().getAttribute("class")) !==
      null;

  if (!hasPendingTask) {
    // Navigate forward one day to find a clean slate
    await page.click("#nextDayBtn");
    await page.waitForTimeout(300);

    await page.click("#assignReliefBtn");
    const teacherSelect = page.locator("#teacherSelect");
    if ((await teacherSelect.locator("option").count()) <= 1) {
      test.skip();
      return;
    }
    await teacherSelect.selectOption({ index: 1 });
    const firstCheckbox = page.locator(".period-checkbox").first();
    if (!(await firstCheckbox.isVisible())) {
      test.skip();
      return;
    }
    await firstCheckbox.check();
    await page.click("#findTeachersBtn");
    await expect(page.locator("#assignReliefModal")).toBeHidden();
  }

  await page.screenshot({ path: SS("04a-pending-task-in-sidebar") });

  // ── Phase B: click the pending task to enter tier-assignment mode ────────────
  const pendingTask = page.locator(".relief-task-item").first();
  await expect(pendingTask).toBeVisible();
  await pendingTask.click();
  await page.screenshot({ path: SS("04b-tier-view") });

  // Timetable must now show tiered teacher rows
  await expect(page.locator(".tier-header").first()).toBeVisible();

  // An Assign button must exist for at least one teacher
  const assignBtn = page.locator(".assign-in-timetable-btn").first();
  await expect(assignBtn).toBeVisible();

  await assignBtn.click();
  await page.screenshot({ path: SS("04c-assigned") });

  // The sidebar card must update (assigned card has green background)
  await expect(page.locator("#reliefTasksSidebar")).toContainText("Period");
});

// ── Step 5: Duplicate teacher → inline error message ─────────────────────────
// If a teacher already has a task for today (real Firestore data), selecting
// them again should immediately show the inline error on submit attempt.
// If no existing task, create one first then retry.
test("05 — duplicate teacher on same day shows inline error", async ({
  page,
}) => {
  await page.goto("/");
  await waitForApp(page);

  await page.click("#assignReliefBtn");
  const teacherSelect = page.locator("#teacherSelect");
  if ((await teacherSelect.locator("option").count()) <= 1) {
    test.skip();
    return;
  }

  // Pick a teacher that already has a task today (index 1 = first real teacher).
  // If Firestore already has them as unavailable, the error fires immediately.
  // If not, we create their task first, then retry — either way we reach the error.
  await teacherSelect.selectOption({ index: 1 });
  const firstCheckbox = page.locator(".period-checkbox").first();
  if (!(await firstCheckbox.isVisible())) {
    test.skip();
    return;
  }
  await firstCheckbox.check();
  await page.locator("#findTeachersBtn").click({ force: true });

  const errorMsg = page.locator("#modalErrorMessage");
  const modalStillOpen = await page.locator("#assignReliefModal").isVisible();

  if (!modalStillOpen) {
    // First attempt succeeded (teacher had no task yet) — retry to trigger error
    await page.click("#assignReliefBtn");
    await teacherSelect.selectOption({ index: 1 });
    const cb = page.locator(".period-checkbox").first();
    if (await cb.isVisible()) await cb.check();
    await page.locator("#findTeachersBtn").click({ force: true });
  }

  await page.screenshot({ path: SS("05-duplicate-error") });
  await expect(errorMsg).toBeVisible();
  await expect(errorMsg).not.toHaveText("");
});

// ── Step 6: Tab navigation ───────────────────────────────────────────────────
test("06 — tab navigation switches panels", async ({ page }) => {
  await page.goto("/");
  await waitForApp(page);

  // Navigate to Relief Load tab
  await page.click('[data-tab="load"]');
  await page.screenshot({ path: SS("06-load-tab") });
  await expect(page.locator("#load")).not.toHaveClass(/hidden/);
  await expect(page.locator("#timetable")).toHaveClass(/hidden/);

  // Navigate to Daily Summary tab
  await page.click('[data-tab="summary"]');
  await page.screenshot({ path: SS("06-summary-tab") });
  await expect(page.locator("#summary")).not.toHaveClass(/hidden/);
});

// ── Step 7: Settings modal ───────────────────────────────────────────────────
test("07 — settings modal opens and accepts term dates", async ({ page }) => {
  await page.goto("/");
  await waitForApp(page);

  await page.click("#settingsBtn");
  await page.screenshot({ path: SS("07-settings-open") });

  await expect(page.locator("#settingsModal")).toBeVisible();
  await expect(page.locator("#term1")).toBeVisible();
  await expect(page.locator("#messageTemplateInput")).toBeVisible();

  await page.click("#saveSettingsBtn");
  await expect(page.locator("#settingsModal")).toBeHidden();
  await page.screenshot({ path: SS("07-settings-saved") });
});
