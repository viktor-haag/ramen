import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { api } from "@/api/client";
import type { CoverLetterTemplate } from "@/api/types";
import CoverLetterTemplatesCard from "@/components/CoverLetterTemplatesCard.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const patch = vi.mocked(api.patch);
const del = vi.mocked(api.del);
const upload = vi.mocked(api.upload);

const builtin: CoverLetterTemplate = { id: 1, name: "Standard", builtin: true, created_at: "2026-10-01T10:00:00Z" };
const custom: CoverLetterTemplate = { id: 2, name: "Mine", builtin: false, created_at: "2026-10-02T10:00:00Z" };

beforeEach(() => {
  setLocale("en");
  for (const m of [get, patch, del, upload]) m.mockReset();
  get.mockResolvedValue([builtin, custom] as never);
});

async function mountCard() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(CoverLetterTemplatesCard)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}

describe("CoverLetterTemplatesCard", () => {
  it("lists templates and badges only the built-in one", async () => {
    const w = await mountCard();
    expect(get).toHaveBeenCalledWith("/cover-letter-templates");
    expect(w.get('[data-test="cover-templates-card"]').text()).toContain("Cover letter templates");
    expect(w.get('[data-test="cover-template-1"]').text()).toContain("Standard");
    expect(w.get('[data-test="cover-template-builtin-1"]').text()).toBe("Default");
    expect(w.find('[data-test="cover-template-builtin-2"]').exists()).toBe(false);
    w.unmount();
  });

  it("offers neither rename nor delete for the built-in template", async () => {
    const w = await mountCard();
    expect(w.find('[data-test="cover-template-rename-1"]').exists()).toBe(false);
    expect(w.find('[data-test="cover-template-delete-1"]').exists()).toBe(false);
    expect(w.find('[data-test="cover-template-rename-2"]').exists()).toBe(true);
    expect(w.find('[data-test="cover-template-delete-2"]').exists()).toBe(true);
    w.unmount();
  });

  it("links the download for every template", async () => {
    const w = await mountCard();
    expect(w.get('[data-test="cover-template-download-1"]').attributes("href")).toBe("/api/cover-letter-templates/1/download");
    expect(w.get('[data-test="cover-template-download-2"]').attributes("href")).toBe("/api/cover-letter-templates/2/download");
    w.unmount();
  });

  it("restricts the upload input to .tex and uploads the chosen file", async () => {
    const w = await mountCard();
    const input = w.get('[data-test="cover-template-file"] input');
    expect(input.attributes("accept")).toBe(".tex");
    const file = new File(["\documentclass{article}"], "new.tex");
    upload.mockResolvedValue({ id: 3, name: "new", builtin: false, created_at: "2026-10-03T10:00:00Z" } as never);
    Object.defineProperty(input.element, "files", { value: [file], configurable: true });
    await input.trigger("change");
    await flushPromises();
    await w.get('[data-test="cover-template-upload"]').trigger("click");
    await flushPromises();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][0]).toBe("/cover-letter-templates");
    expect((upload.mock.calls[0][1] as FormData).get("file")).toBeInstanceOf(File);
    expect(w.find('[data-test="cover-template-3"]').exists()).toBe(true);
    expect(w.findComponent({ name: "VFileInput" }).props("modelValue")).toBeNull();
    expect(w.get('[data-test="cover-template-upload"]').attributes("disabled")).toBeDefined();
    w.unmount();
  });

  it("renames a custom template", async () => {
    const w = await mountCard();
    patch.mockResolvedValue({ ...custom, name: "Renamed" } as never);
    await w.get('[data-test="cover-template-rename-2"]').trigger("click");
    await flushPromises();
    // the dialog is teleported to <body>
    const field = document.body.querySelector('[data-test="cover-template-rename-input"] input') as HTMLInputElement;
    expect(field.value).toBe("Mine");
    field.value = "Renamed";
    field.dispatchEvent(new Event("input"));
    await flushPromises();
    (document.body.querySelector('[data-test="cover-template-rename-save"]') as HTMLElement).click();
    await flushPromises();
    expect(patch).toHaveBeenCalledWith("/cover-letter-templates/2", { name: "Renamed" });
    expect(w.get('[data-test="cover-template-2"]').text()).toContain("Renamed");
    w.unmount();
  });

  it("asks for confirmation before deleting", async () => {
    const w = await mountCard();
    del.mockResolvedValue(undefined as never);
    await w.get('[data-test="cover-template-delete-2"]').trigger("click");
    await flushPromises();
    expect(del).not.toHaveBeenCalled();
    const ok = document.body.querySelector('[data-test="confirm-ok"]') as HTMLElement;
    expect(ok).not.toBeNull();
    ok.click();
    await flushPromises();
    expect(del).toHaveBeenCalledWith("/cover-letter-templates/2");
    expect(w.find('[data-test="cover-template-2"]').exists()).toBe(false);
    w.unmount();
  });

  it("disables Save for empty or over-long names", async () => {
    const w = await mountCard();
    await w.get('[data-test="cover-template-rename-2"]').trigger("click");
    await flushPromises();
    const field = document.body.querySelector('[data-test="cover-template-rename-input"] input') as HTMLInputElement;
    expect(field.getAttribute("maxlength")).toBe("120");
    const save = () => document.body.querySelector('[data-test="cover-template-rename-save"]') as HTMLButtonElement;
    for (const [value, disabled] of [["   ", true], ["x".repeat(121), true], ["x".repeat(120), false]] as const) {
      field.value = value;
      field.dispatchEvent(new Event("input"));
      await flushPromises();
      expect(save().disabled).toBe(disabled);
    }
    w.unmount();
  });

  it("delete confirmation mentions that letters keep their copy", async () => {
    const w = await mountCard();
    await w.get('[data-test="cover-template-delete-2"]').trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain("Existing cover letters keep their own copy.");
    w.unmount();
    setLocale("de");
    const wde = await mountCard();
    await wde.get('[data-test="cover-template-delete-2"]').trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain("Das Template „Mine“ löschen? Bestehende Anschreiben behalten ihre eigene Kopie.");
    wde.unmount();
    setLocale("en");
  });
});
