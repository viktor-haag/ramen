import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import type { CoverLetterOut, CoverLetterTemplate, ProfileDocumentOut, UserProfileOut } from "@/api/types";
import CoverLetterDialog from "@/components/CoverLetterDialog.vue";
import CoverLetterSection from "@/components/CoverLetterSection.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const push = vi.fn();
vi.mock("vue-router", () => ({ useRouter: () => ({ push }) }));

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

const builtin: CoverLetterTemplate = { id: 1, name: "Standard", builtin: true, created_at: "2026-10-01T10:00:00Z" };
const custom: CoverLetterTemplate = { id: 2, name: "Mine", builtin: false, created_at: "2026-10-02T10:00:00Z" };
const doc = (id: number, text: string | null): ProfileDocumentOut => ({
  id, filename: `d${id}.pdf`, display_name: `Doc ${id}`, mime: "application/pdf", kind: "pdf_text", description: null, text,
  text_source: text ? "extracted" : null, created_at: "", updated_at: "", usable: !!text,
});
const profile = (md: string | null): UserProfileOut => ({
  free_text: null, profile_markdown: md, generated_at: md ? "2026-10-01T10:00:00Z" : null, edited_since_generation: false,
  inputs_changed_since_generation: false, version: 1, documents_used: 1, documents_unused: 0,
});
const letterOut = (over: Partial<CoverLetterOut> = {}): CoverLetterOut => ({
  id: 3, application_id: 7, format: "latex", template_id: 2, template_name: "Mine", language: "de",
  context: { profile: true, document_ids: [11], notes: "old notes" }, content: "x", status: "idle", error: null,
  compile_log: null, pdf_available: false, compiler_available: true, compiled_at: null, updated_at: "2026-10-02T10:00:00Z", messages: [],
  ...over,
});

let prof: UserProfileOut;
let docs: ProfileDocumentOut[];
let existingLetter: CoverLetterOut | null;

beforeEach(() => {
  setLocale("en");
  push.mockReset();
  get.mockReset();
  post.mockReset();
  prof = profile("# Me");
  docs = [doc(11, "cv text"), doc(12, null)];
  existingLetter = null;
  get.mockImplementation((async (path: string) => {
    if (path === "/cover-letter-templates") return [builtin, custom];
    if (path === "/me/documents") return docs;
    if (path === "/me/profile") return prof;
    if (path === "/llm/configs" || path.startsWith("/llm")) return [];
    if (path === "/applications/7/cover-letter") {
      if (existingLetter) return existingLetter;
      throw new ApiError(404, "cover_letter_not_found", {}, "nf");
    }
    return [];
  }) as never);
  post.mockResolvedValue(letterOut({ template_id: 1 }));
});

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null;
const input = (sel: string) => q(`${sel} input`) as HTMLInputElement;

async function mountDialog(existing: CoverLetterOut | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({
    render: () => h(VLayout, null, () => h(CoverLetterDialog, { modelValue: true, applicationId: 7, existing })),
  });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}

async function mountSection() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(CoverLetterSection, { applicationId: 7 })) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}

