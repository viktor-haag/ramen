import { expect, test } from "./fixtures";

test("fit evaluation: single, bulk, and reset by deleting the user profile", async ({ page, fakeLlmUrl }) => {
  // 1. LLM configuration pointing at the fake server.
  await page.goto("/settings");
  await page.locator('[data-test="llm-add"]').click();
  await page.locator('[data-test="llm-name"] input').fill("Fake LLM");
  await page.locator('[data-test="llm-provider"]').click();
  await page.getByRole("option", { name: "OpenAI-compatible" }).click();
  await page.locator('[data-test="llm-base-url"] input').fill(fakeLlmUrl);
  await page.locator('[data-test="llm-model"] input').fill("fake-model");
  await page.locator('[data-test="llm-save"]').click();
  await expect(page.locator('[data-test^="llm-config-"]')).toContainText("Fake LLM");

  // 2. Free text and a generated profile.
  await page.goto("/me");
  const freeText = page.locator('[data-test="free-text"] textarea:not(.v-textarea__sizer)');
  await freeText.fill("Python developer, 5 years of experience.");
  await freeText.blur(); // autosave on blur enables "Create profile"
  await expect(page.locator('[data-test="generate"]')).toBeEnabled();
  await page.locator('[data-test="generate"]').click();
  await expect(page.locator('[data-test="md-input"] textarea:not(.v-textarea__sizer)')).toHaveValue(/## Summary/);

  // 3. A search profile and a search run with the fake plugin: five postings.
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
  const dots = rows.locator('[data-test="fit-dot"]');
  const good = rows.locator('[data-test="fit-dot"].fit-dot--good');
  const none = rows.locator('[data-test="fit-dot"].fit-dot--none');
  await expect(none).toHaveCount(5);

  // 4. Evaluate one posting from its drawer.
  const title = (await rows.first().locator(".v-list-item-title").innerText()).trim();
  await rows.first().click();
  const drawer = page.locator('[data-test="posting-drawer"]');
  await drawer.locator('[data-test="fit-evaluate"]').click();
  await expect(drawer.locator('[data-test="fit-explanation"]')).toHaveText("Strong Python match.", { timeout: 15_000 });
  await expect(drawer.locator('[data-test="fit-dot"].fit-dot--good')).toHaveCount(1);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).not.toHaveClass(/v-navigation-drawer--active/); // closed drawers stay in the DOM off-screen
  await expect(rows.filter({ hasText: title }).locator('[data-test="fit-dot"].fit-dot--good')).toHaveCount(1, { timeout: 15_000 });
  await expect(good).toHaveCount(1);

  // 5. Evaluate all visible: the confirm dialog names the remaining four.
  await expect(page.locator('[data-test="fit-bulk"]')).toContainText("(4)", { timeout: 15_000 });
  await page.locator('[data-test="fit-bulk"]').click();
  await expect(page.getByText("Evaluate 4 postings?")).toBeVisible();
  await page.locator('[data-test="confirm-ok"]').click();
  await expect(good).toHaveCount(5, { timeout: 30_000 });
  await expect(dots).toHaveCount(5);

  // 6. Deleting the user profile removes all evaluations.
  await page.goto("/settings");
  await page.locator('[data-test="danger-delete-profile"]').click();
  await page.locator('[data-test="ttc-input"] input').fill("DELETE");
  await page.locator('[data-test="ttc-ok"]').click();
  await expect(page.locator('[data-test="ttc-input"]')).toBeHidden();
  await expect(page.locator(".v-snackbar")).toContainText("User profile deleted");
  // In-app navigation (no reload): the cleared frontend state must not bring back old results.
  await page.locator('.v-navigation-drawer a[href="/feed"]').click();
  await expect(page).toHaveURL(/\/feed$/);
  await expect(rows).toHaveCount(5);
  await expect(none).toHaveCount(5);
  await expect(good).toHaveCount(0);
});
