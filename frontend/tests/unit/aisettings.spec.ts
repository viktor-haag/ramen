import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VCombobox, VLayout, VSelect } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import type { AppSettings, LlmConfigOut, LlmPurposes, LlmUsageOut } from "@/api/types";
import AiSettings from "@/components/AiSettings.vue";
import LlmConfigDialog from "@/components/LlmConfigDialog.vue";
import { i18n, setLocale } from "@/i18n";
import { useLlmStore } from "@/stores/llm";
import { useNotifyStore } from "@/stores/notify";
import { vuetify } from "@/plugins/vuetify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);
const del = vi.mocked(api.del);

const cfg = (over: Partial<LlmConfigOut> = {}): LlmConfigOut => ({
  id: 1, name: "Main", provider: "anthropic", base_url: null, api_key: "…1234", has_api_key: true, model: "claude-x",
  thinking: "off", supports_images: true, extra_body: {}, extra_headers: {}, price_in: null, price_out: null, is_default: true, ...over,
});
const usage = (over: Partial<LlmUsageOut> = {}): LlmUsageOut => ({
  today: { input_tokens: 1200, output_tokens: 300, eur: 0.5 },
  month: { input_tokens: 40000, output_tokens: 9000, eur: 2.25 },
  limit: { kind: "none", value: null }, limit_exceeded: false, ...over,
});

let configs: LlmConfigOut[];
let purposes: LlmPurposes;
let settings: AppSettings;
let usageData: LlmUsageOut;

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  for (const m of [get, post, put, del]) m.mockReset();
  configs = [cfg(), cfg({ id: 2, name: "Local", provider: "openai_compatible", base_url: "http://x/v1", api_key: null, has_api_key: false, supports_images: false, is_default: false })];
  purposes = { profile: null, fit: null, extraction: null };
  settings = { fit_auto: false, fit_concurrency: 2, fit_language: "en", daily_limit_kind: "none", daily_limit_value: null };
  usageData = usage();
  get.mockImplementation(async (path: string) => {
    if (path === "/llm/configs") return configs as never;
    if (path === "/llm/purposes") return purposes as never;
    if (path === "/settings") return settings as never;
    if (path === "/llm/usage") return usageData as never;
    throw new Error(`unexpected GET ${path}`);
  });
  document.body.innerHTML = "";
});

const body = () => document.body;
const q = <T extends Element = HTMLElement>(sel: string) => body().querySelector(sel) as T | null;
async function type(sel: string, value: string) {
  const el = q<HTMLInputElement | HTMLTextAreaElement>(sel)!;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  await flushPromises();
}
async function click(sel: string) {
  q(sel)!.click();
  await flushPromises();
}

function host(component: object, props: Record<string, unknown> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(component, props)) });
  return mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
}
const openDialog = async (config: LlmConfigOut | null) => {
  const w = host(LlmConfigDialog, { modelValue: true, config });
  await flushPromises();
  return w;
};
const selectByTest = (w: ReturnType<typeof host>, id: string) =>
  w.findAllComponents(VSelect).find((c) => c.element.getAttribute("data-test") === id)!;

