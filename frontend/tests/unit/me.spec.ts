import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick } from "vue";
import { VLayout } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import type { LlmConfigOut, LlmPurposes, ProfileDocumentOut, UserProfileOut } from "@/api/types";
import DangerZone from "@/components/DangerZone.vue";
import MarkdownEditor from "@/components/MarkdownEditor.vue";
import { renderMarkdown } from "@/domain/markdown";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useLlmStore } from "@/stores/llm";
import { useMeStore } from "@/stores/me";
import { useNotifyStore } from "@/stores/notify";
import MeView from "@/views/MeView.vue";

const routeGuards: Array<() => unknown> = [];
vi.mock("vue-router", async (orig) => {
  const mod = await orig<typeof import("vue-router")>();
  return { ...mod, onBeforeRouteLeave: (g: () => unknown) => void routeGuards.push(g) };
});

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);
const patch = vi.mocked(api.patch);
const del = vi.mocked(api.del);

beforeAll(() => {
  vi.stubGlobal("visualViewport", { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, addEventListener() {}, removeEventListener() {} });
});

const cfg = (over: Partial<LlmConfigOut> = {}): LlmConfigOut => ({
  id: 1, name: "Main", provider: "anthropic", base_url: null, api_key: "…1234", has_api_key: true, model: "claude-x",
  thinking: "off", supports_images: true, extra_body: {}, extra_headers: {}, price_in: null, price_out: null, is_default: true, ...over,
});
const doc = (over: Partial<ProfileDocumentOut> = {}): ProfileDocumentOut => ({
  id: 1, filename: "cv.pdf", display_name: "cv.pdf", mime: "application/pdf", kind: "pdf_text", description: "My CV",
  text: "Some text", text_source: "extracted", created_at: "2026-10-23T10:00:00Z", updated_at: "2026-10-23T10:00:00Z", usable: true, ...over,
});
const profile = (over: Partial<UserProfileOut> = {}): UserProfileOut => ({
  free_text: null, profile_markdown: null, generated_at: null, edited_since_generation: false,
  inputs_changed_since_generation: false, version: 0, documents_used: 0, documents_unused: 0, ...over,
});

let configs: LlmConfigOut[];
let purposes: LlmPurposes;
let docs: ProfileDocumentOut[];
let prof: UserProfileOut;

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  routeGuards.length = 0;
  for (const m of [get, post, put, patch, del, vi.mocked(api.upload)]) m.mockReset();
  configs = [cfg()];
  purposes = { profile: null, fit: null, extraction: null };
  docs = [];
  prof = profile();
  get.mockImplementation((async (path: string) => {
    if (path === "/me/documents") return docs;
    if (path === "/me/profile") return prof;
    if (path === "/llm/configs") return configs;
    if (path === "/llm/purposes") return purposes;
    if (path === "/settings") return { fit_auto: false, fit_concurrency: 2, daily_limit_kind: "none", daily_limit_value: null };
    if (path === "/llm/usage") return { today: {}, month: {}, limit: { kind: "none", value: null }, limit_exceeded: false };
    throw new Error(`unexpected GET ${path}`);
  }) as never);
  document.body.innerHTML = "";
});

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null;
const text = () => document.body.textContent ?? "";

async function mountView() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(MeView)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
  await flushPromises();
  return w;
}
async function setValue(sel: string, value: string) {
  const el = q(sel) as HTMLInputElement | HTMLTextAreaElement;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  await nextTick();
}
async function blur(sel: string) {
  (q(sel) as HTMLElement).dispatchEvent(new Event("blur"));
  await flushPromises();
}

