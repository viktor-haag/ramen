import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout, VSelect } from "vuetify/components";
import SchemaForm from "@/components/SchemaForm.vue";
import { ApiError, api } from "@/api/client";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import SettingsView from "@/views/SettingsView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const put = vi.mocked(api.put);

const plugins = [
  {
    name: "arbeitsagentur", display_name: "Arbeitsagentur", capabilities: ["search"], url_patterns: [], enabled: true,
    settings: { max_results: 200 },
    settings_schema: { type: "object", properties: { max_results: { type: "integer", title: "Max results", minimum: 1 } } },
    error: null,
  },
  { name: "bad", display_name: "Bad", capabilities: ["search"], url_patterns: [], enabled: false, settings: {}, settings_schema: null, error: "ImportError: x" },
];

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  get.mockReset();
  put.mockReset();
  get.mockImplementation(async (path: string) => {
    if (path === "/plugins") return plugins as never;
    if (path === "/llm/configs") return [] as never;
    if (path === "/llm/purposes") return { profile: null, fit: null, extraction: null } as never;
    if (path === "/settings") return { fit_auto: false, fit_concurrency: 2, daily_limit_kind: "none", daily_limit_value: null } as never;
    if (path === "/llm/usage") {
      const zero = { input_tokens: 0, output_tokens: 0, eur: null };
      return { today: zero, month: zero, limit: { kind: "none", value: null }, limit_exceeded: false } as never;
    }
    throw new Error(`unexpected GET ${path}`);
  });
});

async function mountView() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(SettingsView)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}

