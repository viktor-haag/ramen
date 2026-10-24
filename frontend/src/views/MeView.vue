<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { useI18n } from "vue-i18n";
import { FREE_TEXT_MAX } from "@/api/types";
import { formatDateTime } from "@/domain/time";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import DocumentList from "@/components/DocumentList.vue";
import MarkdownEditor from "@/components/MarkdownEditor.vue";
import { useMeStore } from "@/stores/me";
import { useNotifyStore } from "@/stores/notify";

const { t, locale } = useI18n();
const store = useMeStore();
const notify = useNotifyStore();

onMounted(() => {
  window.addEventListener("beforeunload", onBeforeUnload);
  void store.load();
});
onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", onBeforeUnload);
  void flush(); // the store outlives the view: pending edits are still saved
});
onBeforeRouteLeave(async () => {
  await flush();
});

const profileCfg = computed(() => store.profileConfig);

// --- free text (autosave on blur) ---
const freeText = ref("");
const freeTextError = ref("");
/** The text of a save in flight: a server value must not overwrite what was typed meanwhile. */
let sentFreeText: string | null = null;
watch(
  () => store.profile?.free_text,
  (v) => {
    if (sentFreeText !== null && freeText.value !== sentFreeText) return;
    freeText.value = v ?? "";
  },
  { immediate: true },
);
/** `announce`: also tell via snackbar when the text is too long (leaving the page, generating). */
async function saveFreeText(announce = false) {
  if (freeText.value.length > FREE_TEXT_MAX) {
    const max = FREE_TEXT_MAX.toLocaleString(locale.value);
    freeTextError.value = t("me.freeText.tooLong", { max });
    if (announce) notify.show(t("me.freeText.notSaved", { max }));
    return;
  }
  const sent = freeText.value;
  sentFreeText = sent;
  try {
    const res = await store.saveFreeText(sent);
    freeTextError.value = res.ok ? "" : (res.errors.free_text ?? "");
    await nextTick(); // the store value is applied to the field by the watcher before the guard is lifted
  } finally {
    if (sentFreeText === sent) sentFreeText = null;
  }
}

// --- profile markdown (autosave on blur) ---
const markdown = ref("");
let sentMarkdown: string | null = null; // see sentFreeText
watch(
  () => store.profile?.profile_markdown,
  (v) => {
    if (sentMarkdown !== null && markdown.value !== sentMarkdown) return;
    markdown.value = v ?? "";
  },
  { immediate: true },
);
async function saveMarkdown() {
  const sent = markdown.value;
  sentMarkdown = sent;
  try {
    const res = await store.saveMarkdown(sent);
    await nextTick();
    return res;
  } finally {
    if (sentMarkdown === sent) sentMarkdown = null;
  }
}

// --- unsaved edits ---
const dirty = computed(
  () => (freeText.value || null) !== (store.profile?.free_text || null) || markdown.value !== (store.profile?.profile_markdown ?? ""),
);
/** Save both editors and wait until nothing is in flight. */
async function flush() {
  await store.settled();
  await Promise.all([saveFreeText(true), saveMarkdown()]);
  await store.settled();
}
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!dirty.value) return;
  e.preventDefault();
  e.returnValue = "";
}

// --- profile generation ---
const confirmOverwrite = ref(false);
const hasProfile = computed(() => !!store.profile?.profile_markdown);
const noInputs = computed(() => (store.profile?.documents_used ?? 0) === 0 && !store.profile?.free_text);
const starting = ref(false); // between the click and the request: a second click must not start another flush/request
const canGenerate = computed(() => profileCfg.value !== null && !noInputs.value && !store.generating && !starting.value);
async function onGenerate() {
  if (store.generating || starting.value) return;
  starting.value = true;
  try {
    await flush(); // a pending markdown edit must count as "edited" before we decide whether to ask
    if (dirty.value) return; // a failed save must never be overwritten by the generated profile
    if (store.profile?.edited_since_generation) confirmOverwrite.value = true;
    else void store.generate(false);
  } finally {
    starting.value = false;
  }
}
async function onConfirmOverwrite() {
  confirmOverwrite.value = false;
  await store.generate(true);
}
</script>

<template>
  <div>
    <h1 class="text-h5 mb-4">{{ t("me.title") }}</h1>

    <v-alert type="info" variant="tonal" class="mb-6" data-test="provider-notice">
      <template v-if="profileCfg">
        <div>{{ t("me.notice.profile", { provider: store.providerName }) }}</div>
        <div v-if="store.extractionProviderName">{{ t("me.notice.extraction", { provider: store.extractionProviderName }) }}</div>
      </template>
      <template v-else>{{ t("me.notice.none") }}</template>
    </v-alert>

    <h2 class="text-h6 mb-2">{{ t("me.documents.title") }}</h2>
    <DocumentList class="mb-6" />

    <h2 class="text-h6 mb-2">{{ t("me.freeText.title") }}</h2>
    <v-textarea
      v-model="freeText"
      :label="t('me.freeText.label')"
      :hint="t('me.freeText.hint')"
      :counter="FREE_TEXT_MAX"
      :error-messages="freeTextError"
      :disabled="store.generating"
      auto-grow
      rows="4"
      variant="outlined"
      class="mb-4"
      data-test="free-text"
      @blur="saveFreeText()"
    />

    <h2 class="text-h6 mb-2">{{ t("me.profile.title") }}</h2>
    <v-alert v-if="store.profile?.inputs_changed_since_generation && hasProfile" type="warning" variant="tonal" class="mb-3" data-test="inputs-changed">
      {{ t("me.profile.inputsChanged") }}
    </v-alert>
    <v-alert v-if="store.limitExceeded" type="warning" variant="tonal" class="mb-3" data-test="limit-warning">
      {{ t("me.limitExceeded") }}
    </v-alert>
    <div class="d-flex align-center ga-4 flex-wrap mb-3">
      <v-btn
        color="primary"
        prepend-icon="mdi-auto-fix"
        :disabled="!canGenerate"
        :loading="store.generating"
        data-test="generate"
        @click="onGenerate"
      >
        {{ hasProfile ? t("me.profile.recreate") : t("me.profile.create") }}
      </v-btn>
      <span class="text-body-2 text-medium-emphasis" data-test="generate-counts">
        {{ t("me.profile.used", { n: store.profile?.documents_used ?? 0 }, store.profile?.documents_used ?? 0) }}
        <template v-if="(store.profile?.documents_unused ?? 0) > 0">, {{ t("me.profile.unused", { n: store.profile?.documents_unused ?? 0 }) }}</template>
      </span>
      <span v-if="store.profile?.generated_at" class="text-body-2 text-medium-emphasis">
        {{ t("me.profile.generatedAt", { date: formatDateTime(store.profile.generated_at, locale) }) }}
      </span>
      <v-chip v-if="store.profile?.edited_since_generation" size="small" label variant="tonal" data-test="edited-chip">{{ t("me.profile.edited") }}</v-chip>
    </div>
    <MarkdownEditor v-model="markdown" :disabled="store.generating" @save="saveMarkdown" />

    <ConfirmDialog
      :model-value="confirmOverwrite"
      :title="t('me.profile.overwriteTitle')"
      :text="t('me.profile.overwriteText')"
      :ok-label="t('me.profile.overwrite')"
      @update:model-value="confirmOverwrite = false"
      @confirm="onConfirmOverwrite"
    />
  </div>
</template>