describe("markdown rendering", () => {
  it("escapes raw HTML", () => {
    const html = renderMarkdown("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
  });

  it("renders markdown, opens links safely and drops javascript: links", () => {
    const html = renderMarkdown("## Summary\n\nSee https://example.com and [x](javascript:alert(1))");
    expect(html).toContain("<h2>Summary</h2>");
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("noopener");
    expect(html).not.toContain('href="javascript:');
  });

  it("MarkdownEditor preview shows no raw HTML elements", async () => {
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(MarkdownEditor, { modelValue: "<script>x</script>\n\n**bold**" })) });
    const w = mount(Host, { global: { plugins: [vuetify, i18n] }, attachTo: document.body });
    (q("[data-test=md-mode-preview]") as HTMLElement).click();
    await flushPromises();
    const preview = q("[data-test=md-preview]")!;
    expect(preview.querySelector("script")).toBeNull();
    expect(preview.querySelector("strong")?.textContent).toBe("bold");
    expect(preview.textContent).toContain("<script>x</script>");
    w.unmount();
  });
});

describe("documents", () => {
  it("shows type chip and usable status with its source", async () => {
    docs = [
      doc({ id: 1, kind: "pdf_text", text_source: "extracted" }),
      doc({ id: 2, kind: "image", filename: "scan.png", display_name: "scan.png", text: "From LLM", text_source: "llm" }),
      doc({ id: 3, kind: "pdf_scan", filename: "old.pdf", display_name: "old.pdf", text: null, text_source: null, usable: false }),
      doc({ id: 4, kind: "text", filename: "n.md", display_name: "n.md", text: "Typed", text_source: "manual" }),
    ];
    const w = await mountView();
    expect(q("[data-test=doc-kind-1]")!.textContent).toBe("PDF with text");
    expect(q("[data-test=doc-kind-3]")!.textContent).toBe("Scanned PDF");
    expect(q("[data-test=doc-kind-2]")!.textContent).toBe("Image");
    expect(q("[data-test=doc-status-1]")!.textContent).toContain("Usable");
    expect(q("[data-test=doc-status-1]")!.textContent).toContain("extracted from file");
    expect(q("[data-test=doc-status-2]")!.textContent).toContain("AI extraction");
    expect(q("[data-test=doc-status-4]")!.textContent).toContain("edited by you");
    expect(q("[data-test=doc-status-3]")!.textContent).toContain("Not usable");
    expect(q("[data-test=doc-status-3]")!.textContent).not.toContain("Usable");
    w.unmount();
  });

  it("disables extraction with a tooltip when the extraction config has no image support", async () => {
    configs = [cfg({ id: 1, supports_images: true }), cfg({ id: 2, name: "Local", provider: "openai_compatible", supports_images: false, is_default: false })];
    purposes = { profile: null, fit: null, extraction: 2 };
    docs = [doc({ id: 3, kind: "pdf_scan", text: null, text_source: null, usable: false })];
    const w = await mountView();
    const btn = q("[data-test=doc-extract-3]") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(q("[data-test=doc-extract-tip-3]")!.getAttribute("title")).toBe(
      "The configuration for text extraction does not support images. Choose an image-capable one in the settings.",
    );
    btn.click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    w.unmount();
  });

  it("disables extraction with a different hint when no configuration exists", async () => {
    configs = [];
    docs = [doc({ id: 3, kind: "image", text: null, text_source: null, usable: false })];
    const w = await mountView();
    expect((q("[data-test=doc-extract-3]") as HTMLButtonElement).disabled).toBe(true);
    expect(q("[data-test=doc-extract-tip-3]")!.getAttribute("title")).toContain("No LLM configuration");
    w.unmount();
  });

  it("extracts with an image-capable default configuration and shows the limit warning", async () => {
    docs = [doc({ id: 3, kind: "image", text: null, text_source: null, usable: false })];
    post.mockResolvedValue({ document: doc({ id: 3, kind: "image", text: "Read", text_source: "llm" }), limit_exceeded: true } as never);
    const w = await mountView();
    const btn = q("[data-test=doc-extract-3]") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    btn.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/me/documents/3/extract");
    expect(q("[data-test=doc-status-3]")!.textContent).toContain("AI extraction");
    expect(q("[data-test=limit-warning]")).not.toBeNull();
    w.unmount();
  });

  it("does not offer extraction for documents that already have text", async () => {
    docs = [doc({ id: 1 })];
    const w = await mountView();
    expect(q("[data-test=doc-extract-1]")).toBeNull();
    w.unmount();
  });

  it("saves the description only when it changed", async () => {
    docs = [doc({ id: 1, description: "My CV" })];
    patch.mockResolvedValue(doc({ id: 1, description: "Resume 2026" }) as never);
    const w = await mountView();
    const sel = "[data-test=doc-description-1] input";
    await blur(sel);
    expect(patch).not.toHaveBeenCalled();
    await setValue(sel, "Resume 2026");
    await blur(sel);
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith("/me/documents/1", { description: "Resume 2026" });
    w.unmount();
  });

  it("uploads a file with its description", async () => {
    const w = await mountView();
    const store = useMeStore();
    const created = doc({ id: 7, filename: "new.txt", display_name: "new.txt", kind: "text" });
    vi.mocked(api.upload).mockResolvedValue(created as never);
    const file = new File(["hello"], "new.txt", { type: "text/plain" });
    expect(await store.upload(file, "Letter")).toBe(true);
    const form = vi.mocked(api.upload).mock.calls[0]![1] as FormData;
    expect(vi.mocked(api.upload).mock.calls[0]![0]).toBe("/me/documents");
    expect((form.get("file") as File).name).toBe("new.txt");
    expect(form.get("description")).toBe("Letter");
    expect(store.documents.map((d) => d.id)).toEqual([7]);
    w.unmount();
  });

  it("reports an unreadable upload through the snackbar", async () => {
    const w = await mountView();
    vi.mocked(api.upload).mockRejectedValue(new ApiError(422, "document_unreadable", {}, "unreadable"));
    expect(await useMeStore().upload(new File(["x"], "a.pdf"), "")).toBe(false);
    expect(useNotifyStore().message).toBe("This document could not be read (corrupt or password-protected).");
    w.unmount();
  });

  it("edits the text manually and deletes after confirmation", async () => {
    docs = [doc({ id: 1 })];
    patch.mockResolvedValue(doc({ id: 1, text: "Fixed", text_source: "manual" }) as never);
    del.mockResolvedValue(undefined as never);
    const w = await mountView();
    (q("[data-test=doc-text-1]") as HTMLElement).click();
    await flushPromises();
    await setValue("[data-test=doc-text-input] textarea", "Fixed");
    (q("[data-test=doc-text-save]") as HTMLElement).click();
    await flushPromises();
    expect(patch).toHaveBeenCalledWith("/me/documents/1", { text: "Fixed" });
    expect(q("[data-test=doc-status-1]")!.textContent).toContain("edited by you");

    (q("[data-test=doc-delete-1]") as HTMLElement).click();
    await flushPromises();
    expect(del).not.toHaveBeenCalled();
    (q("[data-test=confirm-ok]") as HTMLElement).click();
    await flushPromises();
    expect(del).toHaveBeenCalledWith("/me/documents/1");
    expect(q("[data-test=doc-status-1]")).toBeNull();
    w.unmount();
  });
});

