<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { CoverLetterFormat, CoverLetterIn, CoverLetterLanguage, CoverLetterOut } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { useCoverLetterStore } from "@/stores/coverLetter";
import { useCoverLetterTemplatesStore } from "@/stores/coverLetterTemplates";
import { useMeStore } from "@/stores/me";

/** Mirrors the backend limit for the free-text notes. */
const NOTES_MAX = 5000;

const props = defineProps<{ modelValue: boolean; applicationId: number; existing: CoverLetterOut | null }>();
const emit = defineEmits<{ "update:modelValue": [boolean]; created: [] }>();

const { t } = useI18n();
const router = useRouter();
const store = useCoverLetterStore();
const templates = useCoverLetterTemplatesStore();
const me = useMeStore();

const format = ref<CoverLetterFormat>("latex");
const templateId = ref<number | null>(null);
const language = ref<CoverLetterLanguage>("posting");
const useProfile = ref(false);
const documentIds = ref<number[]>([]);
const notes = ref("");
const confirming = ref(false);
const busy = ref(false);

const hasProfile = computed(() => !!me.profile?.profile_markdown);
const builtinId = computed(() => templates.items.find((x) => x.builtin)?.id ?? null);
const notesTooLong = computed(() => notes.value.length > NOTES_MAX);
const languages: CoverLetterLanguage[] = ["posting", "de", "en"];

/** Fill the form from the existing letter (or defaults) once the data it depends on is loaded. */
function fill() {
  const ex = props.existing;
  const ctx = (ex?.context ?? {}) as Partial<{ profile: boolean; document_ids: number[]; notes: string }>;
  format.value = ex?.format ?? "latex";
  language.value = ex?.language ?? "posting";
  const known = ex?.template_id != null && templates.items.some((x) => x.id === ex.template_id);
  templateId.value = known ? ex!.template_id : builtinId.value;
  useProfile.value = hasProfile.value && (ex ? ctx.profile === true : true);
  const usable = new Set(me.documents.filter((d) => d.text).map((d) => d.id));
  documentIds.value = (ctx.document_ids ?? []).filter((id) => usable.has(id));
  notes.value = ctx.notes ?? "";
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    confirming.value = false;
    await Promise.all([me.loaded ? undefined : me.load(), templates.loaded ? undefined : templates.load()]);
    fill();
  },
  { immediate: true },
);

function close() {
  emit("update:modelValue", false);
}

function body(): CoverLetterIn {
  return {
    format: format.value,
    template_id: format.value === "latex" ? templateId.value : null,
    language: language.value,
    context: { profile: useProfile.value, document_ids: documentIds.value, notes: notes.value },
  };
}

function submit() {
  if (notesTooLong.value) return;
  if (props.existing) confirming.value = true;
  else void send();
}

async function send() {
  busy.value = true;
  try {
    const ok = await store.create(props.applicationId, body());
    confirming.value = false;
    if (!ok) return;
    emit("created");
    close();
    await router.push({ name: "cover-letter", params: { id: String(props.applicationId) } });
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="640" @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="t('coverLetter.dialog.title')" data-test="cl-dialog">
      <v-card-text>
        <v-btn-toggle v-model="format" mandatory density="comfortable" color="primary" class="mb-4" data-test="cl-format">
          <v-btn value="latex" data-test="cl-format-latex">{{ t("coverLetter.dialog.formatLatex") }}</v-btn>
          <v-btn value="text" data-test="cl-format-text">{{ t("coverLetter.dialog.formatText") }}</v-btn>
        </v-btn-toggle>

        <v-select
          v-if="format === 'latex'"
          v-model="templateId"
          :label="t('coverLetter.dialog.template')"
          :items="templates.items.map((x) => ({ value: x.id, title: x.builtin ? `${x.name} (${t('coverTemplates.builtin')})` : x.name }))"
          data-test="cl-template"
        />
        <v-select
          v-model="language"
          :label="t('coverLetter.dialog.language')"
          :items="languages.map((l) => ({ value: l, title: t(`coverLetter.language.${l}`) }))"
          data-test="cl-language"
        />

        <div class="text-subtitle-2 mb-1">{{ t("coverLetter.dialog.context") }}</div>
        <v-checkbox
          v-model="useProfile"
          :label="t('coverLetter.dialog.profile')"
          :disabled="!hasProfile"
          :hint="hasProfile ? undefined : t('coverLetter.dialog.noProfile')"
          :persistent-hint="!hasProfile"
          density="compact"
          data-test="cl-profile"
        />
        <v-checkbox
          v-for="d in me.documents"
          :key="d.id"
          v-model="documentIds"
          :value="d.id"
          :label="d.display_name"
          :disabled="!d.text"
          :hint="d.text ? undefined : t('coverLetter.dialog.noText')"
          :persistent-hint="!d.text"
          density="compact"
          :data-test="`cl-doc-${d.id}`"
        />
        <v-textarea
          v-model="notes"
          :label="t('coverLetter.dialog.notes')"
          :counter="NOTES_MAX"
          :error="notesTooLong"
          rows="3"
          auto-grow
          class="mt-2"
          data-test="cl-notes"
        />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn data-test="cl-cancel" @click="close">{{ t("common.cancel") }}</v-btn>
        <v-btn color="primary" variant="flat" :loading="busy && !existing" :disabled="busy || notesTooLong" data-test="cl-submit" @click="submit">
          {{ existing ? t("coverLetter.dialog.regenerate") : t("coverLetter.dialog.create") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
  <ConfirmDialog
    v-model="confirming"
    :title="t('coverLetter.dialog.replaceTitle')"
    :text="t('coverLetter.dialog.replaceText')"
    :ok-label="t('coverLetter.dialog.regenerate')"
    :busy="busy"
    @confirm="send"
  />
</template>