describe("LlmConfigDialog", () => {
  it("shows base_url and thinking depending on the provider", async () => {
    const w = await openDialog(null);
    expect(q("[data-test=llm-thinking]")).not.toBeNull();
    expect(q("[data-test=llm-base-url]")).toBeNull();
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai_compatible");
    await flushPromises();
    expect(q("[data-test=llm-thinking]")).toBeNull();
    expect(q("[data-test=llm-base-url]")).not.toBeNull();
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai");
    await flushPromises();
    expect(q("[data-test=llm-thinking]")).not.toBeNull();
    expect(q("[data-test=llm-base-url]")).toBeNull();
    w.unmount();
  });

  it("applies the supports_images provider default for new configs only", async () => {
    const w = await openDialog(null);
    const imgs = () => q<HTMLInputElement>("[data-test=llm-images] input")!.checked;
    expect(imgs()).toBe(true);
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai_compatible");
    await flushPromises();
    expect(imgs()).toBe(false);
    w.unmount();
    const w2 = await openDialog(cfg({ supports_images: false }));
    selectByTest(w2, "llm-provider").vm.$emit("update:modelValue", "openai");
    await flushPromises();
    expect(q<HTMLInputElement>("[data-test=llm-images] input")!.checked).toBe(false);
    w2.unmount();
  });

  it("invalid JSON in advanced fields gives a field error and disables save", async () => {
    const w = await openDialog(cfg());
    await click("[data-test=llm-advanced] .v-expansion-panel-title");
    expect(q<HTMLButtonElement>("[data-test=llm-save]")!.disabled).toBe(false);
    await type("[data-test=llm-extra-body] textarea", "{nope");
    expect(q("[data-test=llm-extra-body]")!.textContent).toContain("valid JSON object");
    expect(q<HTMLButtonElement>("[data-test=llm-save]")!.disabled).toBe(true);
    await type("[data-test=llm-extra-body] textarea", "[1]");
    expect(q<HTMLButtonElement>("[data-test=llm-save]")!.disabled).toBe(true);
    await type("[data-test=llm-extra-body] textarea", '{"a": 1}');
    await type("[data-test=llm-extra-headers] textarea", '{"X-A": 5}');
    expect(q("[data-test=llm-extra-headers]")!.textContent).toContain("strings");
    expect(q<HTMLButtonElement>("[data-test=llm-save]")!.disabled).toBe(true);
    await type("[data-test=llm-extra-headers] textarea", '{"X-A": "5"}');
    expect(q<HTMLButtonElement>("[data-test=llm-save]")!.disabled).toBe(false);
    w.unmount();
  });

  it("shows the masked key as placeholder; empty keeps the key (no api_key in payload)", async () => {
    put.mockResolvedValue(cfg() as never);
    const w = await openDialog(cfg());
    const key = q<HTMLInputElement>("[data-test=llm-api-key] input")!;
    expect(key.type).toBe("password");
    expect(key.placeholder).toBe("…1234");
    expect(key.value).toBe("");
    await click("[data-test=llm-save]");
    expect(put).toHaveBeenCalledTimes(1);
    const [path, payload] = put.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/llm/configs/1");
    expect("api_key" in payload).toBe(false);
    expect(payload).toMatchObject({ name: "Main", provider: "anthropic", base_url: null, model: "claude-x", thinking: "off", supports_images: true });
    w.unmount();
  });

  it("sends a typed key, and \"\" when clear key is checked", async () => {
    put.mockResolvedValue(cfg() as never);
    const w = await openDialog(cfg());
    await type("[data-test=llm-api-key] input", "sk-test-9999");
    await click("[data-test=llm-save]");
    expect(put.mock.calls[0][1]).toMatchObject({ api_key: "sk-test-9999" });
    w.unmount();

    put.mockClear();
    const w2 = await openDialog(cfg({ provider: "openai_compatible", base_url: "http://x/v1" }));
    await click("[data-test=llm-clear-key] input");
    expect(q<HTMLInputElement>("[data-test=llm-api-key] input")!.disabled).toBe(true);
    await click("[data-test=llm-save]");
    expect(put.mock.calls[0][1]).toMatchObject({ api_key: "" });
    w2.unmount();
  });

  it("offers the clear-key checkbox only for openai_compatible configs", async () => {
    const w = await openDialog(cfg());
    expect(q("[data-test=llm-clear-key]")).toBeNull();
    expect(q<HTMLInputElement>("[data-test=llm-api-key] input")!.getAttribute("autocomplete")).toBe("new-password");
    w.unmount();
    const w2 = await openDialog(cfg({ provider: "openai_compatible", base_url: "http://x/v1" }));
    expect(q("[data-test=llm-clear-key]")).not.toBeNull();
    w2.unmount();
  });

  it("keeps extra_body, extra_headers and prices on an unchanged edit", async () => {
    put.mockResolvedValue(cfg() as never);
    const w = await openDialog(cfg({ extra_body: { top_k: 5 }, extra_headers: { "X-A": "b" }, price_in: 1.5, price_out: 7 }));
    await click("[data-test=llm-save]");
    expect(put.mock.calls[0][1]).toMatchObject({ extra_body: { top_k: 5 }, extra_headers: { "X-A": "b" }, price_in: 1.5, price_out: 7 });
    w.unmount();
  });

  it("resets thinking to off when switching to openai_compatible", async () => {
    const w = await openDialog(cfg({ thinking: "high" }));
    expect(selectByTest(w, "llm-thinking").props("modelValue")).toBe("high");
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai_compatible");
    await flushPromises();
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai");
    await flushPromises();
    expect(selectByTest(w, "llm-thinking").props("modelValue")).toBe("off");
    w.unmount();
  });

  it("opens the advanced panel for server errors inside it", async () => {
    put.mockRejectedValue(new ApiError(422, "validation_error", { errors: [{ loc: ["body", "price_in"], msg: "must be >= 0", type: "x" }] }, "invalid"));
    const w = await openDialog(cfg());
    expect(q("[data-test=llm-advanced].v-expansion-panel--active")).toBeNull();
    await click("[data-test=llm-save]");
    expect(q("[data-test=llm-advanced].v-expansion-panel--active")).not.toBeNull();
    expect(q("[data-test=llm-price-in]")!.textContent).toContain("must be >= 0");
    w.unmount();
  });

  it("also shows the snackbar when a 422 maps to no visible field", async () => {
    put.mockRejectedValue(new ApiError(422, "validation_error", { errors: [{ loc: ["body", "base_url"], msg: "base_url is only allowed", type: "x" }] }, "invalid"));
    const w = await openDialog(cfg());
    await click("[data-test=llm-save]");
    const notify = useNotifyStore();
    expect(notify.visible).toBe(true);
    w.unmount();
  });

  it("creates a new openai_compatible config with base_url, off thinking and parsed advanced fields", async () => {
    post.mockResolvedValue(cfg({ id: 3 }) as never);
    const w = await openDialog(null);
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "openai_compatible");
    await flushPromises();
    await type("[data-test=llm-name] input", "Ollama");
    await type("[data-test=llm-base-url] input", "http://localhost:11434/v1");
    await type("[data-test=llm-model] input", "llama3");
    await click("[data-test=llm-advanced] .v-expansion-panel-title");
    await type("[data-test=llm-extra-body] textarea", '{"top_k": 5}');
    await type("[data-test=llm-price-in] input", "1.5");
    await click("[data-test=llm-save]");
    expect(post).toHaveBeenCalledWith("/llm/configs", {
      name: "Ollama", provider: "openai_compatible", base_url: "http://localhost:11434/v1", model: "llama3", thinking: "off",
      supports_images: false, extra_body: { top_k: 5 }, extra_headers: {}, price_in: 1.5, price_out: null,
    });
    w.unmount();
  });

  it("maps 422 field errors onto the fields", async () => {
    put.mockRejectedValue(
      new ApiError(422, "validation_error", { errors: [{ loc: ["body", "base_url"], msg: "base_url is required", type: "x" }, { loc: ["body", "api_key"], msg: "bad key", type: "x" }] }, "invalid"),
    );
    const w = await openDialog(cfg({ provider: "openai_compatible", base_url: "http://x" }));
    await click("[data-test=llm-save]");
    expect(q("[data-test=llm-base-url]")!.textContent).toContain("base_url is required");
    expect(q("[data-test=llm-api-key]")!.textContent).toContain("bad key");
    w.unmount();
  });

  it("leaves config_id out when the provider changed or the key is being cleared", async () => {
    post.mockResolvedValue(["m"] as never);
    const w = await openDialog(cfg({ provider: "openai_compatible", base_url: "http://x/v1" }));
    selectByTest(w, "llm-provider").vm.$emit("update:modelValue", "anthropic");
    await flushPromises();
    await type("[data-test=llm-api-key] input", "sk-typed-1");
    await click("[data-test=llm-load-models]");
    expect(post).toHaveBeenCalledWith("/llm/models", { provider: "anthropic", base_url: null, api_key: "sk-typed-1" });
    w.unmount();

    post.mockClear();
    const w2 = await openDialog(cfg({ provider: "openai_compatible", base_url: "http://x/v1" }));
    await click("[data-test=llm-clear-key] input");
    await click("[data-test=llm-load-models]");
    expect((post.mock.calls[0][1] as Record<string, unknown>).config_id).toBeUndefined();
    w2.unmount();
  });

  it("loads models into the combobox using config_id and the typed key", async () => {
    post.mockResolvedValue(["m-1", "m-2"] as never);
    const w = await openDialog(cfg());
    await type("[data-test=llm-api-key] input", "sk-test-1");
    await click("[data-test=llm-load-models]");
    expect(post).toHaveBeenCalledWith("/llm/models", { config_id: 1, provider: "anthropic", base_url: null, api_key: "sk-test-1" });
    expect(w.findComponent(VCombobox).props("items")).toEqual(["m-1", "m-2"]);
    w.unmount();
  });
});

