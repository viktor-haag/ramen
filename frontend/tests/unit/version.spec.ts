import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout, VSwitch } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import type { AppSettings, VersionInfo } from "@/api/types";
import AboutCard from "@/components/AboutCard.vue";
import UpdateChip from "@/components/UpdateChip.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useLlmStore } from "@/stores/llm";
import { DISMISSED_KEY, REFRESH_MS, useVersionStore } from "@/stores/version";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);

function info(over: Partial<VersionInfo> = {}): VersionInfo {
  return {
    current: "0.1.0", latest: "0.2.0", update_available: true, release_url: "https://github.com/viktor-haag/ramen/releases/tag/v0.2.0",
    published_at: "2026-10-20T10:00:00Z", checked_at: "2026-10-25T10:00:00Z", error: null, enabled: true, disabled_by_env: false, ...over,
  };
}
const appSettings: AppSettings = {
  fit_auto: false, fit_concurrency: 2, fit_language: "en", daily_limit_kind: "none", daily_limit_value: null, update_check: true,
};

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  get.mockReset();
  post.mockReset();
  put.mockReset();
  get.mockResolvedValue(info());
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("version store", () => {
  it("shows the chip for an available update and hides it after dismiss", async () => {
    setActivePinia(createPinia());
    const s = useVersionStore();
    expect(s.showChip).toBe(false);
    await s.load();
    expect(get).toHaveBeenCalledWith("/version");
    expect(s.showChip).toBe(true);
    s.dismiss("0.2.0");
    expect(s.showChip).toBe(false);
    expect(localStorage.getItem(DISMISSED_KEY)).toBe("0.2.0");
  });

  it("a dismissed version stays hidden across reloads but a newer one comes back", async () => {
    localStorage.setItem(DISMISSED_KEY, "0.2.0");
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.load();
    expect(s.showChip).toBe(false);
    get.mockResolvedValue(info({ latest: "0.3.0" }));
    await s.load();
    expect(s.showChip).toBe(true);
  });

  it("no chip without an update", async () => {
    get.mockResolvedValue(info({ update_available: false, latest: "0.1.0" }));
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.load();
    expect(s.showChip).toBe(false);
  });

  it("works in memory when localStorage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.load();
    expect(s.showChip).toBe(true);
    expect(() => s.dismiss("0.2.0")).not.toThrow();
    expect(s.showChip).toBe(false);
  });

  it("load failure is silent and keeps the last result", async () => {
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.load();
    get.mockRejectedValue(new Error("offline"));
    await expect(s.load()).resolves.toBeUndefined();
    expect(s.info?.latest).toBe("0.2.0");
  });

  it("checkNow posts and stores the answer", async () => {
    post.mockResolvedValue(info({ latest: "0.4.0" }));
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.checkNow();
    expect(post).toHaveBeenCalledWith("/version/check");
    expect(s.info?.latest).toBe("0.4.0");
  });

  it("startAutoRefresh reloads on visibilitychange only after REFRESH_MS", async () => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    const s = useVersionStore();
    await s.load();
    s.startAutoRefresh();
    s.startAutoRefresh(); // idempotent
    get.mockClear();
    const fire = () => document.dispatchEvent(new Event("visibilitychange"));
    vi.setSystemTime(Date.now() + REFRESH_MS - 1000);
    fire();
    expect(get).not.toHaveBeenCalled();
    vi.setSystemTime(Date.now() + 1000);
    fire();
    expect(get).toHaveBeenCalledTimes(1);
    fire(); // just loaded
    expect(get).toHaveBeenCalledTimes(1);
  });
});

function mountChip() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(UpdateChip)) });
  return { w: mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body }), store: useVersionStore() };
}

describe("UpdateChip", () => {
  it("links to the release in a new tab and can be dismissed", async () => {
    const { w, store } = mountChip();
    await store.load();
    await flushPromises();
    const chip = w.get('[data-test="update-chip"]');
    expect(chip.text()).toBe("Update 0.2.0");
    expect(chip.attributes("href")).toBe(info().release_url);
    expect(chip.attributes("target")).toBe("_blank");
    expect(chip.attributes("rel")).toContain("noopener");
    const icon = w.get('[data-test="update-chip-icon"]');
    expect(icon.attributes("aria-label")).toBe("Update 0.2.0");
    expect(icon.classes()).toContain("d-sm-none");
    await w.get('[data-test="update-chip-dismiss"]').trigger("click");
    expect(w.find('[data-test="update-chip"]').exists()).toBe(false);
    expect(localStorage.getItem(DISMISSED_KEY)).toBe("0.2.0");
    w.unmount();
  });

  it("is absent without an update", async () => {
    get.mockResolvedValue(info({ update_available: false }));
    const { w, store } = mountChip();
    await store.load();
    await flushPromises();
    expect(w.find('[data-test="update-chip"]').exists()).toBe(false);
    expect(w.find('[data-test="update-chip-dismiss"]').exists()).toBe(false);
    w.unmount();
  });
});