describe("SettingsView", () => {
  it("language selection calls setLocale and changes visible texts", async () => {
    const w = await mountView();
    expect(w.find("h1").text()).toBe("Settings");
    w.findComponent(VSelect).vm.$emit("update:modelValue", "de");
    await flushPromises();
    expect(localStorage.getItem("jobtracker.locale")).toBe("de");
    expect(w.find("h1").text()).toBe("Einstellungen");
    w.unmount();
  });

  it("renders the AI settings section above the danger zone", async () => {
    const w = await mountView();
    const ai = w.find("[data-test=llm-configs]").element;
    const danger = w.find("[data-test=danger-zone]").element;
    expect(ai.compareDocumentPosition(danger) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    w.unmount();
  });

  const panel = (w: Awaited<ReturnType<typeof mountView>>, name: string) => w.find(`[data-test=plugin-${name}]`);
  const expand = async (w: Awaited<ReturnType<typeof mountView>>, name: string) => {
    await panel(w, name).find(".v-expansion-panel-title").trigger("click");
    await flushPromises();
  };

  it("renders plugins as collapsed panels; expanding shows the settings", async () => {
    const w = await mountView();
    expect(w.findAll(".v-expansion-panel--active")).toHaveLength(0);
    expect(w.findComponent(SchemaForm).exists()).toBe(false);
    expect(panel(w, "arbeitsagentur").text()).toContain("Arbeitsagentur");
    await expand(w, "arbeitsagentur");
    expect(panel(w, "arbeitsagentur").classes()).toContain("v-expansion-panel--active");
    expect(w.findComponent(SchemaForm).exists()).toBe(true);
    w.unmount();
  });

  it("toggling the header switch saves immediately with stored settings and does not expand", async () => {
    const w = await mountView();
    put.mockResolvedValue({ ...plugins[0], enabled: false } as never);
    const input = panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input");
    await input.setValue(false);
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/plugins/arbeitsagentur", { enabled: false, settings: { max_results: 200 } });
    expect(panel(w, "arbeitsagentur").classes()).not.toContain("v-expansion-panel--active");
    expect((panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input").element as HTMLInputElement).checked).toBe(false);
    w.unmount();
  });

  it("clicking the header switch does not toggle the panel", async () => {
    const w = await mountView();
    put.mockResolvedValue({ ...plugins[0], enabled: false } as never);
    await panel(w, "arbeitsagentur").find("[data-test=plugin-enabled]").trigger("click");
    await panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input").trigger("click");
    await flushPromises();
    expect(panel(w, "arbeitsagentur").classes()).not.toContain("v-expansion-panel--active");
    w.unmount();
  });

  it("Space/Enter on the header switch input does not expand the panel", async () => {
    const w = await mountView();
    put.mockResolvedValue({ ...plugins[0], enabled: false } as never);
    const input = panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input");
    for (const key of [" ", "Enter"]) {
      await input.trigger("keydown", { key });
      await input.trigger("keyup", { key });
    }
    await flushPromises();
    expect(panel(w, "arbeitsagentur").classes()).not.toContain("v-expansion-panel--active");
    w.unmount();
  });

  it("disables the header switch while the body save is running and the save button while toggling", async () => {
    const w = await mountView();
    await expand(w, "arbeitsagentur");
    const disabled = (sel: string) => (panel(w, "arbeitsagentur").find(sel).element as HTMLInputElement).disabled;
    let release!: (v: unknown) => void;
    put.mockImplementationOnce(() => new Promise((r) => (release = r)) as never);
    await panel(w, "arbeitsagentur").find("[data-test=plugin-save]").trigger("click");
    await flushPromises();
    expect(disabled("[data-test=plugin-enabled] input")).toBe(true);
    release(plugins[0]);
    await flushPromises();
    expect(disabled("[data-test=plugin-enabled] input")).toBe(false);

    put.mockImplementationOnce(() => new Promise((r) => (release = r)) as never);
    await panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input").setValue(false);
    await flushPromises();
    expect(disabled("[data-test=plugin-save]")).toBe(true);
    release({ ...plugins[0], enabled: false });
    await flushPromises();
    expect(disabled("[data-test=plugin-save]")).toBe(false);
    w.unmount();
  });

  it("a failed toggle reverts the switch", async () => {
    const w = await mountView();
    put.mockRejectedValue(new ApiError(500, "internal", {}, "boom"));
    const input = panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input");
    await input.setValue(false);
    await flushPromises();
    expect(put).toHaveBeenCalledTimes(1);
    expect((panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input").element as HTMLInputElement).checked).toBe(true);
    w.unmount();
  });

  it("toggling keeps unsaved draft settings and saves only stored settings", async () => {
    const w = await mountView();
    await expand(w, "arbeitsagentur");
    w.findComponent(SchemaForm).vm.$emit("update:modelValue", { max_results: 5 });
    await flushPromises();
    put.mockResolvedValue({ ...plugins[0], enabled: false } as never);
    await panel(w, "arbeitsagentur").find("[data-test=plugin-enabled] input").setValue(false);
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/plugins/arbeitsagentur", { enabled: false, settings: { max_results: 200 } });
    expect(w.findComponent(SchemaForm).props("modelValue")).toEqual({ max_results: 5 });
    w.unmount();
  });

  it("shows unloadable plugins with an error chip, no switch, and the error in the body", async () => {
    const w = await mountView();
    expect(panel(w, "bad").find("[data-test=plugin-error-chip]").exists()).toBe(true);
    expect(panel(w, "bad").find("[data-test=plugin-enabled]").exists()).toBe(false);
    await expand(w, "bad");
    expect(panel(w, "bad").find("[data-test=plugin-error]").text()).toContain("ImportError: x");
    w.unmount();
  });

  it("shows field errors from 422 on save", async () => {
    const w = await mountView();
    await expand(w, "arbeitsagentur");
    put.mockRejectedValue(
      new ApiError(422, "validation_error", { errors: [{ loc: ["body", "settings", "max_results"], msg: "too small", type: "x" }] }, "invalid"),
    );
    await w.find("[data-test=plugin-arbeitsagentur] [data-test=plugin-save]").trigger("click");
    await flushPromises();
    expect(w.find("[data-test=plugin-arbeitsagentur]").text()).toContain("too small");
    expect(put).toHaveBeenCalledWith("/plugins/arbeitsagentur", { enabled: true, settings: { max_results: 200 } });
    w.unmount();
  });
});
