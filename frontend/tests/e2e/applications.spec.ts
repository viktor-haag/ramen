import { expect, test } from "./fixtures";

test("applications: drag to applied persists and is logged in the history", async ({ page, request, baseURL }) => {
  const res = await request.post(`${baseURL}/api/postings`, { data: { title: "Drag Me", company: "Acme" } });
  expect(res.ok()).toBeTruthy();

  await page.goto("/applications");
  const card = page.locator('.column[data-status="saved"] [data-id]', { hasText: "Drag Me" });
  const target = page.locator('.column[data-status="applied"] .drop-zone');
  await expect(card).toBeVisible();
  await card.dragTo(target);
  await expect(page.locator('.column[data-status="applied"]')).toContainText("Drag Me");

  await page.reload();
  await expect(page.locator('.column[data-status="applied"]')).toContainText("Drag Me");
  await expect(page.locator('.column[data-status="saved"]')).not.toContainText("Drag Me");

  await page.locator('.column[data-status="applied"] [data-id]', { hasText: "Drag Me" }).click();
  await expect(page.locator('[data-test="current-status"]')).toContainText("Applied");
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.locator('[data-test="status-history"] .v-timeline-item')).toHaveCount(2);
});

test("applications: context menu moves a card and the switch hides the saved column", async ({ page, request, baseURL }) => {
  const res = await request.post(`${baseURL}/api/postings`, { data: { title: "Menu Me", company: "Acme" } });
  expect(res.ok()).toBeTruthy();

  await page.goto("/applications");
  const card = page.locator('.column[data-status="saved"] [data-id]', { hasText: "Menu Me" });
  await expect(card).toBeVisible();
  await card.click({ button: "right" });
  await page.locator('[data-test="cm-status-applied"]').click();
  await expect(page.locator('.column[data-status="applied"]')).toContainText("Menu Me");

  await page.reload();
  await expect(page.locator('.column[data-status="applied"]')).toContainText("Menu Me");

  await expect(page.locator('.column[data-status="saved"]')).toBeVisible();
  await page.getByLabel("Hide saved").click({ force: true });
  await expect(page.locator('.column[data-status="saved"]')).toHaveCount(0);
});
