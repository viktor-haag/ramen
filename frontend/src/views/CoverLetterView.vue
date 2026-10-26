<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from "vue-router";
import { useDisplay, useTheme } from "vuetify";
import { ApiError, BASE, toQuery } from "@/api/client";
import type { CoverLetterOut } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import CoverLetterChat from "@/components/CoverLetterChat.vue";
import CoverLetterDialog from "@/components/CoverLetterDialog.vue";
import { errorMessage } from "@/i18n";
import { pdfUrl, useCoverLetterStore } from "@/stores/coverLetter";
import { useNotifyStore } from "@/stores/notify";

// CodeMirror is only loaded with the editor (own chunk).
const TexEditor = defineAsyncComponent(() => import("@/components/TexEditor.vue"));

const README_TECTONIC = "https://github.com/viktor-haag/ramen#pdf-tectonic";

const props = defineProps<{ id: string }>();
const { t, locale } = useI18n();
const router = useRouter();
const store = useCoverLetterStore();
const notify = useNotifyStore();
const theme = useTheme();
const { smAndDown } = useDisplay();

const appId = computed(() => Number(props.id));
// The store keeps the previous application's letter while the next one loads: only show our own.
const letter = computed<CoverLetterOut | null>(() => (store.letter?.application_id === appId.value ? store.letter : null));
const busy = computed(() => letter.value !== null && letter.value.status !== "idle");
const latex = computed(() => letter.value?.format === "latex");
const dark = computed(() => theme.global.current.value.dark);
const uiLang = computed<"de" | "en">(() => (locale.value === "de" ? "de" : "en"));

// --- draft: the editor content; `saved` is the server content it is compared with ---
const draft = ref("");
const saved = ref("");
const dirty = computed(() => letter.value !== null && draft.value !== saved.value);

watch(
  () => letter.value?.content,
  (c) => {
    if (c === undefined) return;
    // A new server version replaces the draft unless the user has edits of their own.
    if (draft.value === saved.value || draft.value === c) draft.value = c;
    saved.value = c;
  },
  { immediate: true },
);

function discardDraft() {
  if (letter.value) draft.value = saved.value = letter.value.content;
}

watch(
  appId,
  (id) => {
    draft.value = saved.value = "";
    userMode.value = null;
    void store.load(id);
  },
  { flush: "sync" },
);
onMounted(() => void store.load(appId.value));
onBeforeUnmount(() => store.stopPolling());

// --- error of the last run ---
const error = computed(() => {
  const e = letter.value?.error as { code?: unknown; params?: unknown; detail?: unknown } | null | undefined;
  if (!e || busy.value) return null;
  const code = typeof e.code === "string" ? e.code : null;
  const params = e.params && typeof e.params === "object" ? (e.params as Record<string, unknown>) : {};
  return { code, params, text: errorMessage(new ApiError(0, code, params, e.detail ?? "")) };
});
const noCompiler = computed(() => latex.value && letter.value?.compiler_available === false);
/** The missing-compiler hint already says it all. */
const showError = computed(() => !!error.value && !(noCompiler.value && error.value.code === "latex_unavailable"));
const forbiddenLine = computed(() => {
  if (error.value?.code !== "latex_forbidden") return null;
  const line = Number(error.value.params.line);
  return Number.isInteger(line) && line > 0 ? line : null;
});

// --- PDF / TeX ---
type Mode = "pdf" | "tex";
/** The user's choice; until then the PDF is shown whenever there is one. */
const userMode = ref<Mode | null>(null);
const mode = computed<Mode>(() => {
  if (!latex.value || error.value?.code === "latex_forbidden") return "tex";
  return userMode.value ?? (letter.value?.pdf_available ? "pdf" : "tex");
});
// Editing fixes the current view: a PDF that appears after saving must not pull the user out of the editor.
watch(dirty, (d) => d && userMode.value === null && (userMode.value = mode.value));
/** The editor stays mounted once shown, so switching to the PDF keeps the undo history. */
const editorUsed = ref(false);
watch(mode, (m) => m === "tex" && (editorUsed.value = true), { immediate: true });
const pdfSrc = computed(() => (letter.value ? pdfUrl(appId.value, letter.value.compiled_at) : ""));
const sourceUrl = computed(() => `${BASE}/applications/${appId.value}/cover-letter/source?${toQuery({ lang: uiLang.value })}`);

// --- actions ---
const saving = ref(false);
async function save() {
  if (!dirty.value || busy.value) return;
  saving.value = true;
  try {
    await store.saveContent(appId.value, draft.value);
  } finally {
    saving.value = false;
  }
}