async function mountCard(v: VersionInfo = info({ update_available: false, latest: "0.1.0" })) {
  const pinia = createPinia();
  setActivePinia(pinia);
  get.mockResolvedValue(v);
  useLlmStore().settings = { ...appSettings };
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(AboutCard)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}

describe("AboutCard", () => {
  it("shows versions, release link and up-to-date state", async () => {
    const w = await mountCard();
    expect(w.text()).toContain("About RAMEN");
    expect(w.get('[data-test="about-installed"]').text()).toContain("0.1.0");
    expect(w.get('[data-test="about-latest"]').text()).toContain("0.1.0");
    expect(w.get('[data-test="about-up-to-date"]').text()).toBe("Up to date");
    expect(w.get('[data-test="about-last-checked"]').text()).toMatch(/^Last checked /);
    w.unmount();
  });

  it("links the latest release when an update exists", async () => {
    const w = await mountCard(info());
    const link = w.get('[data-test="about-latest"] a');
    expect(link.attributes("href")).toBe(info().release_url);
    expect(link.attributes("rel")).toContain("noopener");
    expect(w.find('[data-test="about-up-to-date"]').exists()).toBe(false);
    w.unmount();
  });

  it("says so when never checked", async () => {
    const w = await mountCard(info({ latest: null, update_available: false, checked_at: null }));
    expect(w.get('[data-test="about-last-checked"]').text()).toBe("Not checked yet");
    w.unmount();
  });

  it("translates error codes", async () => {
    let w = await mountCard(info({ error: "rate_limited", update_available: false }));
    expect(w.get('[data-test="about-error"]').text()).toBe("GitHub's request limit was reached; trying again later.");
    w.unmount();
    w = await mountCard(info({ error: "http_500", update_available: false }));
    expect(w.get('[data-test="about-error"]').text()).toBe("GitHub answered with an error (500).");
    w.unmount();
    w = await mountCard(info({ error: "network", update_available: false }));
    expect(w.get('[data-test="about-error"]').text()).toBe("GitHub could not be reached.");
    w.unmount();
    w = await mountCard(info({ error: "invalid_response", update_available: false }));
    expect(w.get('[data-test="about-error"]').text()).toBe("GitHub sent an unexpected answer.");
    w.unmount();
  });

  it("shows whether PDF cover letters are available", async () => {
    let w = await mountCard(info({ pdf_available: true }));
    expect(w.get('[data-test="about-pdf"]').text()).toContain("PDF cover letters: available");
    w.unmount();
    w = await mountCard(info({ pdf_available: false }));
    expect(w.get('[data-test="about-pdf"]').text()).toContain("not available (Tectonic missing)");
    w.unmount();
    w = await mountCard(info());
    expect(w.find('[data-test="about-pdf"]').exists()).toBe(false);
    w.unmount();
  });

  it("Check now posts and shows the new result", async () => {
    const w = await mountCard();
    post.mockResolvedValue(info({ latest: "0.5.0" }));
    await w.get('[data-test="about-check"]').trigger("click");
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/version/check");
    expect(w.get('[data-test="about-latest"]').text()).toContain("0.5.0");
    w.unmount();
  });

  it("the switch saves update_check with the full settings body", async () => {
    const w = await mountCard();
    put.mockImplementation(async (_p: string, body: unknown) => body as never);
    const input = w.get('[data-test="about-auto"] input');
    await input.setValue(false);
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/settings", { ...appSettings, update_check: false });
    expect(useLlmStore().settings?.update_check).toBe(false);
    w.unmount();
  });

  it("a failed save keeps update_check on", async () => {
    const w = await mountCard();
    put.mockRejectedValue(new ApiError(500, null, {}, "boom"));
    await w.get('[data-test="about-auto"] input').setValue(false);
    await flushPromises();
    expect(useLlmStore().settings?.update_check).toBe(true);
    expect(w.findComponent(VSwitch).props("modelValue")).toBe(true);
    w.unmount();
  });

  it("disabled by the server: switch and button disabled, hint shown", async () => {
    const w = await mountCard(info({ enabled: false, disabled_by_env: true, update_available: false }));
    expect(w.get('[data-test="about-auto"] input').attributes("disabled")).toBeDefined();
    expect(w.get('[data-test="about-check"]').attributes("disabled")).toBeDefined();
    expect(w.get('[data-test="about-disabled"]').text()).toContain("JOBTRACKER_UPDATE_CHECK");
    w.unmount();
  });
});
