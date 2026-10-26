import { EditorView } from "@codemirror/view";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import * as directives from "vuetify/directives";
import { VLayout } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import type { CoverLetterOut } from "@/api/types";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useCoverLetterStore } from "@/stores/coverLetter";
import CoverLetterView from "@/views/CoverLetterView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const push = vi.fn();
const leaveGuards: (() => unknown)[] = [];
vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
  onBeforeRouteLeave: (g: () => unknown) => leaveGuards.push(g),
  onBeforeRouteUpdate: () => undefined,
}));

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);
const del = vi.mocked(api.del);

const letterOut = (over: Partial<CoverLetterOut> = {}): CoverLetterOut => ({
  id: 3, application_id: 7, format: "latex", template_id: 1, template_name: "Standard", language: "de",
  context: { profile: true, document_ids: [], notes: "" }, content: "\\documentclass{article}\nline two\n\\end", status: "idle",
  error: null, compile_log: null, pdf_available: true, compiler_available: true, compiled_at: "2026-10-26T10:00:00Z",
  updated_at: "2026-10-26T10:00:00Z", messages: [], ...over,
});

let current: CoverLetterOut | null;

beforeEach(() => {
  setLocale("en");
  push.mockReset();
  get.mockReset();
  post.mockReset();
  put.mockReset();
  del.mockReset();
  leaveGuards.length = 0;
  current = letterOut();
  get.mockImplementation((async (path: string) => {
    if (path === "/applications/7/cover-letter") {
      if (current) return current;
      throw new ApiError(404, "cover_letter_not_found", {}, "nf");
    }
    return [];
  }) as never);
});
afterEach(() => {
  document.body.innerHTML = "";
});

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null;
/** The editor is kept alive (v-show) when switching to the PDF, so check visibility, not presence. */
const shown = (test: string) => { const el = q(`[data-test=${test}]`); return !!el && el.style.display !== "none"; };

async function mountView(plugin = vuetify) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(CoverLetterView, { id: "7" })) });
  const w = mount(Host, { global: { plugins: [pinia, plugin, i18n] }, attachTo: document.body });
  await flushPromises();
  // The editor is an async component (own chunk): wait until CodeMirror is there.
  if (q("[data-test=cl-editor]")) {
    await vi.waitFor(() => {
      if (!q("[data-test=cl-editor] .cm-editor")) throw new Error("editor not loaded yet");
    });
  }
  return w;
}