describe("AiSettings", () => {
  const mountSettings = async () => {
    const w = host(AiSettings);
    await flushPromises();
    return w;
  };

  it("lists configs with provider, model and default star", async () => {
    const w = await mountSettings();
    const row1 = q("[data-test=llm-config-1]")!.textContent!;
    expect(row1).toContain("Main");
    expect(row1).toContain("claude-x");
    expect(q("[data-test=llm-config-1] [data-test=llm-default-icon]")!.classList.contains("mdi-star")).toBe(true);
    expect(q("[data-test=llm-config-2] [data-test=llm-default-icon]")!.classList.contains("mdi-star-outline")).toBe(true);
    post.mockResolvedValue(cfg({ id: 2 }) as never);
    await click("[data-test=llm-config-2] [data-test=llm-default]");
    expect(post).toHaveBeenCalledWith("/llm/configs/2/default");
    w.unmount();
  });

  it("test button shows success and error text", async () => {
    const w = await mountSettings();
    post.mockResolvedValueOnce({ ok: true, model: "claude-x", latency_ms: 321 } as never);
    await click("[data-test=llm-config-1] [data-test=llm-test]");
    expect(post).toHaveBeenCalledWith("/llm/configs/1/test");
    expect(q("[data-test=llm-config-1] [data-test=llm-test-result]")!.textContent).toContain("321 ms");
    post.mockRejectedValueOnce(new ApiError(502, "llm_auth_failed", { reason: "401 invalid x-api-key" }, "auth"));
    await click("[data-test=llm-config-1] [data-test=llm-test]");
    const text = q("[data-test=llm-config-1] [data-test=llm-test-result]")!.textContent!;
    expect(text).toContain("rejected the API key");
    expect(text).toContain("401 invalid x-api-key");
    w.unmount();
  });

  it("reloads usage after a connection test", async () => {
    const w = await mountSettings();
    const usageCalls = () => get.mock.calls.filter((c) => c[0] === "/llm/usage").length;
    expect(usageCalls()).toBe(1);
    post.mockResolvedValueOnce({ ok: true, model: "claude-x", latency_ms: 5 } as never);
    await click("[data-test=llm-config-1] [data-test=llm-test]");
    expect(usageCalls()).toBe(2);
    w.unmount();
  });

  it("keeps the parts that loaded and reports one error when a part fails", async () => {
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (path: string, ...rest: unknown[]) => {
      if (path === "/llm/usage" || path === "/settings") throw new ApiError(500, null, {}, "boom");
      return base(path, ...(rest as []));
    });
    const w = await mountSettings();
    expect(q("[data-test=llm-config-1]")).not.toBeNull();
    expect(useNotifyStore().visible).toBe(true);
    w.unmount();
  });

  it("shows the euro-limit hint only for the eur kind", async () => {
    const w = await mountSettings();
    selectByTest(w, "llm-limit-kind").vm.$emit("update:modelValue", "tokens");
    await flushPromises();
    expect(q("[data-test=llm-limit-value]")!.textContent).not.toContain("without prices");
    selectByTest(w, "llm-limit-kind").vm.$emit("update:modelValue", "eur");
    await flushPromises();
    expect(q("[data-test=llm-limit-value]")!.textContent).toContain("Usage of configurations without prices does not count toward this limit.");
    w.unmount();
  });

  it("deletes a config after confirmation", async () => {
    del.mockResolvedValue(undefined as never);
    const w = await mountSettings();
    await click("[data-test=llm-config-2] [data-test=llm-delete]");
    expect(del).not.toHaveBeenCalled();
    await click("[data-test=confirm-ok]");
    expect(del).toHaveBeenCalledWith("/llm/configs/2");
    w.unmount();
  });

  it("saves purposes with null for Default", async () => {
    put.mockResolvedValue({ profile: 2, fit: null, extraction: null } as never);
    const w = await mountSettings();
    selectByTest(w, "llm-purpose-profile").vm.$emit("update:modelValue", 2);
    await flushPromises();
    await click("[data-test=llm-purposes-save]");
    expect(put).toHaveBeenCalledWith("/llm/purposes", { profile: 2, fit: null, extraction: null });
    w.unmount();
  });

  it("round-trips fit_language: a stored de is sent back on save, and changing it is saved", async () => {
    settings = { ...settings, fit_language: "de" };
    put.mockImplementation(async (_p: string, b: unknown) => b as never);
    const w = await mountSettings();
    expect(q("[data-test=llm-fit-language]")).not.toBeNull();
    expect(body().textContent).toContain("Explanation language for automatic evaluations");
    await click("[data-test=llm-settings-save]");
    expect(put).toHaveBeenLastCalledWith("/settings", expect.objectContaining({ fit_language: "de" }));
    selectByTest(w, "llm-fit-language").vm.$emit("update:modelValue", "en");
    await flushPromises();
    await click("[data-test=llm-settings-save]");
    expect(put).toHaveBeenLastCalledWith("/settings", expect.objectContaining({ fit_language: "en" }));
    w.unmount();
  });

  it("saves fit and limit settings; tokens limit is an integer, none sends null", async () => {
    put.mockImplementation(async (_p: string, b: unknown) => b as never);
    const w = await mountSettings();
    selectByTest(w, "llm-limit-kind").vm.$emit("update:modelValue", "tokens");
    await flushPromises();
    await type("[data-test=llm-limit-value] input", "50000");
    await type("[data-test=llm-concurrency] input", "4");
    await click("[data-test=llm-fit-auto] input");
    await click("[data-test=llm-settings-save]");
    expect(put).toHaveBeenCalledWith("/settings", { fit_auto: true, fit_concurrency: 4, fit_language: "en", daily_limit_kind: "tokens", daily_limit_value: 50000 });
    selectByTest(w, "llm-limit-kind").vm.$emit("update:modelValue", "none");
    await flushPromises();
    expect(q("[data-test=llm-limit-value]")).toBeNull();
    await click("[data-test=llm-settings-save]");
    expect(put).toHaveBeenLastCalledWith("/settings", { fit_auto: true, fit_concurrency: 4, fit_language: "en", daily_limit_kind: "none", daily_limit_value: null });
    w.unmount();
  });

  it("shows a limit field error from a 422", async () => {
    put.mockRejectedValue(new ApiError(422, "validation_error", { errors: [{ loc: ["body", "daily_limit_value"], msg: "must be greater than 0", type: "x" }] }, "invalid"));
    settings = { ...settings, daily_limit_kind: "eur", daily_limit_value: 1 };
    const w = await mountSettings();
    await click("[data-test=llm-settings-save]");
    expect(q("[data-test=llm-limit-value]")!.textContent).toContain("must be greater than 0");
    w.unmount();
  });

  it("renders usage with euro amounts and the exceeded warning", async () => {
    usageData = usage({ limit: { kind: "eur", value: 0.5 }, limit_exceeded: true });
    settings = { ...settings, daily_limit_kind: "eur", daily_limit_value: 0.5 };
    const w = await mountSettings();
    const text = q("[data-test=llm-usage]")!.textContent!;
    expect(text).toContain("1,200");
    expect(text).toContain("300");
    expect(text).toContain("0.50");
    expect(text).toContain("2.25");
    expect(q("[data-test=llm-limit-exceeded]")).not.toBeNull();
    w.unmount();
  });

  it("renders usage without euro amounts when no config has prices", async () => {
    usageData = usage({ today: { input_tokens: 10, output_tokens: 5, eur: null }, month: { input_tokens: 20, output_tokens: 8, eur: null } });
    const w = await mountSettings();
    const text = q("[data-test=llm-usage]")!.textContent!;
    expect(q("[data-test=llm-usage-today]")!.textContent).toContain("10 in / 5 out tokens");
    expect(q("[data-test=llm-usage-month]")!.textContent).toContain("20 in / 8 out tokens");
    expect(text).not.toContain("€");
    expect(text.match(/no prices set/g)).toHaveLength(2);
    expect(q("[data-test=llm-limit-exceeded]")).toBeNull();
    w.unmount();
  });
});

