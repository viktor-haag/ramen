import { expect, test } from "./fixtures";

test("feed: refresh, dismiss, filter, save, board and language", async ({ page }) => {
  await page.goto("/profiles");
  await page.locator('[data-test="profile-add"]').click();
  await page.locator('[data-test="pf-name"] input').fill("Test");
  await page.locator('[data-test="pf-keywords"] input').fill("alpha");
  await page.locator('[data-test="pf-keywords"] input').press("Enter");
  await page.locator('[data-test="pf-save"]').click();
  await expect(page.locator('[data-test="profile-1"]')).toBeVisible();

  await page.goto("/feed");
  await page.locator('[data-test="refresh"]').click();
  const rows = page.locator('[data-test="feed-row"]');
  await expect(rows).toHaveCount(5);

  // second entry: j selects it, v dismisses it
  const dismissedTitle = (await rows.nth(1).locator(".v-list-item-title").innerText()).trim();
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await page.keyboard.press("v");
  await expect(rows).toHaveCount(4);
  await expect(page.getByText(dismissedTitle, { exact: true })).toHaveCount(0);

  // dismissed filter: only the dismissed one
  await page.locator('[data-test="triage-new"]').click();
  await page.locator('[data-test="triage-saved"]').click();
  await page.locator('[data-test="triage-dismissed"]').click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText(dismissedTitle);

  // back to new+saved, save the first
  await page.locator('[data-test="triage-dismissed"]').click();
  await page.locator('[data-test="triage-new"]').click();
  await page.locator('[data-test="triage-saved"]').click();
  await expect(rows).toHaveCount(4);
  const savedTitle = (await rows.first().locator(".v-list-item-title").innerText()).trim();
  await rows.first().locator('[data-test="row-save"]').click();
  await expect(rows.first().locator(".v-chip", { hasText: "Saved" })).toBeVisible();

  await page.goto("/applications");
  const saved = page.locator('.column[data-status="saved"]');
  await expect(saved.locator(".text-subtitle-2")).toContainText("Saved");
  await expect(saved).toContainText(savedTitle);

  // language switch persists across reload
  await page.goto("/settings");
  await page.locator('[data-test="language-select"]').click();
  await page.getByRole("option", { name: /Deutsch/ }).click();
  await page.goto("/applications");
  await expect(page.locator('.column[data-status="saved"] .text-subtitle-2')).toContainText("gemerkt");
  await page.reload();
  await expect(page.locator('.column[data-status="saved"] .text-subtitle-2')).toContainText("gemerkt");
});

test("feed: a profile with two keyword chips yields results for both", async ({ page }) => {
  await page.goto("/profiles");
  await page.locator('[data-test="profile-add"]').click();
  await page.locator('[data-test="pf-name"] input').fill("Two chips");
  for (const kw of ["alpha", "beta"]) {
    await page.locator('[data-test="pf-keywords"] input').fill(kw);
    await page.locator('[data-test="pf-keywords"] input').press("Enter");
  }
  await page.locator('[data-test="pf-save"]').click();
  await expect(page.locator('[data-test="profile-1"]')).toBeVisible();

  await page.goto("/feed");
  await page.locator('[data-test="refresh"]').click();
  const rows = page.locator('[data-test="feed-row"]');
  await expect(rows).toHaveCount(10);
  await expect(page.getByText("alpha job 1", { exact: true })).toBeVisible();
  await expect(page.getByText("beta job 1", { exact: true })).toBeVisible();
});