describe("provider notice", () => {
  it("names the provider and model of the resolved profile and extraction configurations", async () => {
    configs = [cfg({ id: 1, name: "Main", provider: "anthropic", model: "claude-x" }), cfg({ id: 2, name: "Vision", provider: "openai", model: "gpt-v", is_default: false })];
    purposes = { profile: null, fit: null, extraction: 2 };
    const w = await mountView();
    const notice = q("[data-test=provider-notice]")!.textContent!;
    expect(notice).toContain("Anthropic");
    expect(notice).toContain("claude-x");
    expect(notice).toContain("OpenAI");
    expect(notice).toContain("gpt-v");
    expect(useMeStore().providerName).toBe("Anthropic (claude-x)");
    w.unmount();
  });

  it("tells that no configuration exists", async () => {
    configs = [];
    const w = await mountView();
    expect(q("[data-test=provider-notice]")!.textContent).toContain("No LLM configuration");
    expect((q("[data-test=generate]") as HTMLButtonElement).disabled).toBe(true);
    w.unmount();
  });
});

describe("free text", () => {
  it("autosaves on blur only when the text changed", async () => {
    prof = profile({ free_text: "Remote only" });
    put.mockResolvedValue(profile({ free_text: "Remote only, Berlin" }) as never);
    const w = await mountView();
    const sel = "[data-test=free-text] textarea";
    await blur(sel);
    expect(put).not.toHaveBeenCalled();
    await setValue(sel, "Remote only, Berlin");
    await blur(sel);
    expect(put).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith("/me/profile/free-text", { free_text: "Remote only, Berlin" });
    await blur(sel); // saved now: no second call
    expect(put).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it("shows the 422 message of the free text field", async () => {
    put.mockRejectedValue(new ApiError(422, "validation_error", { errors: [{ loc: ["body", "free_text"], msg: "Too long" }] }, "invalid"));
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", "x");
    await blur("[data-test=free-text] textarea");
    expect(q("[data-test=free-text]")!.textContent).toContain("Too long");
    w.unmount();
  });
});

describe("profile generation", () => {
  it("shows used and unused counts and creates the profile without a prompt", async () => {
    prof = profile({ documents_used: 2, documents_unused: 1 });
    post.mockResolvedValue({ profile: profile({ profile_markdown: "## Summary\n\nHi", version: 1, generated_at: "2026-10-23T10:00:00Z", documents_used: 2, documents_unused: 1 }), limit_exceeded: false } as never);
    const w = await mountView();
    expect(q("[data-test=generate-counts]")!.textContent).toContain("2 documents used");
    expect(q("[data-test=generate-counts]")!.textContent).toContain("1 without text");
    expect(q("[data-test=generate]")!.textContent).toContain("Create profile");
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/me/profile/generate");
    expect(q("[data-test=generate]")!.textContent).toContain("Recreate profile");
    expect(q("[data-test=limit-warning]")).toBeNull();
    w.unmount();
  });

  it("asks before overwriting manual edits and then generates with overwrite", async () => {
    prof = profile({ profile_markdown: "## Summary\n\nMine", edited_since_generation: true, version: 2, documents_used: 1 });
    post.mockResolvedValue({ profile: profile({ profile_markdown: "## Summary\n\nNew", version: 3, documents_used: 1 }), limit_exceeded: true } as never);
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    expect(text()).toContain("You have edited the profile manually");
    (q("[data-test=confirm-ok]") as HTMLElement).click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/me/profile/generate?overwrite=true");
    expect(useMeStore().profile?.version).toBe(3);
    expect(q("[data-test=limit-warning]")).not.toBeNull();
    w.unmount();
  });

  it("cancelling the overwrite prompt does not generate", async () => {
    prof = profile({ profile_markdown: "x", edited_since_generation: true, documents_used: 1 });
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    (q("[data-test=confirm-cancel]") as HTMLElement).click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    w.unmount();
  });

  it("shows the inputs-changed notice only when the inputs changed", async () => {
    prof = profile({ profile_markdown: "x", inputs_changed_since_generation: true, documents_used: 1 });
    const w = await mountView();
    expect(q("[data-test=inputs-changed]")).not.toBeNull();
    w.unmount();
    prof = profile({ profile_markdown: "x", documents_used: 1 });
    const w2 = await mountView();
    expect(q("[data-test=inputs-changed]")).toBeNull();
    w2.unmount();
  });

  it("autosaves the markdown only when it changed", async () => {
    prof = profile({ profile_markdown: "## Summary\n\nOld", version: 1, documents_used: 1 });
    put.mockResolvedValue(profile({ profile_markdown: "## Summary\n\nNew", version: 2, edited_since_generation: true }) as never);
    const w = await mountView();
    const sel = "[data-test=md-input] textarea";
    await blur(sel);
    expect(put).not.toHaveBeenCalled();
    await setValue(sel, "## Summary\n\nNew");
    await blur(sel);
    expect(put).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith("/me/profile/markdown", { profile_markdown: "## Summary\n\nNew" });
    expect(useMeStore().profile?.edited_since_generation).toBe(true);
    w.unmount();
  });
});

describe("danger zone: delete user profile", () => {
  async function typeConfirm() {
    const input = q("[data-test=ttc-input] input") as HTMLInputElement;
    input.value = "DELETE";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await nextTick();
  }

  it("calls the admin endpoint only after confirmation and clears the me store", async () => {
    post.mockResolvedValue({ deleted_documents: 3 } as never);
    const pinia = createPinia();
    setActivePinia(pinia);
    const me = useMeStore();
    me.documents = [doc()];
    me.profile = profile({ profile_markdown: "x" });
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(DangerZone)) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    (q("[data-test=danger-delete-profile]") as HTMLElement).click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    await typeConfirm();
    (q("[data-test=ttc-ok]") as HTMLElement).click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/admin/delete-profile");
    expect(me.documents).toEqual([]);
    expect(me.profile).toBeNull();
    expect(useNotifyStore().message).toContain("3");
    expect(useNotifyStore().color).toBe("success");
    w.unmount();
  });

  it("keeps the store when the server refuses", async () => {
    post.mockRejectedValue(new ApiError(409, "runs_active", {}, "Runs are active"));
    const pinia = createPinia();
    setActivePinia(pinia);
    const me = useMeStore();
    me.documents = [doc()];
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(DangerZone)) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    (q("[data-test=danger-delete-profile]") as HTMLElement).click();
    await flushPromises();
    await typeConfirm();
    (q("[data-test=ttc-ok]") as HTMLElement).click();
    await flushPromises();
    expect(me.documents).toHaveLength(1);
    expect(useNotifyStore().color).toBe("error");
    w.unmount();
  });
});

