import { type Page } from "@playwright/test";
import { expect, test } from "./fixtures";

async function configureFakeLlm(page: Page, fakeLlmUrl: string) {
  await page.goto("/settings");
  await page.locator('[data-test="llm-add"]').click();
  await page.locator('[data-test="llm-name"] input').fill("Fake LLM");
  await page.locator('[data-test="llm-provider"]').click();
  await page.getByRole("option", { name: "OpenAI-compatible" }).click();
  await page.locator('[data-test="llm-base-url"] input').fill(fakeLlmUrl);
  await page.locator('[data-test="llm-model"] input').fill("fake-model");
  await page.locator('[data-test="llm-save"]').click();
  await expect(page.locator('[data-test^="llm-config-"]')).toContainText("Fake LLM");
}

/** Creates an application and opens its detail view. */
async function openApplication(page: Page, request: import("@playwright/test").APIRequestContext, baseURL: string) {
  const res = await request.post(`${baseURL}/api/postings`, { data: { title: "Cover Me", company: "Acme" } });
  expect(res.ok()).toBeTruthy();
  await page.goto("/applications");
  await page.locator('.column[data-status="saved"] [data-id]', { hasText: "Cover Me" }).click();
  await expect(page.locator('[data-test="cover-letter-section"]')).toBeVisible();
}

test("cover letter: LaTeX draft opens in the editor and says that the PDF is unavailable", async ({ page, request, baseURL, fakeLlmUrl }) => {
  await configureFakeLlm(page, fakeLlmUrl);
  await openApplication(page, request, baseURL);

  await page.locator('[data-test="cl-create"]').click();
  await expect(page.locator('[data-test="cl-dialog"]')).toBeVisible();
  await expect(page.locator('[data-test="cl-submit"]')).toBeEnabled();
  await page.locator('[data-test="cl-submit"]').click();

  await expect(page).toHaveURL(/\/applications\/\d+\/cover-letter$/);
  await expect(page.locator('[data-test="cl-msg-assistant"]').first()).toHaveText("Draft ready.", { timeout: 30_000 });
  await expect(page.locator('[data-test="cl-no-compiler"]')).toBeVisible();
  await expect(page.locator('[data-test="cl-editor"]')).toContainText("Dear Hiring Team");
});

test("cover letter: text letter with chat request, manual edit and attachment", async ({ page, request, baseURL, fakeLlmUrl }) => {
  await configureFakeLlm(page, fakeLlmUrl);
  await openApplication(page, request, baseURL);

  // 1. Create a plain text letter.
  await page.locator('[data-test="cl-create"]').click();
  await page.locator('[data-test="cl-format-text"]').click();
  await expect(page.locator('[data-test="cl-submit"]')).toBeEnabled();
  await page.locator('[data-test="cl-submit"]').click();
  await expect(page).toHaveURL(/\/applications\/\d+\/cover-letter$/);
  const assistant = page.locator('[data-test="cl-msg-assistant"]');
  await expect(assistant.first()).toHaveText("Draft ready.", { timeout: 30_000 });
  const editor = page.locator('[data-test="cl-editor"]');
  await expect(editor).toContainText("Dear Hiring Team");

  // 2. A chat request yields a second assistant message and a changed letter.
  await page.locator('[data-test="cl-chat-input"] textarea:not(.v-textarea__sizer)').fill("Make the opening shorter");
  await page.locator('[data-test="cl-chat-send"]').click();
  await expect(assistant).toHaveCount(2, { timeout: 30_000 });
  await expect(assistant.last()).toHaveText("Updated.");
  await expect(editor).toContainText("Revised opening paragraph.");

  // 3. Edit by hand and save.
  await editor.locator(".cm-content").click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("P.S. Handwritten line.");
  await expect(page.locator('[data-test="cl-save"]')).toBeEnabled();
  await page.locator('[data-test="cl-save"]').click();
  await expect(page.locator('[data-test="cl-save"]')).toBeDisabled();
  await expect(page.locator('[data-test="cl-attach"]')).toBeEnabled();

  // 4. Save as attachment and go back to the application.
  await page.locator('[data-test="cl-attach"]').click();
  await expect(page.locator(".v-snackbar")).toContainText("saved as an attachment");
  await page.locator('[data-test="cl-back"]').click();
  await expect(page.locator('[data-test="cover-letter-section"]')).toBeVisible();
  await page.getByRole("tab", { name: "Attachments" }).click();
  await expect(page.locator('[data-test="attachment-list"]')).toContainText(/Cover_letter_Acme/);
});
