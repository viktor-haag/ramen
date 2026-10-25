import { expect, test } from "./fixtures";

// Phone width: no page may scroll sideways (scrollable areas like the board are fine).
test.use({ viewport: { width: 360, height: 780 } });

test("phone width: no page overflows horizontally", async ({ page, request, baseURL }) => {
  const posting = await request.post(`${baseURL}/api/postings`, { data: { title: "Senior Python Developer (m/w/d)", company: "Brightwave GmbH" } });
  expect(posting.ok()).toBeTruthy();
  const profile = await request.post(`${baseURL}/api/profiles`, {
    data: { name: "Python München", keywords: ["python", "data"], location: "München", radius_km: 50, plugins: ["fake"], schedule_hours: 6 },
  });
  expect(profile.ok()).toBeTruthy();
  const { id: profileId } = await profile.json();
  expect((await request.post(`${baseURL}/api/profiles/${profileId}/run`)).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${baseURL}/api/runs/active`)).json()).length).toBe(0);
  const [application] = await (await request.get(`${baseURL}/api/applications`)).json();

  for (const path of ["/", "/feed", "/applications", `/applications/${application.id}`, "/profiles", "/me", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width, `${path} is ${width}px wide`).toBeLessThanOrEqual(360);
  }
});
