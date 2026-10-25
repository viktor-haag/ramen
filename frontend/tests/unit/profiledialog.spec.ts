import { mount } from "@vue/test-utils";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import type { PluginOut, ProfileOut } from "@/api/types";
import ProfileDialog from "@/components/ProfileDialog.vue";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

const plugin = (name: string, over: Partial<PluginOut> = {}): PluginOut => ({
  name, display_name: name, capabilities: ["search"], url_patterns: [], enabled: true, settings: {}, settings_schema: null, error: null, ...over,
});

function setup(props: Record<string, unknown>) {
  const Host = defineComponent({
    render: () => h(VLayout, null, () => h(ProfileDialog, { modelValue: true, profile: null, plugins: [], ...props })),
  });
  return mount(Host, { global: { plugins: [vuetify, i18n] }, attachTo: document.body });
}

beforeAll(() => {
  // jsdom has no visualViewport (used by Vuetify's overlay positioning)
  vi.stubGlobal("visualViewport", { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, addEventListener() {}, removeEventListener() {} });
});

describe("ProfileDialog", () => {
  it("shows unloadable plugins (empty capabilities) greyed out with a hint", () => {
    const w = setup({ plugins: [plugin("a"), plugin("broken", { capabilities: [], error: "boom" }), plugin("off", { enabled: false })] });
    const body = document.body;
    const broken = body.querySelector("[data-test=pf-plugin-broken] input") as HTMLInputElement;
    expect(broken.disabled).toBe(true);
    expect(body.querySelector("[data-test=pf-plugin-broken]")!.textContent).toContain("not loadable");
    expect(body.querySelector("[data-test=pf-plugin-off]")!.textContent).toContain("disabled in settings");
    expect((body.querySelector("[data-test=pf-plugin-a] input") as HTMLInputElement).checked).toBe(true);
    w.unmount();
  });

  it("save is disabled when the plugin list was not loaded", () => {
    const w = setup({ pluginsLoaded: false });
    expect((document.body.querySelector("[data-test=pf-save]") as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.querySelector("[data-test=pf-plugins-failed]")).not.toBeNull();
    w.unmount();
  });

  const saveBtn = () => document.body.querySelector("[data-test=pf-save]") as HTMLButtonElement;
  const chips = () => Array.from(document.body.querySelectorAll("[data-test=pf-keywords] .v-chip")).map((c) => c.textContent!.trim());
  const input = () => document.body.querySelector("[data-test=pf-keywords] input") as HTMLInputElement;
  const type = async (text: string) => {
    input().focus();
    input().value = text;
    input().dispatchEvent(new Event("input", { bubbles: true }));
    await nextTick();
  };
  const press = async (key: string) => {
    input().dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    await nextTick();
    await nextTick();
  };
  const profile = (keywords: string[]): ProfileOut => ({
    id: 1, name: "Dev", keywords, locations: [], radius_km: null, employment_type: null, remote: null, enabled: true, schedule_hours: null,
    plugins: [], last_run_at: null,
  });

  it("comma creates a chip", async () => {
    const w = setup({ plugins: [plugin("a")] });
    await type("Python,");
    expect(chips()).toEqual(["Python"]);
    w.unmount();
  });

  it("enter creates a chip", async () => {
    const w = setup({ plugins: [plugin("a")] });
    await type("Go");
    await press("Enter");
    expect(chips()).toEqual(["Go"]);
    w.unmount();
  });

  it("pasted text with commas creates several chips", async () => {
    const w = setup({ plugins: [plugin("a")] });
    await type("a, b");
    await press("Enter");
    expect(chips()).toEqual(["a", "b"]);
    w.unmount();
  });

  const cityInput = () => document.body.querySelector("[data-test=pf-locations] input") as HTMLInputElement;
  const cityChips = () => Array.from(document.body.querySelectorAll("[data-test=pf-locations] .v-chip")).map((c) => c.textContent!.trim());
  const typeCity = async (text: string) => {
    cityInput().focus();
    cityInput().value = text;
    cityInput().dispatchEvent(new Event("input", { bubbles: true }));
    await nextTick();
  };
  const pressCity = async (key: string) => {
    cityInput().dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    await nextTick();
    await nextTick();
  };

  it("adds two cities via Enter and comma and saves them; radius is enabled only with a city", async () => {
    const w = setup({ plugins: [plugin("a")], profile: profile(["python"]) });
    await new Promise((r) => setTimeout(r));
    const radius = () => document.body.querySelector("[data-test=pf-radius] input") as HTMLInputElement;
    expect(radius().disabled).toBe(true);
    await typeCity("Berlin");
    await pressCity("Enter");
    await typeCity("Hamburg,");
    expect(cityChips()).toEqual(["Berlin", "Hamburg"]);
    expect(radius().disabled).toBe(false);
    saveBtn().click();
    await nextTick();
    const emitted = w.findComponent(ProfileDialog).emitted("save")!;
    expect(emitted[0][0]).toMatchObject({ locations: ["Berlin", "Hamburg"] });
    w.unmount();
  });

  it("shows existing cities and flags more than 20 or an overlong city", async () => {
    const w = setup({ plugins: [plugin("a")], profile: { ...profile(["x"]), locations: ["Bonn", "Köln"] } });
    await nextTick();
    expect(cityChips()).toEqual(["Bonn", "Köln"]);
    w.unmount();
    const w2 = setup({ plugins: [plugin("a")], profile: { ...profile(["x"]), locations: Array.from({ length: 21 }, (_, i) => `c${i}`) } });
    await nextTick();
    expect(document.body.querySelector("[data-test=pf-locations-error]")!.textContent).toContain("20");
    expect(saveBtn().disabled).toBe(true);
    w2.unmount();
    const w3 = setup({ plugins: [plugin("a")], profile: { ...profile(["x"]), locations: ["y".repeat(101)] } });
    await nextTick();
    expect(document.body.querySelector("[data-test=pf-locations-error]")!.textContent).toContain("100");
    expect(saveBtn().disabled).toBe(true);
    w3.unmount();
  });

  it("adds uncommitted keyword and city text when saving", async () => {
    const w = setup({ plugins: [plugin("a")], profile: profile(["python"]) });
    await new Promise((r) => setTimeout(r));
    await type("Go");
    await typeCity("Berlin");
    saveBtn().click();
    await nextTick();
    const emitted = w.findComponent(ProfileDialog).emitted("save")!;
    expect(emitted[0][0]).toMatchObject({ keywords: ["python", "Go"], locations: ["Berlin"] });
    w.unmount();
  });

  it("save is disabled without chips and enabled with one", async () => {
    const w = setup({ plugins: [plugin("a")], profile: null });
    await new Promise((r) => setTimeout(r));
    const name = document.body.querySelector("[data-test=pf-name] input") as HTMLInputElement;
    name.value = "Dev";
    name.dispatchEvent(new Event("input", { bubbles: true }));
    await nextTick();
    expect(saveBtn().disabled).toBe(true);
    await type("Python,");
    expect(saveBtn().disabled).toBe(false);
    w.unmount();
  });

  it("profile with empty keywords opens without chips and disables save", async () => {
    const w = setup({ plugins: [plugin("a")], profile: profile([]) });
    await nextTick();
    expect(chips()).toEqual([]);
    expect(saveBtn().disabled).toBe(true);
    w.unmount();
  });

  it("shows an error hint for more than 20 chips or an overlong chip and disables save", async () => {
    const many = Array.from({ length: 21 }, (_, i) => `k${i}`);
    const w = setup({ plugins: [plugin("a")], profile: profile(many) });
    await nextTick();
    expect(document.body.querySelector("[data-test=pf-keywords-error]")!.textContent).toContain("20");
    expect(saveBtn().disabled).toBe(true);
    w.unmount();
    const w2 = setup({ plugins: [plugin("a")], profile: profile(["x".repeat(101)]) });
    await nextTick();
    expect(document.body.querySelector("[data-test=pf-keywords-error]")!.textContent).toContain("100");
    expect(saveBtn().disabled).toBe(true);
    w2.unmount();
  });
});