describe("llm store save fallbacks", () => {
  const body: AppSettings = { fit_auto: false, fit_concurrency: 2, fit_language: "en", daily_limit_kind: "tokens", daily_limit_value: 1 };
  const invalid = (field: string) =>
    new ApiError(422, "validation_error", { errors: [{ loc: ["body", field], msg: "bad value", type: "x" }] }, "invalid");

  beforeEach(() => setActivePinia(createPinia()));

  it("saveSettings shows the snackbar when the 422 maps to no visible field", async () => {
    put.mockRejectedValue(invalid("fit_concurrency"));
    const res = await useLlmStore().saveSettings(body, ["daily_limit_value"]);
    expect(res.ok).toBe(false);
    expect(useNotifyStore().visible).toBe(true);
  });

  it("saveSettings leaves the snackbar alone when a visible field shows the error", async () => {
    put.mockRejectedValue(invalid("daily_limit_value"));
    const res = await useLlmStore().saveSettings(body, ["daily_limit_value"]);
    expect(res).toEqual({ ok: false, errors: { daily_limit_value: "bad value" } });
    expect(useNotifyStore().visible).toBe(false);
  });

  it("savePurposes has no inline fields, so every error reaches the snackbar", async () => {
    put.mockRejectedValue(invalid("profile"));
    const res = await useLlmStore().savePurposes({ profile: 1, fit: null, extraction: null });
    expect(res.ok).toBe(false);
    expect(useNotifyStore().visible).toBe(true);
    useNotifyStore().visible = false;
    put.mockRejectedValue(new ApiError(500, null, {}, "boom"));
    await useLlmStore().savePurposes({ profile: 1, fit: null, extraction: null });
    expect(useNotifyStore().message).toBe("boom");
  });
});
