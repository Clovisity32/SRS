/**
 * Auth Visibility Test — Smart Relief Allocator
 *
 * Verifies that chrome elements (sidebar, header, mobile nav) are hidden
 * before sign-in and that the login screen is the only visible region.
 * Does NOT attempt Google OAuth — tests are limited to the pre-auth state.
 */

import { test, expect } from "@playwright/test";
import * as path from "path";

const SS = (name: string) => path.join("debug", `auth-visibility-${name}.png`);

test("pre-auth: login screen visible, chrome hidden", async ({ page }) => {
  await page.goto("/");

  // Give Firebase a moment to initialise (onAuthStateChanged fires async)
  await page.waitForFunction(
    () => {
      const login = document.getElementById("loginScreen");
      return login !== null && !login.classList.contains("hidden");
    },
    { timeout: 10000 },
  );

  await page.screenshot({ path: SS("01-pre-auth") });

  // Login screen must be visible
  await expect(page.locator("#loginScreen")).toBeVisible();
  await expect(page.locator("#signInWithGoogleBtn")).toBeVisible();

  // Access denied screen must remain hidden
  await expect(page.locator("#accessDeniedScreen")).toBeHidden();

  // App chrome must be hidden until authenticated
  await expect(page.locator("#sidebar")).toBeHidden();
  await expect(page.locator("#appHeader")).toBeHidden();

  // Main content and loading overlay must not leak through
  await expect(page.locator("#mainContent")).toBeHidden();
  await expect(page.locator("#loadingOverlay")).toBeHidden();
});

test("pre-auth: mobileBottomNav has hidden class", async ({ page }) => {
  await page.goto("/");

  await page.waitForFunction(
    () => document.getElementById("loginScreen") !== null,
    { timeout: 10000 },
  );

  // Check the class directly — on desktop md:hidden would hide it anyway,
  // so we verify the explicit `hidden` class is present before auth
  const hasHidden = await page.evaluate(
    () =>
      document
        .getElementById("mobileBottomNav")
        ?.classList.contains("hidden") ?? false,
  );
  expect(hasHidden).toBe(true);
});
