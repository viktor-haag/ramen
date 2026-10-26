import { EditorView } from "@codemirror/view";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TexEditor from "@/components/TexEditor.vue";

const DOC = "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}";

function mountEditor(props: Partial<InstanceType<typeof TexEditor>["$props"]> = {}) {
  return mount(TexEditor, {
    props: { modelValue: DOC, language: "latex", dark: false, ...props },
    attachTo: document.body,
  });
}

function viewOf(w: ReturnType<typeof mountEditor>): EditorView {
  const view = EditorView.findFromDOM(w.find(".cm-editor").element as HTMLElement);
  if (!view) throw new Error("no editor view");
  return view;
}

describe("TexEditor", () => {
  it("renders the content", () => {
    const w = mountEditor();
    expect(w.find(".cm-content").text()).toContain("\\begin{document}");
    expect(viewOf(w).state.doc.toString()).toBe(DOC);
    w.unmount();
  });

  it("emits update:modelValue on input", () => {
    const w = mountEditor();
    const view = viewOf(w);
    view.dispatch({ changes: { from: view.state.doc.length, insert: "\n%" } });
    expect(w.emitted("update:modelValue")?.at(-1)).toEqual([`${DOC}\n%`]);
    w.unmount();
  });

  it("replaces the content when modelValue changes from outside, but not for its own echo", async () => {
    const w = mountEditor();
    const view = viewOf(w);
    view.dispatch({ changes: { from: 0, insert: "% a\n" } });
    view.dispatch({ selection: { anchor: 2 } });
    await w.setProps({ modelValue: `% a\n${DOC}` });
    expect(view.state.selection.main.anchor).toBe(2); // the echo did not reset the document
    await w.setProps({ modelValue: "other" });
    expect(view.state.doc.toString()).toBe("other");
    w.unmount();
  });

  it("disabled makes the editor read-only", async () => {
    const w = mountEditor({ disabled: true });
    expect(w.find(".cm-content").attributes("contenteditable")).toBe("false");
    await w.setProps({ disabled: false });
    expect(w.find(".cm-content").attributes("contenteditable")).toBe("true");
    w.unmount();
  });

  it("highlightLine marks that line", async () => {
    const w = mountEditor({ highlightLine: 2 });
    await flushPromises();
    const lines = w.findAll(".cm-line");
    expect(lines[1]!.classes()).toContain("tex-error-line");
    expect(w.findAll(".tex-error-line")).toHaveLength(1);
    await w.setProps({ highlightLine: null });
    expect(w.findAll(".tex-error-line")).toHaveLength(0);
    w.unmount();
  });

  it("uses the stex mode only for latex", () => {
    const tex = mountEditor();
    expect(tex.find(".cm-content").attributes("data-language")).toBe("stex");
    tex.unmount();
    const txt = mountEditor({ language: "text", modelValue: "Dear Sir" });
    expect(txt.find(".cm-content").attributes("data-language")).toBeUndefined();
    txt.unmount();
  });

  it("switches to the dark theme", async () => {
    const w = mountEditor({ dark: true });
    expect(viewOf(w).state.facet(EditorView.darkTheme)).toBe(true);
    await w.setProps({ dark: false });
    expect(viewOf(w).state.facet(EditorView.darkTheme)).toBe(false);
    w.unmount();
  });

  it("uses the ramenLight theme in light mode", () => {
    const w = mountEditor({ dark: false });
    const css = [...document.querySelectorAll("style")].map((x) => x.textContent ?? "").join("\n").toLowerCase();
    // the caret colour of the light theme (ramenLight primary) is registered for the editor
    expect(css).toMatch(/caret-color: ?#c45220/);
    w.unmount();
  });
});
