<script setup lang="ts">
import { basicSetup } from "codemirror";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import { Compartment, EditorState, RangeSetBuilder, StateEffect, StateField, type Extension } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{ modelValue: string; language: "latex" | "text"; disabled?: boolean; highlightLine?: number | null; dark: boolean }>();
const emit = defineEmits<{ "update:modelValue": [string] }>();

const host = ref<HTMLElement | null>(null);
let view: EditorView | null = null;

const languageConf = new Compartment();
const editableConf = new Compartment();
const themeConf = new Compartment();

// --- line marker (e.g. the line of a forbidden command) ---
const setMarkedLine = StateEffect.define<number | null>();
const errorLine = Decoration.line({ class: "tex-error-line" });

function lineDecorations(state: EditorState, line: number | null): DecorationSet {
  if (line == null || line < 1 || line > state.doc.lines) return Decoration.none;
  const b = new RangeSetBuilder<Decoration>();
  const at = state.doc.line(line).from;
  b.add(at, at, errorLine);
  return b.finish();
}

const markedLine = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    for (const e of tr.effects) if (e.is(setMarkedLine)) return lineDecorations(tr.state, e.value);
    return deco.map(tr.changes);
  },
  provide: (f) => EditorView.decorations.from(f),
});

// --- themes: the colours of ramenLight / ramenDark (plugins/vuetify.ts) ---
const base = EditorView.theme({
  "&": { height: "100%", fontSize: "14px" },
  ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", overflow: "auto" },
  ".tex-error-line": { backgroundColor: "rgba(179, 56, 44, 0.18)" },
});

const darkTheme: Extension = [
  EditorView.theme(
    {
      "&": { backgroundColor: "#1E2638", color: "#E8E2D8" },
      ".cm-content": { caretColor: "#EC804C" },
      ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#EC804C" },
      "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
        backgroundColor: "#3A4560",
      },
      ".cm-gutters": { backgroundColor: "#1A2132", color: "#8E99B3", borderRight: "1px solid #2B3449" },
      ".cm-activeLine": { backgroundColor: "#2A334966" },
      ".cm-activeLineGutter": { backgroundColor: "#2A3349" },
      ".cm-matchingBracket, .cm-nonmatchingBracket": { backgroundColor: "#46506A", outline: "none" },
      ".cm-searchMatch": { backgroundColor: "#F0A86040" },
      ".cm-panels": { backgroundColor: "#1A2132", color: "#E8E2D8" },
      ".cm-tooltip": { backgroundColor: "#1A2132", border: "1px solid #2B3449" },
      ".tex-error-line": { backgroundColor: "rgba(232, 131, 122, 0.22)" },
    },
    { dark: true },
  ),
  syntaxHighlighting(
    HighlightStyle.define([
      { tag: tags.tagName, color: "#F2A57E" },
      { tag: tags.keyword, color: "#EC804C", fontWeight: "bold" },
      { tag: [tags.atom, tags.number], color: "#8FB3E0" },
      { tag: tags.special(tags.variableName), color: "#8DBB6E" },
      { tag: [tags.string, tags.bracket], color: "#F6DCC6" },
      { tag: tags.comment, color: "#8E99B3", fontStyle: "italic" },
      { tag: tags.invalid, color: "#E8837A" },
    ]),
  ),
];

const languageExt = () => (props.language === "latex" ? StreamLanguage.define(stex) : []);
const editableExt = () => [EditorView.editable.of(!props.disabled), EditorState.readOnly.of(!!props.disabled)];

onMounted(() => {
  view = new EditorView({
    parent: host.value!,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        basicSetup,
        EditorView.lineWrapping,
        base,
        markedLine,
        languageConf.of(languageExt()),
        editableConf.of(editableExt()),
        themeConf.of(props.dark ? darkTheme : []),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) emit("update:modelValue", u.state.doc.toString());
        }),
      ],
    }),
  });
  markLine(props.highlightLine ?? null);
});

onBeforeUnmount(() => {
  view?.destroy();
  view = null;
});

function markLine(line: number | null) {
  if (!view) return;
  const effects: StateEffect<unknown>[] = [setMarkedLine.of(line)];
  if (line != null && line >= 1 && line <= view.state.doc.lines) {
    effects.push(EditorView.scrollIntoView(view.state.doc.line(line).from, { y: "center" }));
  }
  view.dispatch({ effects });
}

// Only an outside change replaces the document; the echo of our own update is equal and skipped.
watch(
  () => props.modelValue,
  (v) => {
    if (!view || v === view.state.doc.toString()) return;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } });
    markLine(props.highlightLine ?? null);
  },
);
watch(() => props.language, () => view?.dispatch({ effects: languageConf.reconfigure(languageExt()) }));
watch(() => props.disabled, () => view?.dispatch({ effects: editableConf.reconfigure(editableExt()) }));
watch(() => props.dark, (d) => view?.dispatch({ effects: themeConf.reconfigure(d ? darkTheme : []) }));
watch(() => props.highlightLine, (l) => markLine(l ?? null));
</script>

<template>
  <div ref="host" class="tex-editor" data-test="tex-editor" />
</template>

<style scoped>
.tex-editor {
  height: 100%;
  border: 1px solid rgb(var(--v-theme-border-subtle));
  border-radius: 4px;
  overflow: hidden;
}
</style>
