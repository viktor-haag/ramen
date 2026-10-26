import { undo } from "@codemirror/commands";
import { EditorView } from "@codemirror/view";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
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

  it("a locked editor swallows clicks on the text: no cursor, no focus; scrolling still works", async () => {
    const w = mountEditor({ disabled: true, followEnd: true });
    const view = viewOf(w);
    const before = view.state.selection.main.anchor;
    const line = w.find(".cm-line").element;
    for (const type of ["mousedown", "dblclick", "contextmenu"]) {
      const ev = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0 });
      line.dispatchEvent(ev);
      expect(ev.defaultPrevented, type).toBe(true);
    }
    expect(view.state.selection.main.anchor).toBe(before);
    expect(view.hasFocus).toBe(false);
    expect(w.find(".cm-editor").classes()).toContain("tex-locked");
    // a press on the scroll container itself (scrollbar) is not swallowed
    const onScroller = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    view.scrollDOM.dispatchEvent(onScroller);
    expect(onScroller.defaultPrevented).toBe(false);
    w.unmount();
  });

  it("locking drops the focus, unlocking makes the text clickable again", async () => {
    const w = mountEditor();
    const view = viewOf(w);
    view.focus();
    expect(view.hasFocus).toBe(true);
    await w.setProps({ disabled: true });
    expect(view.hasFocus).toBe(false);
    await w.setProps({ disabled: false });
    const ev = new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 });
    w.find(".cm-line").element.dispatchEvent(ev);
    expect(w.find(".cm-editor").classes()).not.toContain("tex-locked");
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

  describe("followEnd", () => {
    /** Calls of EditorView.scrollIntoView that target the document end. */
    function endScrolls(spy: { mock: { calls: readonly (readonly unknown[])[] } }, view: EditorView) {
      return spy.mock.calls.filter((c) => c[0] === view.state.doc.length).length;
    }
    function setScroll(el: HTMLElement, m: { top: number; height: number; client: number }) {
      Object.defineProperty(el, "scrollHeight", { configurable: true, value: m.height });
      Object.defineProperty(el, "clientHeight", { configurable: true, value: m.client });
      el.scrollTop = m.top;
      Object.defineProperty(el, "scrollTop", { configurable: true, writable: true, value: m.top });
      el.dispatchEvent(new Event("scroll"));
    }

    it("scrolls to the end when the content grows", async () => {
      const spy = vi.spyOn(EditorView, "scrollIntoView");
      const w = mountEditor({ modelValue: "a", disabled: true, followEnd: true });
      const view = viewOf(w);
      spy.mockClear();
      await w.setProps({ modelValue: "a\nb" });
      expect(endScrolls(spy, view)).toBe(1);
      spy.mockClear();
      await w.setProps({ modelValue: "a\nb\nc" });
      expect(endScrolls(spy, view)).toBe(1);
      spy.mockRestore();
      w.unmount();
    });

    it("does not scroll without followEnd", async () => {
      const spy = vi.spyOn(EditorView, "scrollIntoView");
      const w = mountEditor({ modelValue: "a" });
      const view = viewOf(w);
      await w.setProps({ modelValue: "a\nb" });
      expect(endScrolls(spy, view)).toBe(0);
      spy.mockRestore();
      w.unmount();
    });

    it("stops following after the user scrolls up and resumes at the bottom", async () => {
      const spy = vi.spyOn(EditorView, "scrollIntoView");
      const w = mountEditor({ modelValue: "a", disabled: true, followEnd: true });
      const view = viewOf(w);
      spy.mockClear();
      setScroll(view.scrollDOM, { top: 800, height: 1000, client: 200 }); // at the bottom
      setScroll(view.scrollDOM, { top: 100, height: 1000, client: 200 }); // user scrolled up
      await w.setProps({ modelValue: "a\nb" });
      expect(endScrolls(spy, view)).toBe(0);
      setScroll(view.scrollDOM, { top: 800, height: 1000, client: 200 }); // back at the bottom
      await w.setProps({ modelValue: "a\nb\nc" });
      expect(endScrolls(spy, view)).toBe(1);
      spy.mockRestore();
      w.unmount();
    });

    it("keeps following when a scroll away from the bottom did not go up", async () => {
      const spy = vi.spyOn(EditorView, "scrollIntoView");
      const w = mountEditor({ modelValue: "a", disabled: true, followEnd: true });
      const view = viewOf(w);
      setScroll(view.scrollDOM, { top: 100, height: 1000, client: 200 });
      setScroll(view.scrollDOM, { top: 300, height: 1000, client: 200 }); // moving down, content grew below
      spy.mockClear();
      await w.setProps({ modelValue: "a\nb" });
      expect(endScrolls(spy, view)).toBe(1);
      spy.mockRestore();
      w.unmount();
    });
  });

  it("outside replacements are not undoable", async () => {
    const w = mountEditor({ modelValue: "a" });
    const view = viewOf(w);
    await w.setProps({ modelValue: "a b" });
    await w.setProps({ modelValue: "a b c" });
    undo(view);
    expect(view.state.doc.toString()).toBe("a b c");
    w.unmount();
  });

  it("appends only the tail when the new value extends the document", async () => {
    const w = mountEditor({ modelValue: "Hello" });
    const view = viewOf(w);
    view.dispatch({ selection: { anchor: 2 } });
    await w.setProps({ modelValue: "Hello world" });
    expect(view.state.doc.toString()).toBe("Hello world");
    expect(view.state.selection.main.anchor).toBe(2); // a full replacement would have moved it
    await w.setProps({ modelValue: "Bye" });
    expect(view.state.doc.toString()).toBe("Bye");
    w.unmount();
  });
});