describe("llm store resolution", () => {
  it("falls back to the default configuration when the purpose is unassigned", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const llm = useLlmStore();
    llm.configs = [cfg({ id: 1, is_default: false, name: "A" }), cfg({ id: 2, is_default: true, name: "B", provider: "openai" })];
    llm.purposes = { profile: null, fit: null, extraction: null };
    expect(useMeStore().profileConfig?.id).toBe(2);
    llm.purposes = { profile: 1, fit: null, extraction: null };
    expect(useMeStore().profileConfig?.id).toBe(1);
  });
});

describe("fix round 1", () => {
  it("409 profile_edited during generation reloads the profile and shows a specific message", async () => {
    prof = profile({ profile_markdown: "old", documents_used: 1 });
    post.mockImplementation((async () => {
      prof = profile({ profile_markdown: "edited elsewhere", edited_since_generation: true, version: 5, documents_used: 1 });
      throw new ApiError(409, "profile_edited", {}, "edited");
    }) as never);
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(useMeStore().profile?.version).toBe(5);
    expect(useNotifyStore().message).toBe("The profile was changed while it was being generated; nothing was overwritten.");
    w.unmount();
  });

  it("profile_missing shows its error text", async () => {
    prof = profile({ free_text: "x", documents_used: 0 });
    post.mockRejectedValue(new ApiError(409, "profile_missing", {}, "missing"));
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(useNotifyStore().message).toContain("nothing to build a profile from");
    w.unmount();
  });

  it("the overwrite dialog has its own text", async () => {
    prof = profile({ profile_markdown: "x", edited_since_generation: true, documents_used: 1 });
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(text()).toContain("Recreating the profile replaces your changes.");
    w.unmount();
  });

  it("flushes an unsaved markdown edit before checking for manual edits when Recreate is clicked", async () => {
    prof = profile({ profile_markdown: "## Summary\n\nOld", version: 1, documents_used: 1 });
    put.mockResolvedValue(profile({ profile_markdown: "## Summary\n\nNew", version: 2, edited_since_generation: true, documents_used: 1 }) as never);
    const w = await mountView();
    await setValue("[data-test=md-input] textarea", "## Summary\n\nNew");
    (q("[data-test=generate]") as HTMLElement).click(); // no blur in between
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/me/profile/markdown", { profile_markdown: "## Summary\n\nNew" });
    expect(post).not.toHaveBeenCalled();
    expect(q("[data-test=confirm-ok]")).not.toBeNull();
    w.unmount();
  });

  it("flushes an unsaved free text before generating", async () => {
    prof = profile({ documents_used: 1 });
    put.mockResolvedValue(profile({ free_text: "Berlin", documents_used: 1 }) as never);
    post.mockResolvedValue({ profile: profile({ profile_markdown: "x", documents_used: 1 }), limit_exceeded: false } as never);
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", "Berlin");
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(put.mock.invocationCallOrder[0]!).toBeLessThan(post.mock.invocationCallOrder[0]!);
    w.unmount();
  });

  it("disables the editors while generating", async () => {
    prof = profile({ profile_markdown: "x", documents_used: 1 });
    let release: (v: unknown) => void = () => {};
    post.mockReturnValue(new Promise((r) => (release = r)) as never);
    const w = await mountView();
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect((q("[data-test=md-input] textarea") as HTMLTextAreaElement).disabled).toBe(true);
    expect((q("[data-test=free-text] textarea") as HTMLTextAreaElement).disabled).toBe(true);
    release({ profile: profile({ profile_markdown: "y", documents_used: 1 }), limit_exceeded: false });
    await flushPromises();
    expect((q("[data-test=md-input] textarea") as HTMLTextAreaElement).disabled).toBe(false);
    w.unmount();
  });

  it("saves unsaved edits when the route is left", async () => {
    prof = profile({ free_text: "a", profile_markdown: "m", documents_used: 1 });
    put.mockResolvedValue(profile({ free_text: "b" }) as never);
    const w = await mountView();
    expect(routeGuards).toHaveLength(1);
    await setValue("[data-test=free-text] textarea", "b");
    await routeGuards[0]!();
    expect(put).toHaveBeenCalledWith("/me/profile/free-text", { free_text: "b" });
    w.unmount();
  });

  it("saves unsaved edits on unmount", async () => {
    prof = profile({ free_text: "a", documents_used: 1 });
    put.mockResolvedValue(profile({ free_text: "c" }) as never);
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", "c");
    w.unmount();
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/me/profile/free-text", { free_text: "c" });
  });

  it("warns on page unload only while there are unsaved changes", async () => {
    prof = profile({ free_text: "a", documents_used: 1 });
    const w = await mountView();
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    await setValue("[data-test=free-text] textarea", "dirty");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
    w.unmount();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it("reloads the LLM configurations on every load (stale after a reset)", async () => {
    const w = await mountView();
    expect(q("[data-test=provider-notice]")!.textContent).toContain("Anthropic");
    expect(useLlmStore().loaded).toBe(true);
    configs = [];
    purposes = { profile: null, fit: null, extraction: null };
    await useMeStore().load(); // the llm store is already loaded; it must still refetch
    await flushPromises();
    expect(useLlmStore().configs).toEqual([]);
    expect(q("[data-test=provider-notice]")!.textContent).toContain("No LLM configuration");
    expect((q("[data-test=generate]") as HTMLButtonElement).disabled).toBe(true);
    w.unmount();
  });

  it("refuses free text over 20,000 characters with a translated message", async () => {
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", "x".repeat(20_001));
    await blur("[data-test=free-text] textarea");
    expect(put).not.toHaveBeenCalled();
    expect(q("[data-test=free-text]")!.textContent).toContain("at most 20,000 characters");
    w.unmount();
  });

  it("hides the extraction line when the extraction configuration cannot read images", async () => {
    configs = [cfg({ id: 1 }), cfg({ id: 2, name: "Text only", provider: "openai_compatible", model: "local", supports_images: false, is_default: false })];
    purposes = { profile: null, fit: null, extraction: 2 };
    const w = await mountView();
    const notice = q("[data-test=provider-notice]")!.textContent!;
    expect(notice).toContain("Anthropic");
    expect(notice).not.toContain("local");
    w.unmount();
  });

  it("tracks several concurrent extractions", async () => {
    docs = [doc({ id: 3, kind: "image", text: null, text_source: null, usable: false }), doc({ id: 4, kind: "image", text: null, text_source: null, usable: false })];
    const resolvers: Array<(v: unknown) => void> = [];
    post.mockImplementation((() => new Promise((r) => resolvers.push(r))) as never);
    const w = await mountView();
    const store = useMeStore();
    void store.extract(3);
    void store.extract(4);
    await nextTick();
    expect([...store.extracting].sort()).toEqual([3, 4]);
    resolvers[0]!({ document: doc({ id: 3, kind: "image" }), limit_exceeded: false });
    await flushPromises();
    expect([...store.extracting]).toEqual([4]);
    resolvers[1]!({ document: doc({ id: 4, kind: "image" }), limit_exceeded: false });
    await flushPromises();
    expect(store.extracting.size).toBe(0);
    w.unmount();
  });

  it("keeps the typed description when saving it fails", async () => {
    docs = [doc({ id: 1, description: "My CV" })];
    patch.mockRejectedValue(new ApiError(500, null, {}, "boom"));
    const w = await mountView();
    const sel = "[data-test=doc-description-1] input";
    await setValue(sel, "Typed");
    await blur(sel);
    expect((q(sel) as HTMLInputElement).value).toBe("Typed");
    w.unmount();
  });

  it("uploads through the file input and description field", async () => {
    const w = await mountView();
    const created = doc({ id: 9, filename: "n.txt", display_name: "n.txt", kind: "text" });
    vi.mocked(api.upload).mockResolvedValue(created as never);
    const input = q("[data-test=doc-file] input") as HTMLInputElement;
    const file = new File(["hi"], "n.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await flushPromises();
    await setValue("[data-test=doc-upload-description] input", "Cover letter");
    (q("[data-test=doc-upload]") as HTMLElement).click();
    await flushPromises();
    const [path, form] = vi.mocked(api.upload).mock.calls[0]! as [string, FormData];
    expect(path).toBe("/me/documents");
    expect((form.get("file") as File).name).toBe("n.txt");
    expect(form.get("description")).toBe("Cover letter");
    expect(q("[data-test=doc-kind-9]")).not.toBeNull();
    w.unmount();
  });
});

describe("markdown images and links", () => {
  it("never renders an img element; remote images become a link", () => {
    const html = renderMarkdown("![logo](https://evil.example/pixel.png) and ![x](javascript:alert(1))");
    expect(html).not.toContain("<img");
    expect(html).toContain('<a href="https://evil.example/pixel.png"');
    expect(html).toContain("logo");
    expect(html).not.toMatch(/href="javascript:/i);
  });

  it("leaves mixed-case javascript: links unlinked", () => {
    const html = renderMarkdown("[x](JaVaScRiPt:alert(1))");
    expect(html).not.toMatch(/href=/i);
  });
});

describe("final fix wave", () => {
  it("never generates over a failed save and keeps the typed text", async () => {
    prof = profile({ profile_markdown: "## Summary\n\nOld", version: 1, documents_used: 1 });
    put.mockRejectedValue(new ApiError(500, null, {}, "boom"));
    const w = await mountView();
    await setValue("[data-test=md-input] textarea", "## Summary\n\nTyped");
    (q("[data-test=generate]") as HTMLElement).click();
    await flushPromises();
    expect(put).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
    expect(q("[data-test=confirm-ok]")).toBeNull();
    expect((q("[data-test=md-input] textarea") as HTMLTextAreaElement).value).toBe("## Summary\n\nTyped");
    expect(useNotifyStore().visible).toBe(true);
    w.unmount();
  });

  it("a double click starts exactly one generation", async () => {
    prof = profile({ documents_used: 1 });
    post.mockResolvedValue({ profile: profile({ profile_markdown: "x", documents_used: 1 }), limit_exceeded: false } as never);
    const w = await mountView();
    const btn = q("[data-test=generate]") as HTMLElement;
    btn.click();
    btn.click();
    await flushPromises();
    expect(post).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it("a double click on an edited profile opens one dialog and flushes once", async () => {
    prof = profile({ profile_markdown: "m", edited_since_generation: true, version: 1, documents_used: 1 });
    put.mockResolvedValue(profile({ profile_markdown: "m2", edited_since_generation: true, version: 2, documents_used: 1 }) as never);
    const w = await mountView();
    await setValue("[data-test=md-input] textarea", "m2");
    const btn = q("[data-test=generate]") as HTMLElement;
    btn.click();
    btn.click();
    await flushPromises();
    expect(put).toHaveBeenCalledTimes(1);
    expect(document.body.querySelectorAll("[data-test=confirm-ok]")).toHaveLength(1);
    expect(post).not.toHaveBeenCalled();
    w.unmount();
  });

  it("keeps free text typed while the save was in flight", async () => {
    prof = profile({ free_text: "a" });
    let release: (v: unknown) => void = () => {};
    put.mockReturnValue(new Promise((r) => (release = r)) as never);
    const w = await mountView();
    const sel = "[data-test=free-text] textarea";
    await setValue(sel, "AB");
    await blur(sel);
    await setValue(sel, "ABC"); // typed while the request is running
    release(profile({ free_text: "AB" }));
    await flushPromises();
    expect((q(sel) as HTMLTextAreaElement).value).toBe("ABC");
    w.unmount();
  });

  it("keeps markdown typed while the save was in flight", async () => {
    prof = profile({ profile_markdown: "a", version: 1 });
    let release: (v: unknown) => void = () => {};
    put.mockReturnValue(new Promise((r) => (release = r)) as never);
    const w = await mountView();
    const sel = "[data-test=md-input] textarea";
    await setValue(sel, "AB");
    await blur(sel);
    await setValue(sel, "ABC");
    release(profile({ profile_markdown: "AB", version: 2, edited_since_generation: true }));
    await flushPromises();
    expect((q(sel) as HTMLTextAreaElement).value).toBe("ABC");
    w.unmount();
  });

  it("still applies the server value when nothing was typed meanwhile", async () => {
    prof = profile({ free_text: "a" });
    put.mockResolvedValue(profile({ free_text: "normalised" }) as never);
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", " AB ");
    await blur("[data-test=free-text] textarea");
    expect((q("[data-test=free-text] textarea") as HTMLTextAreaElement).value).toBe("normalised");
    w.unmount();
  });

  it("tells that an over-long free text was not saved when the page is left", async () => {
    const w = await mountView();
    await setValue("[data-test=free-text] textarea", "x".repeat(20_001));
    await routeGuards[0]!();
    expect(put).not.toHaveBeenCalled();
    const notify = useNotifyStore();
    expect(notify.visible).toBe(true);
    expect(notify.message).toContain("not saved");
    w.unmount();
  });

  it("reports a failing llm.load inside me.load", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const llm = useLlmStore();
    llm.load = vi.fn().mockRejectedValue(new ApiError(500, null, {}, "llm down"));
    await useMeStore().load();
    const notify = useNotifyStore();
    expect(notify.visible).toBe(true);
    expect(notify.message).toBe("llm down");
  });
});
