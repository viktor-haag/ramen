import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "./fixtures";

// Smallest valid 1x1 PNG.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("my profile: configure llm, upload, extract, create profile, delete via danger zone", async ({ page, fakeLlmUrl }) => {
  const dir = mkdtempSync(join(tmpdir(), "jobtracker-e2e-files-"));
  const txt = join(dir, "cv.txt");
  const png = join(dir, "scan.png");
  writeFileSync(txt, "Jane Doe\nPython developer, 5 years of experience.\n");
  writeFileSync(png, PNG);
  try {
    // 1. An openai_compatible config pointing at the fake server, image support on.
    await page.goto("/settings");
    await page.locator('[data-test="llm-add"]').click();
    await page.locator('[data-test="llm-name"] input').fill("Fake LLM");
    await page.locator('[data-test="llm-provider"]').click();
    await page.getByRole("option", { name: "OpenAI-compatible" }).click();
    await page.locator('[data-test="llm-base-url"] input').fill(fakeLlmUrl);
    await page.locator('[data-test="llm-model"] input').fill("fake-model");
    await page.locator('[data-test="llm-images"] input').check({ force: true });
    await page.locator('[data-test="llm-save"]').click();
    await expect(page.locator('[data-test^="llm-config-"]')).toContainText("Fake LLM");

    // 2. Upload a TXT and a PNG.
    await page.goto("/me");
    await page.locator('[data-test="doc-file"] input[type="file"]').setInputFiles(txt);
    await page.locator('[data-test="doc-upload"]').click();
    await expect(page.locator('[data-test="doc-list"]')).toContainText("cv.txt");
    await page.locator('[data-test="doc-file"] input[type="file"]').setInputFiles(png);
    await page.locator('[data-test="doc-upload"]').click();
    await expect(page.locator('[data-test="doc-list"]')).toContainText("scan.png");

    // 3. Extract the text of the PNG with the LLM.
    const pngRow = page.locator('[data-test="doc-list"] .v-list-item', { hasText: "scan.png" });
    await pngRow.locator('button[data-test^="doc-extract-"]').click();
    await expect(pngRow.locator('[data-test^="doc-status-"]')).toContainText("Usable");

    // 4. Create the profile.
    await page.locator('[data-test="generate"]').click();
    await expect(page.locator('[data-test="md-input"] textarea:not(.v-textarea__sizer)')).toHaveValue(/## Summary/);
    await page.locator('[data-test="md-mode-preview"]').click();
    await expect(page.locator('[data-test="md-preview"]')).toContainText("Jane Doe is a Python developer");

    // 5. Delete the user profile in the danger zone: the page is empty again.
    await page.goto("/settings");
    await page.locator('[data-test="danger-delete-profile"]').click();
    await page.locator('[data-test="ttc-input"] input').fill("DELETE");
    await page.locator('[data-test="ttc-ok"]').click();
    // Wait for the request to finish (dialog closed, success snackbar) before navigating away.
    await expect(page.locator('[data-test="ttc-input"]')).toBeHidden();
    await expect(page.locator(".v-snackbar")).toContainText("User profile deleted");
    await page.goto("/me");
    await expect(page.locator('[data-test="doc-empty"]')).toBeVisible();
    await expect(page.locator('[data-test="md-input"] textarea:not(.v-textarea__sizer)')).toHaveValue("");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