describe("CoverLetterDialog", () => {
  it("preselects the default template and hides the template select for plain text", async () => {
    const w = await mountDialog();
    expect(q("[data-test=cl-template]")).not.toBeNull();
    expect(q("[data-test=cl-template]")!.textContent).toContain("Standard");
    q("[data-test=cl-format-text]")!.click();
    await flushPromises();
    expect(q("[data-test=cl-template]")).toBeNull();
    w.unmount();
  });

  it("disables the profile checkbox without a generated profile", async () => {
    prof = profile(null);
    const w = await mountDialog();
    expect(input("[data-test=cl-profile]").disabled).toBe(true);
    expect(input("[data-test=cl-profile]").checked).toBe(false);
    w.unmount();
  });

  it("disables a document without text", async () => {
    const w = await mountDialog();
    expect(input("[data-test=cl-doc-12]").disabled).toBe(true);
    expect(input("[data-test=cl-doc-11]").disabled).toBe(false);
    w.unmount();
  });

  it("posts the chosen documents and notes, then opens the editor", async () => {
    const w = await mountDialog();
    input("[data-test=cl-doc-11]").click();
    const notes = q("[data-test=cl-notes] textarea") as HTMLTextAreaElement;
    notes.value = "Mention Rust";
    notes.dispatchEvent(new Event("input", { bubbles: true }));
    await flushPromises();
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter", {
      format: "latex",
      template_id: 1,
      language: "posting",
      context: { profile: true, document_ids: [11], notes: "Mention Rust" },
    });
    expect(push).toHaveBeenCalledWith({ name: "cover-letter", params: { id: "7" } });
    expect(w.findComponent(CoverLetterDialog).emitted("created")).toHaveLength(1);
    w.unmount();
  });

  it("sends profile:false when no profile exists", async () => {
    prof = profile(null);
    const w = await mountDialog();
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    expect(post.mock.calls[0]![1]).toMatchObject({ context: { profile: false } });
    w.unmount();
  });

  it("drops stale and text-less documents and falls back to the default template when prefilling", async () => {
    const w = await mountDialog(letterOut({ template_id: 99, context: { profile: true, document_ids: [11, 12, 404], notes: "" } }));
    expect(q("[data-test=cl-template]")!.textContent).toContain("Standard");
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    q("[data-test=confirm-ok]")!.click();
    await flushPromises();
    expect(post.mock.calls[0]![1]).toMatchObject({ template_id: 1, context: { document_ids: [11] } });
    w.unmount();
  });

  it("sends no template for plain text", async () => {
    const w = await mountDialog();
    q("[data-test=cl-format-text]")!.click();
    await flushPromises();
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    expect(post.mock.calls[0]![1]).toMatchObject({ format: "text", template_id: null });
    w.unmount();
  });

  it("prefills from the existing letter and asks before replacing it", async () => {
    const w = await mountDialog(letterOut());
    expect(q("[data-test=cl-template]")!.textContent).toContain("Mine");
    expect(input("[data-test=cl-doc-11]").checked).toBe(true);
    expect((q("[data-test=cl-notes] textarea") as HTMLTextAreaElement).value).toBe("old notes");
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("The draft and chat history will be replaced.");
    q("[data-test=confirm-ok]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0]![1]).toMatchObject({ template_id: 2, language: "de", context: { profile: true, document_ids: [11], notes: "old notes" } });
    w.unmount();
  });

  it("does not navigate when creating fails", async () => {
    post.mockRejectedValue(new Error("boom"));
    const w = await mountDialog();
    q("[data-test=cl-submit]")!.click();
    await flushPromises();
    expect(push).not.toHaveBeenCalled();
    w.unmount();
  });
});

describe("CoverLetterSection", () => {
  it("offers to create a letter when there is none", async () => {
    const w = await mountSection();
    expect(w.get("[data-test=cl-create]").text()).toBe("Create cover letter");
    expect(w.find("[data-test=cl-open]").exists()).toBe(false);
    w.unmount();
  });

  it("offers to open an existing draft and navigates to the editor", async () => {
    existingLetter = letterOut();
    const w = await mountSection();
    expect(w.find("[data-test=cl-create]").exists()).toBe(false);
    await w.get("[data-test=cl-open]").trigger("click");
    expect(w.get("[data-test=cl-open]").text()).toBe("Open");
    expect(push).toHaveBeenCalledWith({ name: "cover-letter", params: { id: "7" } });
    w.unmount();
  });

  it("shows status and last change of an existing draft", async () => {
    existingLetter = letterOut();
    const w = await mountSection();
    expect(w.get("[data-test=cl-status]").text()).toBe("Draft ready");
    expect(w.get("[data-test=cl-last-change]").text()).toContain("2026");
    w.unmount();
  });

  it("ignores a letter that belongs to another application", async () => {
    existingLetter = letterOut({ application_id: 99 });
    const w = await mountSection();
    expect(w.find("[data-test=cl-open]").exists()).toBe(false);
    w.unmount();
  });
});