describe("CoverLetterView", () => {
  it("loads the letter, shows the PDF and the toggle for LaTeX", async () => {
    const w = await mountView();
    expect(get).toHaveBeenCalledWith("/applications/7/cover-letter");
    expect(q("[data-test=cl-view-toggle]")).not.toBeNull();
    const frame = q("[data-test=cl-pdf-frame]") as HTMLIFrameElement;
    expect(frame.getAttribute("src")).toBe("/api/applications/7/cover-letter/pdf?v=2026-10-26T10:00:00Z");
    expect(shown("cl-editor")).toBe(false);
    w.unmount();
  });

  it("starts in the TeX view without a PDF and switches with the toggle", async () => {
    current = letterOut({ pdf_available: false });
    const w = await mountView();
    expect(shown("cl-editor")).toBe(true);
    q("[data-test=cl-view-pdf]")!.click();
    await flushPromises();
    expect(shown("cl-editor")).toBe(false);
    expect(q("[data-test=cl-no-pdf]")).not.toBeNull();
    w.unmount();
  });

  it("has no toggle and no PDF for the text format", async () => {
    current = letterOut({ format: "text", content: "Dear Sir", pdf_available: false });
    const w = await mountView();
    expect(q("[data-test=cl-view-toggle]")).toBeNull();
    expect(q("[data-test=cl-pdf-frame]")).toBeNull();
    expect(shown("cl-editor")).toBe(true);
    expect(q("[data-test=cl-download]")!.textContent).toContain(".txt");
    w.unmount();
  });

  it("shows the compile log and a repair button on latex_failed", async () => {
    current = letterOut({ error: { code: "latex_failed", params: {}, detail: "x" }, compile_log: "! Undefined control sequence.", pdf_available: false });
    post.mockResolvedValue(letterOut({ status: "compiling" }));
    const w = await mountView();
    expect(q("[data-test=cl-error]")!.textContent).toContain("could not be compiled");
    expect(q("[data-test=cl-compile-log]")!.textContent).toContain("Undefined control sequence");
    q("[data-test=cl-repair]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/repair");
    useCoverLetterStore().stopPolling();
    w.unmount();
  });

  it("forces the TeX view and marks the line on latex_forbidden", async () => {
    current = letterOut({ error: { code: "latex_forbidden", params: { command: "\\input", line: 2 }, detail: "x" } });
    const w = await mountView();
    expect(q("[data-test=cl-error]")!.textContent).toContain("Line 2 uses \\input");
    expect(shown("cl-editor")).toBe(true);
    expect(document.body.querySelectorAll(".cm-line")[1]!.classList).toContain("tex-error-line");
    w.unmount();
  });

  it("offers the repair button on latex_forbidden too, without a compile log", async () => {
    current = letterOut({ error: { code: "latex_forbidden", params: { command: "\\input", line: 2 }, detail: "x" } });
    post.mockResolvedValue(letterOut({ status: "generating" }));
    const w = await mountView();
    expect(q("[data-test=cl-compile-log]")).toBeNull();
    const button = q("[data-test=cl-repair]")!;
    expect(button.classList).not.toContain("v-btn--disabled");
    button.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/repair");
    useCoverLetterStore().stopPolling();
    w.unmount();
  });

  it("has no repair button for other errors", async () => {
    current = letterOut({ error: { code: "latex_timeout", params: {}, detail: "x" } });
    const w = await mountView();
    expect(q("[data-test=cl-error]")).not.toBeNull();
    expect(q("[data-test=cl-repair]")).toBeNull();
    w.unmount();
  });

  it("with unsaved edits, repair, attach and download wait for saving", async () => {
    current = letterOut({ error: { code: "latex_failed", params: {}, detail: "x" }, compile_log: "! Error.", pdf_available: true });
    const w = await mountView();
    q("[data-test=cl-view-tex]")!.click();
    await flushPromises();
    await vi.waitFor(() => {
      if (!q("[data-test=cl-editor] .cm-editor")) throw new Error("editor not loaded yet");
    });
    expect(q("[data-test=cl-repair]")!.classList).not.toContain("v-btn--disabled");
    expect(q("[data-test=cl-repair-hint]")).toBeNull();
    const { EditorView } = await import("@codemirror/view");
    EditorView.findFromDOM(q("[data-test=cl-editor] .cm-editor")!)!.dispatch({ changes: { from: 0, insert: "% x\n" } });
    await flushPromises();
    for (const a of ["cl-repair", "cl-attach", "cl-download"]) {
      expect(q(`[data-test=${a}]`)!.classList, a).toContain("v-btn--disabled");
    }
    expect(q("[data-test=cl-repair-hint]")!.textContent).toContain("Save your changes first");
    expect(q("[data-test=cl-dirty-hint]")!.textContent).toContain("Save your changes first");
    // a second leave attempt cancels the first one still waiting
    const first = Promise.resolve(leaveGuards[0]!());
    const second = Promise.resolve(leaveGuards[0]!());
    expect(await first).toBe(false);
    await flushPromises();
    q("[data-test=cl-leave-dialog] [data-test=confirm-ok]")!.click();
    expect(await second).toBe(true);
    w.unmount();
  });

  it("locks editor, chat and actions while generating", async () => {
    current = letterOut({ status: "generating", pdf_available: false });
    const w = await mountView();
    expect(q("[data-test=cl-progress]")).not.toBeNull();
    expect(q("[data-test=cl-editor] .cm-content")!.getAttribute("contenteditable")).toBe("false");
    expect((q("[data-test=cl-chat-input] textarea") as HTMLTextAreaElement).disabled).toBe(true);
    for (const a of ["cl-save", "cl-attach", "cl-download", "cl-regenerate", "cl-delete"]) {
      expect(q(`[data-test=${a}]`)!.classList, a).toContain("v-btn--disabled");
    }
    useCoverLetterStore().stopPolling();
    w.unmount();
  });

  it("shows the streaming text read-only in the TeX editor and then the final letter", async () => {
    current = letterOut({ status: "generating", pdf_available: true });
    const w = await mountView();
    const store = useCoverLetterStore();
    store.streamText = "\\documentclass{article}\nDear";
    store.streamPhase = "revise";
    await flushPromises();
    await vi.waitFor(() => {
      if (!q("[data-test=cl-editor] .cm-editor")) throw new Error("editor not loaded yet");
    });
    expect(shown("cl-editor")).toBe(true);
    expect(q("[data-test=cl-pdf-frame]")).toBeNull();
    expect(q("[data-test=cl-editor] .cm-content")!.textContent).toContain("Dear");
    expect(q("[data-test=cl-editor] .cm-content")!.getAttribute("contenteditable")).toBe("false");
    expect(q("[data-test=cl-stream-status]")!.textContent).toBe("Revising…");
    expect(q("[data-test=cl-progress]")).not.toBeNull();
    expect(q("[data-test=cl-view-pdf]")!.classList).toContain("v-btn--disabled");
    expect((q("[data-test=cl-chat-input] textarea") as HTMLTextAreaElement).disabled).toBe(true);
    expect(q("[data-test=cl-repair]")).toBeNull();
    for (const a of ["cl-save", "cl-attach", "cl-download", "cl-regenerate", "cl-delete"]) {
      expect(q(`[data-test=${a}]`)!.classList, a).toContain("v-btn--disabled");
    }
    // the stream text is not a user edit
    expect(q("[data-test=cl-dirty-hint]")).toBeNull();

    store.streamPhase = "repair";
    await flushPromises();
    expect(q("[data-test=cl-stream-status]")!.textContent).toBe("Fixing the compile error…");

    // stream over: the store clears the text in the same tick as it sets the reloaded letter
    const cm = EditorView.findFromDOM(q("[data-test=cl-editor] .cm-editor")!)!;
    const docs: string[] = [];
    const dispatch = cm.dispatch.bind(cm);
    cm.dispatch = ((...args: Parameters<EditorView["dispatch"]>) => {
      dispatch(...args);
      docs.push(cm.state.doc.toString());
    }) as EditorView["dispatch"];
    store.letter = letterOut({ status: "generating", content: "\\documentclass{article}\nFinal letter", pdf_available: false });
    store.streamText = null;
    store.streamPhase = null;
    await flushPromises();
    expect(docs).not.toContain(letterOut().content); // never a frame with the old draft
    expect(q("[data-test=cl-stream-status]")).toBeNull();
    expect(q("[data-test=cl-editor] .cm-content")!.textContent).toContain("Final letter");
    expect(q("[data-test=cl-dirty-hint]")).toBeNull();
    store.letter = letterOut({ content: "\\documentclass{article}\nFinal letter", pdf_available: false });
    await flushPromises();
    expect(q("[data-test=cl-save]")!.classList).toContain("v-btn--disabled"); // not dirty
    store.stopPolling();
    w.unmount();
  });

  it("shows the streaming text in the text-format editor with the phase status", async () => {
    current = letterOut({ format: "text", status: "generating", content: "", pdf_available: false });
    const w = await mountView();
    const store = useCoverLetterStore();
    store.streamText = "Dear Sir";
    store.streamPhase = "generate";
    await flushPromises();
    expect(q("[data-test=cl-editor] .cm-content")!.textContent).toContain("Dear Sir");
    expect(q("[data-test=cl-stream-status]")!.textContent).toBe("Writing the cover letter…");
    store.stopPolling();
    w.unmount();
  });

  it("shows a hint with the README link without a compiler", async () => {
    current = letterOut({ compiler_available: false, pdf_available: false });
    const w = await mountView();
    const hint = q("[data-test=cl-no-compiler]")!;
    expect(hint.querySelector("a")!.getAttribute("href")).toBe("https://github.com/viktor-haag/ramen#pdf-tectonic");
    w.unmount();
  });

  it("saves only when there are unsaved changes", async () => {
    current = letterOut({ pdf_available: false });
    put.mockImplementation((async (_p: string, body: { content: string }) => letterOut({ content: body.content })) as never);
    const w = await mountView();
    expect(q("[data-test=cl-save]")!.classList).toContain("v-btn--disabled");
    const { EditorView } = await import("@codemirror/view");
    const view = EditorView.findFromDOM(q("[data-test=cl-editor] .cm-editor")!)!;
    view.dispatch({ changes: { from: 0, insert: "% x\n" } });
    await flushPromises();
    expect(q("[data-test=cl-save]")!.classList).not.toContain("v-btn--disabled");
    // leaving asks first; cancelling stays
    const leaving = Promise.resolve(leaveGuards[0]!());
    await flushPromises();
    expect(q("[data-test=cl-leave-dialog]")).not.toBeNull();
    q("[data-test=cl-leave-dialog] [data-test=confirm-cancel]")!.click();
    expect(await leaving).toBe(false);
    q("[data-test=cl-save]")!.click();
    await flushPromises();
    expect(put).toHaveBeenCalledWith("/applications/7/cover-letter/content", { content: `% x\n${letterOut().content}` });
    expect(q("[data-test=cl-save]")!.classList).toContain("v-btn--disabled");
    w.unmount();
  });

  it("sending a chat message calls send and clears the field", async () => {
    post.mockResolvedValue(letterOut());
    const w = await mountView();
    const ta = q("[data-test=cl-chat-input] textarea") as HTMLTextAreaElement;
    ta.value = "Shorter, please";
    ta.dispatchEvent(new Event("input"));
    await flushPromises();
    q("[data-test=cl-chat-send]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/messages", { text: "Shorter, please" });
    expect(ta.value).toBe("");
    // Shift+Enter is a line break, Enter sends
    ta.value = "Second";
    ta.dispatchEvent(new Event("input"));
    await flushPromises();
    ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }));
    ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true })); // Safari IME
    await flushPromises();
    expect(post).toHaveBeenCalledTimes(1);
    ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flushPromises();
    expect(post).toHaveBeenLastCalledWith("/applications/7/cover-letter/messages", { text: "Second" });
    w.unmount();
  });

  it("renders the chat history with user and assistant messages", async () => {
    current = letterOut({
      messages: [
        { id: 1, role: "user", text: "More formal", created_at: "2026-10-26T10:00:00Z" },
        { id: 2, role: "assistant", text: "Made it more formal.", created_at: "2026-10-26T10:00:05Z" },
      ],
    });
    const w = await mountView();
    expect(q("[data-test=cl-msg-user]")!.textContent).toContain("More formal");
    expect(q("[data-test=cl-msg-assistant]")!.textContent).toContain("Made it more formal.");
    w.unmount();
  });

  it("attaches with the UI language", async () => {
    setLocale("de");
    post.mockResolvedValue({});
    const w = await mountView();
    q("[data-test=cl-attach]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/attach?lang=de");
    expect(q("[data-test=cl-download]")!.getAttribute("href")).toBe("/api/applications/7/cover-letter/source?lang=de");
    w.unmount();
  });

  it("does not render another application's letter", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useCoverLetterStore().letter = letterOut({ application_id: 99, content: "foreign" });
    get.mockImplementation((() => new Promise(() => undefined)) as never);
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(CoverLetterView, { id: "7" })) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    expect(document.body.textContent).not.toContain("foreign");
    expect(shown("cl-editor")).toBe(false);
    w.unmount();
  });

  it("shows an 'open PDF' button instead of the frame on narrow screens", async () => {
    const width = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 500 });
    const narrow = createVuetify({ components, directives });
    const w = await mountView(narrow);
    expect(q("[data-test=cl-pdf-frame]")).toBeNull();
    const btn = q("[data-test=cl-open-pdf]")!;
    expect(btn.getAttribute("href")).toBe("/api/applications/7/cover-letter/pdf?v=2026-10-26T10:00:00Z");
    expect(btn.getAttribute("target")).toBe("_blank");
    w.unmount();
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  });

  it("stops polling on unmount", async () => {
    const w = await mountView();
    const stop = vi.spyOn(useCoverLetterStore(), "stopPolling");
    w.unmount();
    expect(stop).toHaveBeenCalled();
  });

  it("deletes after confirming and goes back to the application", async () => {
    del.mockResolvedValue(undefined);
    const w = await mountView();
    q("[data-test=cl-delete]")!.click();
    await flushPromises();
    q("[data-test=confirm-ok]")!.click();
    await flushPromises();
    expect(del).toHaveBeenCalledWith("/applications/7/cover-letter");
    expect(push).toHaveBeenCalledWith({ name: "application", params: { id: "7" } });
    w.unmount();
  });
});