const repairing = ref(false);
async function repair() {
  repairing.value = true;
  try {
    await store.repair(appId.value);
  } finally {
    repairing.value = false;
  }
}

const sendMessage = (text: string) => store.send(appId.value, text);

const attaching = ref(false);
async function attach() {
  attaching.value = true;
  try {
    if (await store.attach(appId.value, uiLang.value)) notify.show(t("coverLetter.view.attached"), "success");
  } finally {
    attaching.value = false;
  }
}

const regenerating = ref(false);
const deleting = ref(false);
const deleteBusy = ref(false);
async function remove() {
  deleteBusy.value = true;
  try {
    if (!(await store.remove(appId.value))) return;
    deleting.value = false;
    draft.value = saved.value = "";
    await router.push({ name: "application", params: { id: props.id } });
  } finally {
    deleteBusy.value = false;
  }
}
function back() {
  void router.push({ name: "application", params: { id: props.id } });
}

// --- leaving with unsaved changes ---
const leaving = ref(false);
let answerLeave: ((ok: boolean) => void) | null = null;
function confirmLeave(): boolean | Promise<boolean> {
  if (!dirty.value) return true;
  answerLeave?.(false); // an earlier navigation still waiting is cancelled
  leaving.value = true;
  return new Promise((resolve) => (answerLeave = resolve));
}
function answer(ok: boolean) {
  leaving.value = false;
  answerLeave?.(ok);
  answerLeave = null;
}
onBeforeRouteLeave(confirmLeave);
onBeforeRouteUpdate(confirmLeave);
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!dirty.value) return;
  e.preventDefault();
  e.returnValue = "";
}
onMounted(() => window.addEventListener("beforeunload", onBeforeUnload));
onBeforeUnmount(() => window.removeEventListener("beforeunload", onBeforeUnload));
</script>

