import { expect, test } from "./fixtures";

test("add posting: known URL gives a preview, save opens the detail page", async ({ page }) => {
  await page.goto("/");
  await page.locator("#add-posting").click();
  await page.locator('[data-test="ap-url"] input').fill("https://fake.test/x");
  await page.locator('[data-test="ap-fetch"]').click();
  await expect(page.locator('[data-test="ap-preview"]')).toContainText("Fetched x");
  await page.locator('[data-test="ap-save"]').click();
  await expect(page).toHaveURL(/\/applications\/\d+$/);
  await expect(page.locator('[data-test="application-detail"]')).toContainText("Fetched x");
});

test("add posting: unknown URL falls back to the manual form with the URL prefilled", async ({ page }) => {
  await page.goto("/");
  await page.locator("#add-posting").click();
  await page.locator('[data-test="ap-url"] input').fill("https://unbekannt.test/y");
  await page.locator('[data-test="ap-fetch"]').click();
  await expect(page.locator('[data-test="ap-manual"]')).toBeVisible();
  await expect(page.locator('[data-test="ap-m-url"] input')).toHaveValue("https://unbekannt.test/y");
});
