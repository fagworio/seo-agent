import { test, expect } from "@playwright/test";

test("browser launches headless", async ({ page }) => {
  await page.goto("about:blank");
  expect(page.url()).toBe("about:blank");
});