<template>
  <div data-test="cover-letter-view">
    <div class="d-flex align-center flex-wrap ga-2 mb-2">
      <v-btn variant="text" prepend-icon="mdi-arrow-left" data-test="cl-back" @click="back">{{ t("coverLetter.view.back") }}</v-btn>
      <h1 class="text-h5 flex-grow-1">{{ t("coverLetter.section") }}</h1>
    </div>

    <div v-if="!letter" class="text-body-2 text-medium-emphasis" data-test="cl-view-none">
      {{ store.loading ? t("common.loading") : t("coverLetter.none") }}
    </div>

    <template v-else>
      <div class="d-flex align-center flex-wrap ga-2 mb-2" data-test="cl-actions">
        <v-btn-toggle
          v-if="latex"
          :model-value="mode"
          mandatory
          density="comfortable"
          color="primary"
          data-test="cl-view-toggle"
          @update:model-value="(m: Mode) => (userMode = m)"
        >
          <v-btn value="pdf" prepend-icon="mdi-file-pdf-box" :disabled="forbiddenLine !== null" data-test="cl-view-pdf">{{ t("coverLetter.view.pdf") }}</v-btn>
          <v-btn value="tex" prepend-icon="mdi-code-braces" data-test="cl-view-tex">{{ t("coverLetter.view.tex") }}</v-btn>
        </v-btn-toggle>
        <v-spacer />
        <v-btn
          v-if="mode === 'tex'"
          color="primary"
          variant="flat"
          prepend-icon="mdi-content-save"
          :disabled="!dirty || busy"
          :loading="saving"
          data-test="cl-save"
          @click="save"
        >
          {{ latex ? t("coverLetter.view.saveCompile") : t("common.save") }}
        </v-btn>
        <v-btn
          variant="tonal"
          prepend-icon="mdi-paperclip"
          :disabled="busy || dirty || (latex && !letter.pdf_available)"
          :loading="attaching"
          data-test="cl-attach"
          @click="attach"
        >
          {{ t("coverLetter.view.attach") }}
        </v-btn>
        <v-btn variant="tonal" prepend-icon="mdi-download" :href="sourceUrl" download :disabled="busy || dirty" data-test="cl-download">
          {{ latex ? t("coverLetter.view.downloadTex") : t("coverLetter.view.downloadTxt") }}
        </v-btn>
        <v-btn variant="text" prepend-icon="mdi-refresh" :disabled="busy" data-test="cl-regenerate" @click="regenerating = true">
          {{ t("coverLetter.dialog.regenerate") }}
        </v-btn>
        <v-btn variant="text" color="error" prepend-icon="mdi-delete" :disabled="busy" data-test="cl-delete" @click="deleting = true">
          {{ t("common.delete") }}
        </v-btn>
      </div>
      <!-- Attach, download and repair work on the saved version, which differs from the editor. -->
      <div v-if="dirty" class="text-caption text-medium-emphasis mb-2" data-test="cl-dirty-hint">{{ t("coverLetter.chat.saveFirst") }}</div>

      <div v-if="busy" class="mb-2" data-test="cl-busy">
        <v-progress-linear indeterminate color="primary" data-test="cl-progress" />
        <div class="text-body-2 text-medium-emphasis mt-1">{{ t(`coverLetter.status.${letter.status}`) }}</div>
      </div>

      <v-alert v-if="noCompiler" type="info" variant="tonal" density="compact" class="mb-2" data-test="cl-no-compiler">
        {{ t("coverLetter.view.noCompiler") }}
        <a :href="README_TECTONIC" target="_blank" rel="noopener noreferrer">{{ t("coverLetter.view.noCompilerLink") }}</a>
      </v-alert>

      <v-alert v-if="showError && error" type="error" variant="tonal" density="compact" class="mb-2" data-test="cl-error">
        <div>{{ error.text }}</div>
        <template v-if="error.code === 'latex_failed'">
          <pre v-if="letter.compile_log" class="cl-log mt-2" data-test="cl-compile-log">{{ letter.compile_log }}</pre>
          <v-btn class="mt-2" size="small" variant="flat" color="error" prepend-icon="mdi-auto-fix" :disabled="dirty" :loading="repairing" data-test="cl-repair" @click="repair">
            {{ t("coverLetter.view.repair") }}
          </v-btn>
          <div v-if="dirty" class="text-caption mt-1" data-test="cl-repair-hint">{{ t("coverLetter.chat.saveFirst") }}</div>
        </template>
      </v-alert>

      <v-row>
        <v-col cols="12" md="8">
          <template v-if="mode === 'pdf'">
            <template v-if="letter.pdf_available">
              <v-btn
                v-if="smAndDown"
                color="primary"
                variant="tonal"
                prepend-icon="mdi-open-in-new"
                :href="pdfSrc"
                target="_blank"
                rel="noopener"
                data-test="cl-open-pdf"
              >
                {{ t("coverLetter.view.openPdf") }}
              </v-btn>
              <iframe v-else :src="pdfSrc" class="cl-pane cl-pdf" :title="t('coverLetter.view.pdf')" data-test="cl-pdf-frame" />
            </template>
            <div v-else class="text-body-2 text-medium-emphasis" data-test="cl-no-pdf">{{ t("coverLetter.view.noPdf") }}</div>
          </template>
          <div v-if="editorUsed" v-show="mode === 'tex'" class="cl-pane" data-test="cl-editor">
            <TexEditor v-model="draft" :language="letter.format" :disabled="busy" :highlight-line="forbiddenLine" :dark="dark" />
          </div>
        </v-col>
        <v-col cols="12" md="4">
          <CoverLetterChat
            :messages="letter.messages"
            :disabled="busy || dirty"
            :hint="dirty ? t('coverLetter.chat.saveFirst') : null"
            :submit="sendMessage"
          />
        </v-col>
      </v-row>
    </template>

    <CoverLetterDialog v-if="regenerating" v-model="regenerating" :application-id="appId" :existing="letter" @created="discardDraft" />
    <ConfirmDialog
      v-model="deleting"
      :title="t('coverLetter.view.deleteTitle')"
      :text="t('coverLetter.view.deleteText')"
      :busy="deleteBusy"
      data-test="cl-delete-dialog"
      @confirm="remove"
    />
    <ConfirmDialog
      :model-value="leaving"
      :title="t('coverLetter.view.leaveTitle')"
      :text="t('coverLetter.view.leaveText')"
      :ok-label="t('coverLetter.view.leaveOk')"
      data-test="cl-leave-dialog"
      @update:model-value="(v: boolean) => !v && answer(false)"
      @confirm="answer(true)"
    />
  </div>
</template>

<style scoped>
.cl-pane {
  height: calc(100vh - 260px);
  min-height: 480px;
}
.cl-pdf {
  width: 100%;
  border: 1px solid rgb(var(--v-theme-border-subtle));
  border-radius: 4px;
  background: #fff;
}
.cl-log {
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
  background: rgba(var(--v-theme-on-surface), 0.05);
  padding: 8px;
  border-radius: 4px;
}
</style>
