import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { api } from "@/api/client";
import type { PromptOut } from "@/api/types";
import PromptsCard from "@/components/PromptsCard.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { usePromptsStore } from "@/stores/prompts";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const put = vi.mocked(api.put);
const del = vi.mocked(api.del);

const prompt = (purpose: PromptOut["purpose"], over: Partial<PromptOut> = {}): PromptOut => ({
  purpose, text: `${purpose} text`, default_text: `${purpose} default`, fixed_text: "", customized: false, ...over,
});
let items: PromptOut[];

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  for (const m of [get, put, del]) m.mockReset();
  items = [
    prompt("fit", { fixed_text: "Answer as {{\"score\": 1}}.\n{language_line}" }),
    prompt("profile", { fixed_text: "Return JSON." }),
    prompt("extraction"),
  ];
  get.mockImplementation(async (path: string) => {
    if (path === "/prompts") return items as never;
    throw new Error(`unexpected GET ${path}`);
  });
  document.body.innerHTML = "";
});

const q = <T extends Element = HTMLElement>(sel: string) => document.body.querySelector(sel) as T | null;
async function click(sel: string) {
  q(sel)!.click();
  await flushPromises();
}
async function type(sel: string, value: string) {
  const el = q<HTMLTextAreaElement>(sel)!;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  await flushPromises();
}
async function mountCard() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(PromptsCard)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}
const area = () => q<HTMLTextAreaElement>('[data-test="prompt-text"] textarea')!;
const saveBtn = () => q<HTMLButtonElement>('[data-test="prompt-save"]')!;
const resetBtn = () => q<HTMLButtonElement>('[data-test="prompt-reset"]')!;

describe("PromptsCard", () => {
  it("renders three tabs and starts on fit", async () => {
    await mountCard();
    expect(q('[data-test="prompts-card"]')).not.toBeNull();
    for (const p of ["fit", "profile", "extraction"]) expect(q(`[data-test="prompt-tab-${p}"]`)).not.toBeNull();
    expect(area().value).toBe("fit text");
    expect(saveBtn().disabled).toBe(true);
  });

  it("editing enables save and PUTs the text", async () => {
    await mountCard();
    put.mockResolvedValue(prompt("fit", { text: "new", customized: true }) as never);
    await type('[data-test="prompt-text"] textarea', "new");
    expect(saveBtn().disabled).toBe(false);
    await click('[data-test="prompt-save"]');
    expect(put).toHaveBeenCalledWith("/prompts/fit", { text: "new" });
    expect(saveBtn().disabled).toBe(true);
    expect(q('[data-test="prompt-customized"]')).not.toBeNull();
  });

  it("limits the text to 20000 characters: counter, message, save disabled", async () => {
    await mountCard();
    expect(q('[data-test="prompt-text"]')!.textContent).toContain("/ 20000");
    await type('[data-test="prompt-text"] textarea', "x".repeat(20_001));
    expect(q('[data-test="prompt-text"]')!.textContent).toContain("at most 20,000 characters");
    expect(saveBtn().disabled).toBe(true);
    await type('[data-test="prompt-text"] textarea', "x".repeat(20_000));
    expect(q('[data-test="prompt-text"]')!.textContent).not.toContain("at most 20,000 characters");
    expect(saveBtn().disabled).toBe(false);
  });

  it("keeps drafts across tab switches", async () => {
    await mountCard();
    await type('[data-test="prompt-text"] textarea', "draft fit");
    await click('[data-test="prompt-tab-profile"]');
    expect(area().value).toBe("profile text");
    await click('[data-test="prompt-tab-fit"]');
    expect(area().value).toBe("draft fit");
  });

  it("reset asks for confirmation, then DELETEs", async () => {
    items[0] = prompt("fit", { text: "mine", customized: true });
    await mountCard();
    expect(resetBtn().disabled).toBe(false);
    del.mockResolvedValue(prompt("fit") as never);
    await click('[data-test="prompt-reset"]');
    expect(del).not.toHaveBeenCalled();
    await click('[data-test="confirm-ok"]');
    expect(del).toHaveBeenCalledWith("/prompts/fit");
    expect(area().value).toBe("fit text");
    expect(q('[data-test="prompt-customized"]')).toBeNull();
  });

  it("reset is disabled when not customized", async () => {
    await mountCard();
    expect(resetBtn().disabled).toBe(true);
  });

  it("shows the fixed block with readable placeholders, hidden for extraction", async () => {
    await mountCard();
    const fixed = q('[data-test="prompt-fixed"]')!;
    expect(fixed.textContent).toContain('{"score": 1}');
    expect(fixed.textContent).not.toContain("{language_line}");
    expect(fixed.textContent).toContain("(language instruction)");
    await click('[data-test="prompt-tab-extraction"]');
    expect(q('[data-test="prompt-fixed"]')).toBeNull();
  });

  it("shows the customized chip only when customized", async () => {
    items[1] = prompt("profile", { customized: true });
    await mountCard();
    expect(q('[data-test="prompt-customized"]')).toBeNull();
    await click('[data-test="prompt-tab-profile"]');
    expect(q('[data-test="prompt-customized"]')).not.toBeNull();
  });

  it("store save/reset replace the item", async () => {
    await mountCard();
    const s = usePromptsStore();
    put.mockResolvedValue(prompt("fit", { text: "x", customized: true }) as never);
    expect(await s.save("fit", "x")).toBe(true);
    expect(s.items.find((i) => i.purpose === "fit")?.text).toBe("x");
  });
});
